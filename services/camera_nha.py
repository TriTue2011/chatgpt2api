"""Camera nhà — nguồn ảnh của cổng, KHÔNG đi qua Home Assistant.

Nhiều người dùng bot không cài Home Assistant, nên camera phải khai thẳng vào
cổng. Hai đường vào, khai tên tiếng Việt cho từng cái rồi hỏi bằng tên đó:

``go2rtc``
    Đã có sẵn một máy chủ go2rtc thì chỉ cần trỏ tới nó và nêu tên luồng.
    Ảnh tĩnh lấy qua ``GET {base}/api/frame.jpeg?src={src}`` (cổng mặc định
    1984). Đây là đường NÊN dùng khi có: go2rtc giữ sẵn kết nối tới camera nên
    lấy một khung gần như tức thì, còn ffmpeg phải bắt tay RTSP lại từ đầu.

``rtsp``
    Trỏ thẳng vào luồng RTSP của camera, ffmpeg bóc một khung. Không cần cài
    thêm gì, đổi lại mỗi lần chụp tốn vài giây bắt tay.

Sổ camera nằm trong ``config`` dưới khoá ``cameras``, cùng chỗ với
``home_assistant``. Để ở đó chứ không phải một tệp riêng vì tab cài đặt trên web
sửa camera qua đúng đường lưu cấu hình mà mọi card khác đang dùng — thêm tệp
riêng là phải đẻ thêm một bộ endpoint CRUD chỉ để làm lại việc đã có.

URL RTSP thường nhúng luôn mật khẩu, nên mọi hàm liệt kê đều che phần đó — model
không bao giờ nhìn thấy mật khẩu camera.
"""

from __future__ import annotations

import logging
import re
import subprocess
from typing import Any
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

#: Khung gửi cho người xem. Ảnh camera 4K gửi qua Zalo/Telegram là thừa, mà
#: nhiều đầu ghi trả JPEG vài MB.
CANH_GUI = 1600
#: Khung đưa cho AI đọc. Đo trên máy thật (xem README blueprint cảnh báo camera):
#: ba ảnh luồng phụ tốn 978 token ~1,0 giây, ba ảnh luồng chính tốn 8 425 token
#: ~20 giây, cùng kết quả nhận dạng. Ảnh nét chỉ để mắt người.
CANH_AI = 768
#: Chốt an toàn cho khung tải về, trước khi thu nhỏ.
TOI_DA_BYTE = 12_000_000

KIEU_HOP_LE = ("go2rtc", "rtsp")


class LoiCamera(RuntimeError):
    """Chụp không được — thông điệp đã sẵn sàng đọc cho người dùng."""


# ── Sổ camera ────────────────────────────────────────────────────────────────

def _doc_so() -> dict[str, dict[str, Any]]:
    """Sổ camera hiện tại, khoá là tên người dùng đặt."""
    from services.config import config
    so = config.data.get("cameras")
    if not isinstance(so, dict):
        return {}
    return {str(k): dict(v) for k, v in so.items() if isinstance(v, dict)}


def che_bi_mat(url: str) -> str:
    """Bỏ mật khẩu khỏi URL trước khi cho ai đó nhìn thấy.

    ``rtsp://admin:MatKhau@10.0.0.5/stream`` → ``rtsp://admin:***@10.0.0.5/stream``
    """
    if not url:
        return ""
    try:
        p = urlsplit(url)
    except ValueError:
        return re.sub(r"//[^/@]*@", "//***@", url)
    if not p.password:
        return url
    chu = f"{p.username or ''}:***@{p.hostname or ''}"
    if p.port:
        chu += f":{p.port}"
    return urlunsplit((p.scheme, chu, p.path, p.query, p.fragment))


def danh_sach(*, kem_bi_mat: bool = False) -> list[dict[str, Any]]:
    """Danh sách camera. Mặc định che mật khẩu — chỉ lõi chụp mới cần bản thật."""
    ra = []
    for ten, c in sorted(_doc_so().items()):
        m = dict(c)
        m["name"] = ten
        if not kem_bi_mat:
            for khoa in ("url", "url_ai", "base"):
                if m.get(khoa):
                    m[khoa] = che_bi_mat(str(m[khoa]))
            m.pop("password", None)
        ra.append(m)
    return ra


def them(ten: str, kieu: str, *, url: str = "", base: str = "", src: str = "",
         url_ai: str = "", src_ai: str = "",
         username: str = "", password: str = "", ghi_chu: str = "") -> dict[str, Any]:
    """Khai hoặc sửa một camera. Trả về bản ghi đã che mật khẩu.

    Tên đã có thì ghi đè — đó cũng là đường "sửa camera" của card web.

    ``kieu='go2rtc'`` cần ``base`` (vd ``http://172.16.10.38:1984``) và ``src``
    là tên luồng trong cấu hình go2rtc. ``kieu='rtsp'`` cần ``url``.

    ``url_ai`` / ``src_ai`` là **luồng phụ cho AI đọc**, không bắt buộc. Khai nó
    thì ảnh gửi bạn lấy từ luồng chính cho nét, còn ảnh đưa model đọc lấy từ
    luồng phụ cho rẻ. Không khai thì AI đọc luôn luồng chính — chỉ tốn hơn chứ
    không mất tính năng nào.
    """
    ten = (ten or "").strip()
    if not ten:
        raise LoiCamera("Chưa đặt tên cho camera.")
    kieu = (kieu or "").strip().lower()
    if kieu not in KIEU_HOP_LE:
        raise LoiCamera(f"Kiểu '{kieu}' không dùng được, chỉ có: {', '.join(KIEU_HOP_LE)}.")

    ban_ghi: dict[str, Any] = {"kind": kieu, "note": (ghi_chu or "").strip()}
    if kieu == "go2rtc":
        base = (base or "").strip().rstrip("/")
        src = (src or "").strip()
        if not base or not src:
            raise LoiCamera("Camera go2rtc cần cả địa chỉ máy chủ và tên luồng (src).")
        ban_ghi.update(base=base, src=src, src_ai=(src_ai or "").strip(),
                       username=(username or "").strip(), password=password or "")
    else:
        url = (url or "").strip()
        if not url.lower().startswith("rtsp://"):
            raise LoiCamera("Địa chỉ RTSP phải bắt đầu bằng rtsp://")
        url_ai = (url_ai or "").strip()
        if url_ai and not url_ai.lower().startswith("rtsp://"):
            raise LoiCamera("Địa chỉ RTSP của luồng phụ phải bắt đầu bằng rtsp://")
        ban_ghi.update(url=url, url_ai=url_ai)

    from services.config import config

    def _ghi(data: dict) -> None:
        so = data.get("cameras")
        if not isinstance(so, dict):
            so = {}
        so[ten] = ban_ghi
        data["cameras"] = so

    config.mutate(_ghi)
    logger.info({"event": "camera_added", "name": ten, "kind": kieu})
    m = dict(ban_ghi)
    m["name"] = ten
    m.pop("password", None)
    for khoa in ("url", "url_ai", "base"):
        if m.get(khoa):
            m[khoa] = che_bi_mat(str(m[khoa]))
    return m


def xoa(ten: str) -> bool:
    from services.config import config

    def _bo(data: dict) -> bool:
        so = data.get("cameras")
        if not isinstance(so, dict) or ten not in so:
            return False
        del so[ten]
        data["cameras"] = so
        return True

    da_xoa = bool(config.mutate(_bo))
    if da_xoa:
        logger.info({"event": "camera_removed", "name": ten})
    return da_xoa


#: Từ ai cũng nói khi gọi camera, nên không dùng để phân biệt camera nào.
_TU_CHUNG = {"camera", "cam", "xem", "cai", "con", "chiec", "cua", "o", "ngoai",
             "trong", "hinh", "anh", "the", "view"}


def _tu(s: str) -> set[str]:
    from services.agent.vi_text import fold
    return {t for t in re.split(r"[^0-9a-z]+", fold(s)) if t}


def _khop(ten: str, so: dict[str, dict[str, Any]]) -> str | None:
    """Khớp câu người dùng nói với một tên camera đã khai.

    Trả tên camera khi chốt được, ``""`` khi mập mờ, ``None`` khi không từ nào
    dính. Ba kết quả khác nhau vì tầng trên xử lý khác nhau: mập mờ thì hỏi lại,
    không dính thì còn được nới (nhà có đúng một camera).
    """
    q = _tu(ten)
    if not q:
        return None

    # (1) Khớp nguyên cụm, chỉ khác dấu: "sân trước" trúng camera "Sân trước".
    y_het = [k for k in so if _tu(k) == q]
    if len(y_het) == 1:
        return y_het[0]
    if len(y_het) > 1:
        return ""

    # (2) Chấm điểm theo từ RIÊNG. Bỏ từ chung trước khi chấm, nếu không thì
    #     "xem camera sân" và "xem camera bếp" đều được 2 điểm nhờ chữ "camera"
    #     và hoà nhau, dù người dùng đã nói rõ phòng nào.
    q_rieng = q - _TU_CHUNG
    if not q_rieng:
        return None
    diem = [(len(q_rieng & (_tu(k) | _tu(v.get("note") or ""))), k) for k, v in so.items()]
    cao = max((d for d, _ in diem), default=0)
    if cao < 1:
        return None
    dan = [k for d, k in diem if d == cao]
    return dan[0] if len(dan) == 1 else ""


def tim(ten: str) -> tuple[str, dict[str, Any] | None, list[str]]:
    """Khớp tên người dùng nói với camera đã khai.

    Trả ``(tên, bản ghi, gợi ý)``. Bản ghi ``None`` nghĩa là chưa chốt được:
    ``gợi ý`` rỗng là chưa khai camera nào, còn có gợi ý là mập mờ hoặc sai tên —
    hai trường hợp đó bot phải HỎI LẠI chứ không đoán bừa, vì chụp nhầm camera
    phòng ngủ khi người ta hỏi camera sân là chuyện không sửa lại được.
    """
    so = _doc_so()
    if not so:
        return "", None, []

    khop = _khop(ten, so)
    if khop:
        return khop, dict(so[khop], name=khop), sorted(so)
    # Không từ nào dính mà nhà chỉ có đúng một camera thì lấy luôn — "xem camera"
    # lúc đó là câu rõ nghĩa. Mập mờ ("") thì KHÔNG nới, phải hỏi lại.
    if khop is None and len(so) == 1:
        chi_mot = next(iter(so))
        return chi_mot, dict(so[chi_mot], name=chi_mot), sorted(so)
    return "", None, sorted(so)


# ── Bóc một khung ảnh ────────────────────────────────────────────────────────

def kich_thuoc_jpeg(jpeg: bytes) -> tuple[int, int] | None:
    """Đọc rộng×cao từ header JPEG. Không nhận ra thì trả ``None``.

    Đọc bằng tay thay vì gọi ffprobe: chỉ cần lướt vài chục byte đầu, mà mỗi lần
    tránh được một tiến trình con là mỗi lần bớt vài chục mili-giây.
    """
    i, n = 2, len(jpeg)
    if jpeg[:2] != b"\xff\xd8":
        return None
    while i + 9 < n:
        if jpeg[i] != 0xFF:
            i += 1
            continue
        dau = jpeg[i + 1]
        # SOF0…SOF15, trừ DHT(C4), JPG(C8), DAC(CC) — chúng không mang kích thước.
        if 0xC0 <= dau <= 0xCF and dau not in (0xC4, 0xC8, 0xCC):
            cao = int.from_bytes(jpeg[i + 5:i + 7], "big")
            rong = int.from_bytes(jpeg[i + 7:i + 9], "big")
            return (rong, cao) if rong and cao else None
        if dau in (0xD8, 0x01) or 0xD0 <= dau <= 0xD7:
            i += 2
            continue
        i += 2 + int.from_bytes(jpeg[i + 2:i + 4], "big")
    return None


def _thu_nho(jpeg: bytes, canh: int) -> bytes:
    """Thu nhỏ cạnh dài nhất về ``canh`` px. Lỗi thì trả nguyên bản.

    Thu nhỏ là bước làm-đẹp, không phải bước bắt buộc: ffmpeg trục trặc thì thà
    gửi ảnh to còn hơn không có ảnh nào.

    Ảnh đã nhỏ hơn đích thì trả nguyên bản, KHÔNG mã hoá lại. Đo trên camera
    thật: khung luồng phụ 640×480 nặng 27 KB, cho qua ffmpeg với đích 1600 px
    thì ffmpeg không phóng to (đã chặn bằng ``decrease``) nhưng vẫn nén lại và
    ra 69 KB — to gấp hai rưỡi ảnh gốc, mà chất lượng thì kém đi.
    """
    kt = kich_thuoc_jpeg(jpeg)
    if kt and max(kt) <= canh:
        return jpeg
    try:
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
             "-frames:v", "1",
             "-vf", f"scale={canh}:{canh}:force_original_aspect_ratio=decrease",
             "-q:v", "5", "-f", "image2", "pipe:1"],
            input=jpeg, capture_output=True, timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("thu nhỏ ảnh không được: %s", exc)
        return jpeg
    if p.returncode or not p.stdout:
        return jpeg
    return p.stdout


def _chup_go2rtc(cam: dict[str, Any], timeout: float) -> bytes:
    import httpx

    base = str(cam.get("base") or "").rstrip("/")
    src = str(cam.get("src") or "")
    auth = None
    if cam.get("username"):
        auth = (str(cam["username"]), str(cam.get("password") or ""))
    try:
        r = httpx.get(f"{base}/api/frame.jpeg", params={"src": src},
                      auth=auth, timeout=timeout, follow_redirects=True)
    except Exception as exc:
        raise LoiCamera(f"không nối được máy chủ go2rtc ({str(exc)[:120]})") from exc
    if r.status_code == 404:
        raise LoiCamera(f"go2rtc không có luồng tên '{src}'")
    if r.status_code in (401, 403):
        raise LoiCamera("go2rtc từ chối — sai tài khoản hoặc mật khẩu")
    if r.status_code != 200 or not r.content:
        raise LoiCamera(f"go2rtc trả về mã {r.status_code}")
    if len(r.content) > TOI_DA_BYTE:
        raise LoiCamera("khung ảnh quá lớn")
    return r.content


def _chup_rtsp(cam: dict[str, Any], timeout: float) -> bytes:
    """Bóc một khung bằng ffmpeg, cùng cách ``video_vision.trich_khung`` đang làm.

    Ép ``-rtsp_transport tcp`` vì UDP qua wifi hay mất gói giữa chừng, ra khung
    vỡ. Không dùng cờ timeout của ffmpeg — tên cờ đổi giữa các đời (``-stimeout``
    thành ``-timeout``) nên chốt bằng timeout của tiến trình, đời nào cũng đúng.
    """
    url = str(cam.get("url") or "")
    try:
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-rtsp_transport", "tcp", "-i", url, "-frames:v", "1",
             "-q:v", "4", "-f", "image2", "pipe:1"],
            capture_output=True, timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise LoiCamera("máy chủ thiếu ffmpeg nên chưa bóc được ảnh RTSP") from exc
    except subprocess.TimeoutExpired as exc:
        raise LoiCamera(f"camera không trả lời trong {timeout:.0f} giây") from exc
    if p.returncode or not p.stdout:
        loi = (p.stderr or b"").decode("utf-8", "ignore").strip().splitlines()
        raise LoiCamera(f"ffmpeg không lấy được khung ({loi[-1][:120] if loi else 'lỗi không rõ'})")
    if len(p.stdout) > TOI_DA_BYTE:
        raise LoiCamera("khung ảnh quá lớn")
    return p.stdout


def _ban_ghi_luong(cam: dict[str, Any], phu: bool) -> dict[str, Any]:
    """Bản ghi trỏ vào một luồng cụ thể của camera.

    ``phu=True`` lấy luồng phụ nếu có khai, không có thì rơi về luồng chính —
    khai thiếu luồng phụ chỉ tốn thêm token chứ không được im lặng không có ảnh.
    """
    if not phu:
        return cam
    if cam.get("kind") == "go2rtc":
        src = str(cam.get("src_ai") or "").strip()
        return dict(cam, src=src) if src else cam
    url = str(cam.get("url_ai") or "").strip()
    return dict(cam, url=url) if url else cam


def co_luong_phu(cam: dict[str, Any]) -> bool:
    """Camera này có khai luồng phụ riêng cho AI đọc không."""
    khoa = "src_ai" if cam.get("kind") == "go2rtc" else "url_ai"
    return bool(str(cam.get(khoa) or "").strip())


def _lay(ten: str) -> tuple[str, dict[str, Any]]:
    """Tra camera theo tên, ném lỗi đã sẵn sàng đọc nếu chưa chốt được."""
    ten_that, cam, goi_y = tim(ten)
    if cam is None:
        if not goi_y:
            raise LoiCamera("Chưa có camera nào được khai báo.")
        raise LoiCamera("Chưa rõ camera nào. Đang có: " + ", ".join(goi_y))
    # Card web ghi thẳng vào config (đúng khuôn mọi card khác) nên bản ghi không
    # bắt buộc đi qua `them()`. Kiểm lại kiểu ở đây thay vì để `else` rơi vào
    # nhánh RTSP với url rỗng — lúc đó lỗi báo ra là "ffmpeg không lấy được
    # khung", trỏ người dùng đi sửa sai chỗ.
    kieu = str(cam.get("kind") or "")
    if kieu not in KIEU_HOP_LE:
        raise LoiCamera(f"Camera '{ten_that}' khai kiểu '{kieu}' không dùng được — "
                        f"chỉ có: {', '.join(KIEU_HOP_LE)}.")
    return ten_that, cam


def _bocc(cam: dict[str, Any], timeout: float) -> bytes:
    """Bóc một khung từ bản ghi đã chốt luồng."""
    return (_chup_go2rtc(cam, timeout) if cam.get("kind") == "go2rtc"
            else _chup_rtsp(cam, timeout))


def chup_tho(ten: str, *, phu: bool = False, timeout: float = 20.0) -> tuple[str, bytes]:
    """Bóc một khung nguyên cỡ. Trả ``(tên thật, JPEG)``.

    Ném ``LoiCamera`` với câu đã sẵn sàng đọc cho người dùng.
    """
    ten_that, cam = _lay(ten)
    return ten_that, _bocc(_ban_ghi_luong(cam, phu), timeout)


def chup(ten: str, *, cho_ai: bool = False, timeout: float = 20.0) -> tuple[str, bytes]:
    """Chụp một khung đã thu nhỏ sẵn.

    ``cho_ai=True`` đọc luồng phụ (nếu có khai) và thu nhỏ mạnh hơn, vì ảnh chỉ
    để model đọc chứ không để người xem.
    """
    ten_that, jpeg = chup_tho(ten, phu=cho_ai, timeout=timeout)
    return ten_that, _thu_nho(jpeg, CANH_AI if cho_ai else CANH_GUI)


def chup_hai_co(ten: str, *, timeout: float = 20.0) -> tuple[str, bytes, bytes]:
    """Ảnh gửi người và ảnh cho AI đọc: ``(tên, ảnh gửi, ảnh cho AI)``.

    Không khai luồng phụ thì bóc **một** khung rồi thu nhỏ hai kiểu — hai tấm
    chắc chắn cùng một khoảnh khắc, và chỉ tốn một phiên với camera.

    Khai luồng phụ thì bấm hai luồng. Cách bấm khác nhau theo nguồn, và đây là
    chỗ đo thật đã sửa lại thiết kế:

    - **go2rtc**: bấm song song. go2rtc giữ sẵn một kết nối tới camera rồi phục
      vụ nhiều khách, nên hai lời gọi HTTP cùng lúc không phiền camera.
    - **RTSP thẳng**: bấm nối đuôi. Đo trên camera Dahua thật: hai phiên RTSP
      song song **hỏng cả hai** (hết 25 giây chờ, thử lại vẫn hỏng), trong khi
      nối đuôi xong trong 8,6 giây. Camera loại này chỉ có vài khe phiên, mở
      cùng lúc là nghẽn. Nối đuôi thì hai tấm cách nhau vài giây — đó là cái giá
      của việc khai hai luồng RTSP, và cũng là lý do nên cân nhắc **không khai**
      luồng phụ khi đi RTSP thẳng.
    """
    ten_that, cam = _lay(ten)

    if not co_luong_phu(cam):
        jpeg = _bocc(cam, timeout)
        return ten_that, _thu_nho(jpeg, CANH_GUI), _thu_nho(jpeg, CANH_AI)

    ban_chinh = _ban_ghi_luong(cam, False)
    ban_phu = _ban_ghi_luong(cam, True)

    def _phu_hoac_chinh(lay_phu, chinh: bytes) -> bytes:
        """Luồng phụ hỏng KHÔNG được làm hỏng cả lượt — rơi về luồng chính."""
        try:
            return lay_phu()
        except LoiCamera as exc:
            logger.warning({"event": "camera_luong_phu_hong",
                            "camera": ten_that, "loi": str(exc)[:150]})
            return chinh

    if cam.get("kind") == "go2rtc":
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_chinh = pool.submit(_bocc, ban_chinh, timeout)
            f_phu = pool.submit(_bocc, ban_phu, timeout)
            chinh = f_chinh.result()
            phu = _phu_hoac_chinh(f_phu.result, chinh)
    else:
        chinh = _bocc(ban_chinh, timeout)
        phu = _phu_hoac_chinh(lambda: _bocc(ban_phu, timeout), chinh)

    return ten_that, _thu_nho(chinh, CANH_GUI), _thu_nho(phu, CANH_AI)
