"""Tiến trình con: nói ra loa camera Hikvision / EZVIZ qua HCNetSDK (cổng thiết bị 8000).

Vì sao: EZVIZ H6C nhà (đo 28/09/2026) không có đường nói nào khác — RTSP không có kênh ngược,
không ONVIF, cổng HTTP/ISAPI bị khoá — nhưng HCNetSDK qua cổng 8000 mở được kênh đàm thoại và
loa phát thật (chủ máy nghe xác nhận). Camera báo mã AAC 16 kHz.

Vì sao là tiến trình con: HCNetSDK là thư viện mã máy của hãng, nạp bằng ctypes; lỗi trong đó
làm sập cả tiến trình — chạy riêng thì c2a không sập theo.

Vì sao sống giữa các lượt nói (giữ đăng nhập): đo 29/09/2026 trên H6C, đăng nhập 0,6–1,3 s và
đăng xuất 0,5 s, còn mở kênh chỉ 0,02–0,27 s. Đăng nhập lại mỗi lượt bộ đàm thì tiếng dồn hàng
đợi suốt lúc ấy và cả câu phát trễ theo. Ngồi yên ``HIK_NGHI`` giây thì tự đăng xuất và thoát.

Thư viện KHÔNG nằm trong ảnh / git (bản quyền Hikvision): tải "Device Network SDK (Linux 64-bit)"
từ trang Hikvision, chép thư mục ``lib`` vào ``data/hcnetsdk/lib``.

Giao thức với tiến trình cha (giống bản C ``hik_noi.c`` của tích hợp dahua_talk cho HA):
    argv: ip cổng tài_khoản     env: HIK_LIB (thư mục lib), HIK_MK (mật khẩu), HIK_NGHI (giây)
    kênh báo = fd gốc của stdout, mỗi dòng một tin:
        "SAN <mã> <tần_số>" đăng nhập xong | "OK" kênh đã mở | "DONG" kênh đã đóng
        "LOI <thông điệp>" hỏng (lúc đăng nhập thì thoát luôn)
    stdin: mỗi mục = 4 byte độ dài (big-endian) + dữ liệu
        0xFFFFFFFF = mở kênh đàm thoại; n > 0 = một khung tiếng; 0 = phát nốt rồi đóng kênh
        hết stdin = đóng kênh (nếu đang mở), đăng xuất, thoát
    Mã: AAC (khung ADTS 1024 mẫu) hoặc G711U / G711A (khung 160 byte = 20 ms ở 8 kHz).
"""

from __future__ import annotations

import ctypes as C
import os
import select
import struct
import sys
import time

MA = {0: "G722", 1: "G711U", 2: "G711A", 7: "AAC", 12: "AAC"}
TAN_SO = {0: 16000, 1: 16000, 2: 32000, 3: 48000, 4: 44100, 5: 8000}
MO_KENH = 0xFFFFFFFF
#: Sau khung cuối chờ ngần này giây cho loa phát nốt rồi mới đóng kênh.
_DUOI_GIAY = 0.5


class _SdkPath(C.Structure):
    _fields_ = [("sPath", C.c_char * 256), ("byRes", C.c_ubyte * 128)]


class _LoginInfo(C.Structure):
    _fields_ = [("sDeviceAddress", C.c_char * 129), ("byUseTransport", C.c_ubyte),
                ("wPort", C.c_uint16), ("sUserName", C.c_char * 64), ("sPassword", C.c_char * 64),
                ("cbLoginResult", C.c_void_p), ("pUser", C.c_void_p), ("bUseAsynLogin", C.c_int),
                ("byProxyType", C.c_ubyte), ("byUseUTCTime", C.c_ubyte), ("byLoginMode", C.c_ubyte),
                ("byHttps", C.c_ubyte), ("iProxyID", C.c_int), ("byVerifyMode", C.c_ubyte),
                ("byRes3", C.c_ubyte * 119)]


class _AudioComp(C.Structure):
    _fields_ = [("byAudioEncType", C.c_ubyte), ("byAudioSamplingRate", C.c_ubyte),
                ("byAudioBitRate", C.c_ubyte), ("byres", C.c_ubyte * 4), ("bySupport", C.c_ubyte)]


def _doc_du(f, n: int) -> bytes:
    du = b""
    while len(du) < n:
        b = f.read(n - len(du))
        if not b:
            return b""
        du += b
    return du


def chay(ip: str, cong: int, user: str) -> int:
    # Kênh báo = stdout gốc; stdout của tiến trình (SDK tự in rác vào đó) chuyển sang stderr.
    bao = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)
    lib = os.environ.get("HIK_LIB", "")
    nghi = float(os.environ.get("HIK_NGHI") or 60)
    try:
        for dep in ("libcrypto.so.1.1", "libssl.so.1.1", "libhpr.so", "libHCCore.so"):
            if os.path.exists(os.path.join(lib, dep)):
                C.CDLL(os.path.join(lib, dep), mode=C.RTLD_GLOBAL)
        sdk = C.CDLL(os.path.join(lib, "libhcnetsdk.so"), mode=C.RTLD_GLOBAL)
    except OSError as exc:
        bao.write(f"LOI không nạp được HCNetSDK ({exc})\n")
        return 2
    p = _SdkPath()
    p.sPath = (lib.rstrip("/") + "/").encode()
    sdk.NET_DVR_SetSDKInitCfg(2, C.byref(p))
    sdk.NET_DVR_Init()
    sdk.NET_DVR_SetConnectTime(5000, 1)
    li = _LoginInfo()
    li.sDeviceAddress = ip.encode()
    li.wPort = cong
    li.sUserName = user.encode()
    li.sPassword = os.environ.get("HIK_MK", "").encode()
    uid = sdk.NET_DVR_Login_V40(C.byref(li), (C.c_ubyte * 1024)())
    if uid < 0:
        bao.write(f"LOI đăng nhập cổng {cong} không được (mã {sdk.NET_DVR_GetLastError()})\n")
        sdk.NET_DVR_Cleanup()
        return 3
    h = -1
    try:
        ac = _AudioComp()
        sdk.NET_DVR_GetCurrentAudioCompress(uid, C.byref(ac))
        ma = MA.get(ac.byAudioEncType)
        tan_so = 8000 if ma in ("G711U", "G711A") else TAN_SO.get(ac.byAudioSamplingRate, 16000)
        if ma not in ("AAC", "G711U", "G711A"):
            bao.write(f"LOI camera đòi mã đàm thoại chưa hỗ trợ ({ac.byAudioEncType})\n")
            return 4
        cb_t = C.CFUNCTYPE(None, C.c_int, C.c_void_p, C.c_uint, C.c_ubyte, C.c_void_p)
        cb = cb_t(lambda *_a: None)         # bỏ tiếng mic camera gửi về
        # Nghe ngoại lệ đàm thoại (EXCEPTION_AUDIOEXCHANGE = 0x8001) — camera rớt mạng giữa bài thì SDK báo ở đây.
        kenh_hong = [-1]
        ngoai_le_t = C.CFUNCTYPE(None, C.c_uint, C.c_int, C.c_int, C.c_void_p)

        def _ngoai_le(loai, _uid, kenh, _u):
            if loai == 0x8001:
                kenh_hong[0] = kenh
        ngoai_le = ngoai_le_t(_ngoai_le)
        if hasattr(sdk, "NET_DVR_SetExceptionCallBack_V30"):
            sdk.NET_DVR_SetExceptionCallBack_V30(0, None, ngoai_le, None)
        sdk.NET_DVR_VoiceComSendData.restype = C.c_int
        sdk.NET_DVR_StartVoiceCom_MR_V30.restype = C.c_int
        bao.write(f"SAN {ma} {tan_so}\n")
        vao = sys.stdin.buffer
        t0, da_phat = None, 0.0

        def dong_kenh() -> None:
            nonlocal h
            if h >= 0:
                if t0 is not None:
                    time.sleep(max(0.0, t0 + da_phat - time.monotonic()) + _DUOI_GIAY)
                sdk.NET_DVR_StopVoiceCom(h)
                h = -1

        while True:
            if h < 0 and not select.select([vao], [], [], nghi)[0]:
                break                       # kênh đóng, ngồi yên quá lâu
            dau = _doc_du(vao, 4)
            if not dau:
                break
            n = struct.unpack(">I", dau)[0]
            if n == MO_KENH:
                if h < 0:
                    kenh_hong[0] = -1
                    h = sdk.NET_DVR_StartVoiceCom_MR_V30(uid, 1, cb, None)
                bao.write("OK\n" if h >= 0 else
                          f"LOI camera không mở kênh đàm thoại (mã {sdk.NET_DVR_GetLastError()})\n")
                t0, da_phat = None, 0.0
                continue
            if n == 0:
                dong_kenh()
                bao.write("DONG\n")
                continue
            khung = _doc_du(vao, n)
            if not khung:
                break
            if h < 0:
                continue                    # khung lạc lúc kênh đóng: bỏ
            if t0 is None:
                t0 = time.monotonic()
            cho = t0 + da_phat - time.monotonic()
            if cho > 0:
                time.sleep(cho)
            # Kiểm kết quả gửi (issue #2 của dahua_talk: bỏ qua nó thì camera rớt mạng mà vẫn «đang phát» 44 phút).
            gui_duoc = sdk.NET_DVR_VoiceComSendData(h, C.c_char_p(khung), n)
            if not gui_duoc or kenh_hong[0] == h:
                bao.write(f"LOI gửi tiếng hỏng (mã {sdk.NET_DVR_GetLastError()})\n" if not gui_duoc
                          else "LOI camera rớt kênh đàm thoại (ngoại lệ 0x8001)\n")
                sdk.NET_DVR_StopVoiceCom(h)
                h = -1                      # khung còn lại của lượt bị bỏ; vẫn giữ đăng nhập
                continue
            da_phat += 1024 / tan_so if ma == "AAC" else n / 8000
        dong_kenh()
        return 0
    finally:
        if h >= 0:
            sdk.NET_DVR_StopVoiceCom(h)
        sdk.NET_DVR_Logout(uid)
        sdk.NET_DVR_Cleanup()


if __name__ == "__main__":
    sys.exit(chay(sys.argv[1], int(sys.argv[2]), sys.argv[3]))
