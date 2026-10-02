"""Chi tiêu từ EMAIL — đọc thư báo biến động số dư của ngân hàng / ví rồi tự ghi vào sổ.

Chủ máy 02/10/2026: "chi tiêu chưa có chỗ kết nối với mail để lấy chi tiêu (từ 1 hoặc nhiều địa chỉ mail, từ 1
hoặc nhiều mail)"; chọn: MỖI SỔ tự nối hộp thư của mình (đúng luật "mỗi account chỉ xem được chi tiêu của họ"),
và thư đọc được thì TỰ GHI rồi báo để sửa.

* Hộp thư thuộc sổ (bảng ``hop_thu``): IMAP + mật khẩu ứng dụng (mã hoá Fernet, khoá ở ``data/chi_tieu/email.key``
  — cùng cách ``services/mcp_oauth.py``) + danh sách NGƯỜI GỬI được đọc (địa chỉ, hoặc ``@tên-miền``). Không có
  người gửi nào thì không đọc gì — không bao giờ đưa thư riêng tư khác cho model.
* Mở hộp thư CHỈ-ĐỌC (``EXAMINE`` + ``BODY.PEEK``): không đánh dấu đã đọc, không xoá, không đổi gì trong hộp thư.
  Lần đầu đọc từ đầu kỳ lương đang chạy; sau đó theo UID mới. Một thư (Message-ID) chỉ ghi một lần mỗi sổ, kể
  cả khi nó nằm ở hai hộp thư.
* Hiểu thư bằng MODEL theo hướng dẫn, không bằng danh sách mẫu thư từng ngân hàng (danh sách luôn thiếu): model trả
  chi / thu / không phải giao dịch, số tiền, nội dung, và chọn hũ trong danh sách hũ của sổ. Dãy số dài (số tài
  khoản, số thẻ) được che trước khi gửi model.
* Chi → ``nghiep_vu.ghi_chi`` (nguồn ``email``); thu → thu nhập thêm của kỳ. Ghi xong nhắn các kênh chat đã liên
  kết với sổ, kèm cách sửa / xoá trên web.
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import imaplib
import json
import os
import re
import threading
import time
from datetime import date, datetime
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any, Callable

from services.chi_tieu import kho, ngan_sach as ns, nghiep_vu as nv
from utils.log import logger

QUET_GIAY = 180
_TOI_DA_MOI_LUOT = 50
_RE_NGUOI_GUI = re.compile(r"(?:[^@\s]+)?@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_khoa_quet = threading.Lock()
_luong: threading.Thread | None = None


# ── Mã hoá mật khẩu hộp thư ──────────────────────────────────────────────────
def _cipher():
    from cryptography.fernet import Fernet
    p = kho._duong().parent / "email.key"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(Fernet.generate_key())
    return Fernet(p.read_bytes())


def _ma_hoa(s: str) -> str:
    return _cipher().encrypt(s.encode()).decode()


def _giai_ma(s: str) -> str:
    return _cipher().decrypt(s.encode()).decode()


# ── Hộp thư của sổ ───────────────────────────────────────────────────────────
def _cong_khai(r: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in r.items() if k != "mat_khau"} | {"nguoi_gui": json.loads(r["nguoi_gui"] or "[]")}


def ds_hop_thu(so_id: int) -> dict[str, Any]:
    with kho.db() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM hop_thu WHERE so_id=? ORDER BY id", (so_id,))]
    return {"hop_thu": [_cong_khai(r) for r in rows]}


def _mot(so_id: int, id_: int) -> dict[str, Any]:
    with kho.db() as c:
        r = c.execute("SELECT * FROM hop_thu WHERE so_id=? AND id=?", (so_id, int(id_))).fetchone()
    if r is None:
        raise nv.LoiChiTieu("Không có hộp thư này trong sổ của bạn.")
    return dict(r)


def _kiem_nguoi_gui(x: Any) -> list[str]:
    ds = [str(v).strip().lower() for v in (x if isinstance(x, list) else str(x or "").replace(",", "\n").split("\n"))]
    ds = [v for v in dict.fromkeys(ds) if v]
    if not ds:
        raise nv.LoiChiTieu("Cần ít nhất một địa chỉ người gửi (vd thư báo của ngân hàng) — bot chỉ đọc thư của họ.")
    sai = [v for v in ds if not _RE_NGUOI_GUI.fullmatch(v)]
    if sai:
        raise nv.LoiChiTieu(f"Địa chỉ người gửi chưa đúng dạng: {', '.join(sai[:3])} (vd info@vcb.com.vn hoặc @vcb.com.vn).")
    return ds


def dau_ky(s: dict[str, Any], hom_nay: date | None = None) -> date:
    """Ngày bắt đầu kỳ lương đang chạy — lần đầu nối chỉ đọc thư từ đây."""
    h = hom_nay or date.today()
    nhan = ns.nhan_ky(h, ns.ngay_bat_dau(s))
    nam, thang = (int(x) for x in nhan.split("-"))
    return date(nam, thang, ns.ngay_bat_dau(s))


def luu_hop_thu(so_id: int, *, id_: Any = None, ten: Any = "", imap_host: Any = "", imap_port: Any = 993,
                dia_chi: Any = "", mat_khau: Any = "", nguoi_gui: Any = None, bat: Any = True) -> dict[str, Any]:
    host = str(imap_host or "").strip().lower()
    dc = str(dia_chi or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", host):
        raise nv.LoiChiTieu("Máy chủ IMAP chưa đúng (Gmail: imap.gmail.com).")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", dc):
        raise nv.LoiChiTieu("Địa chỉ email chưa đúng.")
    try:
        cong = int(imap_port or 993)
    except (TypeError, ValueError):
        raise nv.LoiChiTieu("Cổng IMAP phải là số (thường 993).") from None
    ng = json.dumps(_kiem_nguoi_gui(nguoi_gui), ensure_ascii=False)
    truong = {"ten": str(ten or dc)[:60], "imap_host": host, "imap_port": cong, "dia_chi": dc,
              "nguoi_gui": ng, "bat": 1 if bat else 0}
    mk = str(mat_khau or "").replace(" ", "")
    with kho.db() as c:
        if id_:
            _mot(so_id, int(id_))
            if mk:
                truong["mat_khau"] = _ma_hoa(mk)
            dat = ", ".join(f"{k}=?" for k in truong)
            c.execute(f"UPDATE hop_thu SET {dat}, loi='' WHERE so_id=? AND id=?",  # nosec B608 — khoá cố định ở trên
                      (*truong.values(), so_id, int(id_)))
            moi = int(id_)
        else:
            if not mk:
                raise nv.LoiChiTieu("Cần mật khẩu ứng dụng của hộp thư (Gmail: myaccount.google.com/apppasswords).")
            s = kho.so(so_id)
            cur = c.execute(
                "INSERT INTO hop_thu (so_id, ten, imap_host, imap_port, dia_chi, mat_khau, nguoi_gui, bat, tu_ngay)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (so_id, truong["ten"], host, cong, dc, _ma_hoa(mk), ng, truong["bat"], dau_ky(s).isoformat()))  # type: ignore[arg-type]
            moi = int(cur.lastrowid)
    return {"id": moi}


def xoa_hop_thu(so_id: int, id_: int) -> dict[str, Any]:
    _mot(so_id, id_)
    with kho.db() as c:
        c.execute("DELETE FROM hop_thu WHERE so_id=? AND id=?", (so_id, int(id_)))
    return {"da_xoa": True}


# ── Đọc hộp thư ──────────────────────────────────────────────────────────────
def _mo(h: dict[str, Any]) -> tuple[imaplib.IMAP4, str]:
    """Mở INBOX CHỈ-ĐỌC; trả (kết nối, UIDVALIDITY)."""
    from services.email_channel import _imap_connect
    m = _imap_connect({"imap_host": h["imap_host"], "imap_port": h["imap_port"]}, timeout=30)
    m.login(h["dia_chi"], _giai_ma(h["mat_khau"]))
    typ, _ = m.select("INBOX", readonly=True)
    if typ != "OK":
        raise RuntimeError("Không mở được hộp INBOX.")
    uv = (getattr(m, "untagged_responses", {}).get("UIDVALIDITY") or [b""])[0]
    return m, uv.decode("ascii", "ignore") if isinstance(uv, bytes) else str(uv)


def _loi_de_hieu(exc: Exception, host: str) -> str:
    from services.email_channel import _friendly_error
    return _friendly_error(exc, host)


def _uid_moi(m: imaplib.IMAP4, h: dict[str, Any], uv: str) -> list[int]:
    """UID thư của các người gửi đã khai, mới hơn lần trước (hoặc từ ``tu_ngay`` khi UIDVALIDITY đổi / lần đầu)."""
    ra: set[int] = set()
    tu = datetime.fromisoformat(h["tu_ngay"]).strftime("%d-%b-%Y")
    for ng in json.loads(h["nguoi_gui"] or "[]"):
        if uv == h["uid_validity"] and h["uid_cuoi"]:
            tieu_chi = f'UID {int(h["uid_cuoi"]) + 1}:* FROM "{ng}"'
        else:
            tieu_chi = f'SINCE {tu} FROM "{ng}"'
        typ, dl = m.uid("SEARCH", None, tieu_chi)
        if typ == "OK" and dl and dl[0]:
            ra |= {int(x) for x in dl[0].split()}
    cuoi = int(h["uid_cuoi"]) if uv == h["uid_validity"] else 0
    return sorted(u for u in ra if u > cuoi)


def _khop_nguoi_gui(dia_chi: str, ds: list[str]) -> bool:
    """Đúng địa chỉ; khai ``@tên-miền`` thì khớp tên miền đó và tên miền con của nó (info.vcb.com.vn), không khớp
    tên miền chỉ có cùng đuôi chữ (gia-vcb.com.vn)."""
    d = dia_chi.lower()
    return any((d.endswith(x) or d.endswith("." + x[1:])) if x.startswith("@") else d == x for x in ds)


def che_so(s: str) -> str:
    """Dãy ≥ 8 chữ số liền (số tài khoản, số thẻ) → giữ 4 số cuối. Số tiền có dấu phân cách nên không bị đụng."""
    return re.sub(r"\d{8,}", lambda m: "…" + m.group(0)[-4:], s)


# ── Model hiểu thư ───────────────────────────────────────────────────────────
HUONG_DAN = (
    "Em đọc MỘT email gửi tới chủ tài khoản. Nếu đó là thông báo một GIAO DỊCH tiền của chính chủ tài khoản "
    "(biến động số dư, thanh toán thẻ, chuyển khoản đi / đến, ví điện tử…), trả về giao dịch đó; quảng cáo, mã OTP, "
    "sao kê tổng hợp, thông báo bảo mật thì KHÔNG phải giao dịch.\n"
    "- loai: \"chi\" (tiền ra khỏi tài khoản chủ), \"thu\" (tiền vào), \"khong\" (không phải giao dịch).\n"
    "- so_tien: số nguyên đồng Việt Nam, dương, KHÔNG phải số dư sau giao dịch.\n"
    "- noi_dung: ngắn gọn tiếng Việt, ưu tiên nội dung giao dịch / nơi nhận (vd \"Grab đi làm\", \"Siêu thị WinMart\").\n"
    "- hu: với loai chi, chọn ĐÚNG MỘT tên trong danh sách hũ cho sẵn, hợp nhất với nội dung; thu thì để trống.\n"
    "Chỉ trả JSON một dòng: {\"loai\": \"chi|thu|khong\", \"so_tien\": 0, \"noi_dung\": \"\", \"hu\": \"\"}"
)


def _doc_json(s: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", s or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def hieu_thu(chu_de: str, noi_dung: str, ten_hu: list[str], goi: Callable[[str, str], str] | None = None
             ) -> dict[str, Any] | None:
    """Model đọc thư → {loai, so_tien, noi_dung, hu}; trả None khi model lỗi hoặc trả sai khuôn (thư để lượt sau)."""
    de = (f"Danh sách hũ: {', '.join(ten_hu)}\n\nTiêu đề: {che_so(chu_de)}\n\nNội dung:\n{che_so(noi_dung)[:4000]}")
    tra = (goi or _goi_model)(HUONG_DAN, de)
    d = _doc_json(tra)
    if not d or d.get("loai") not in ("chi", "thu", "khong"):
        return None
    if d["loai"] == "khong":
        return {"loai": "khong"}
    v = d.get("so_tien")
    # Số (185000 / 185000.0) giữ nguyên; chuỗi («185,000», «185.000 VND») bỏ mọi dấu phân cách. Bỏ dấu chấm của
    # SỐ THỰC thì 185000.0 thành 1.850.000 — gấp 10 lần.
    tien = int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else int(re.sub(r"\D", "", str(v or "")) or 0)
    if not 0 < tien < 10 ** 11:
        return None
    return {"loai": d["loai"], "so_tien": tien, "noi_dung": str(d.get("noi_dung") or "").strip()[:200],
            "hu": str(d.get("hu") or "").strip()}


def _goi_model(huong: str, de: str) -> str:
    from services.agent import model_hints
    from services.agent.runtime import call_model, content_of
    r = call_model(model_hints.resolve("chat"), [{"role": "system", "content": huong}, {"role": "user", "content": de}],
                   max_tokens=400, timeout=90, no_smart_home=True, allowed_groups=set())
    if r.get("error"):
        raise RuntimeError(str(r["error"])[:200])
    return content_of(r) or ""


# ── Ghi sổ ───────────────────────────────────────────────────────────────────
def _da_doc(so_id: int, khoa: str) -> bool:
    with kho.db() as c:
        return c.execute("SELECT 1 FROM thu_da_doc WHERE so_id=? AND khoa=?", (so_id, khoa)).fetchone() is not None


def _ghi_da_doc(so_id: int, khoa: str, ket_qua: str) -> None:
    with kho.db() as c:
        c.execute("INSERT OR IGNORE INTO thu_da_doc (so_id, khoa, ket_qua, luc) VALUES (?,?,?,?)",
                  (so_id, khoa, ket_qua[:200], kho.bay_gio()))


def xu_ly_thu(so_id: int, raw: bytes, nguoi_gui: list[str], goi: Callable[[str, str], str] | None = None
              ) -> tuple[str, dict[str, Any] | None]:
    """Một thư thô → ghi sổ. Trả ("ghi", mục để báo) | ("bo", None) — người gửi khác, đã ghi, không phải giao dịch |
    ("cho", None) — model lỗi / sai khuôn: KHÔNG đánh dấu, lượt sau đọc lại."""
    from services.email_channel import _decode_hdr, _extract_body
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    gui = parseaddr(str(msg.get("From") or ""))[1]
    if not _khop_nguoi_gui(gui, nguoi_gui):
        return "bo", None                 # IMAP FROM khớp chuỗi con — lọc lại cho đúng địa chỉ
    mid = str(msg.get("Message-ID") or "").strip()
    chu_de = _decode_hdr(msg.get("Subject"))
    khoa = mid or hashlib.sha256(f"{gui}|{msg.get('Date')}|{chu_de}".encode()).hexdigest()
    if _da_doc(so_id, khoa):
        return "bo", None
    hus = kho.ds_hu(so_id)
    kq = hieu_thu(chu_de, _extract_body(msg, 6000), [h["ten"] for h in hus], goi)
    if kq is None:
        return "cho", None
    if kq["loai"] == "khong":
        _ghi_da_doc(so_id, khoa, "khong")
        return "bo", None
    try:
        luc = parsedate_to_datetime(str(msg.get("Date"))).astimezone().strftime("%d/%m %H:%M")
    except (TypeError, ValueError):
        luc = ""
    nd = kq["noi_dung"] or chu_de[:80]
    if kq["loai"] == "thu":
        r = nv.ghi_ky("thu_nhap_them", so_id, f"{nd} (email)", kq["so_tien"])
        muc = {"loai": "thu", "so_tien": kq["so_tien"], "noi_dung": nd, "luc": luc, "id": r.get("id")}
    else:
        try:
            h = nv.tim_hu(so_id, kq["hu"])
        except nv.LoiChiTieu:
            h = min(hus, key=lambda x: x["thu_tu"]) if hus else None
            nd = f"{nd} (chưa rõ hũ)"
        if h is None:
            return "bo", None
        r = nv.ghi_chi(so_id, h["id"], kq["so_tien"], nd, xac_nhan_vuot_tong=True, nguon="email")
        muc = {"loai": "chi", "so_tien": kq["so_tien"], "noi_dung": nd, "luc": luc, "hu": r.get("hu"),
               "id": r.get("id"), "con_lai": r.get("con_lai"), "canh_bao": r.get("canh_bao")}
    _ghi_da_doc(so_id, khoa, f"{kq['loai']}:{kq['so_tien']}")
    return "ghi", muc


def _tin(muc: dict[str, Any]) -> str:
    tien = f"{muc['so_tien']:,}".replace(",", ".") + "đ"
    if muc["loai"] == "thu":
        dau = f"📧 Vừa ghi THU {tien} «{muc['noi_dung']}» vào thu nhập thêm"
    else:
        dau = f"📧 Vừa ghi CHI {tien} «{muc['noi_dung']}» vào hũ {muc.get('hu')}"
        if muc.get("con_lai") is not None:
            dau += f" (hũ còn {muc['con_lai']:,}đ)".replace(",", ".")
    dau += f" — từ thư lúc {muc['luc']}." if muc.get("luc") else " — từ email."
    if muc.get("canh_bao"):
        dau += f"\n⚠️ {muc['canh_bao']}"
    return dau + "\nSai thì sửa / xoá ở tab Chi tiêu trên web, hoặc nhắn em."


def quet_hop_thu(h: dict[str, Any], *, goi: Callable[[str, str], str] | None = None,
                 gui: Callable[[int, str], int] | None = None) -> dict[str, Any]:
    """Quét một hộp thư; mỗi thư ghi được thì báo. Lỗi kết nối ghi vào ``loi`` của hộp thư, không ném."""
    from services.chi_tieu.canh_bao import _gui
    gui = gui or _gui
    so_id, ghi = int(h["so_id"]), []
    try:
        m, uv = _mo(h)
    except Exception as exc:  # noqa: BLE001 — hộp thư hỏng không chặn hộp khác
        loi = _loi_de_hieu(exc, h["imap_host"])
        with kho.db() as c:
            c.execute("UPDATE hop_thu SET loi=?, luc_quet=? WHERE id=?", (loi, kho.bay_gio(), h["id"]))
        return {"loi": loi, "da_ghi": 0}
    try:
        uids = _uid_moi(m, h, uv)
        xong = int(h["uid_cuoi"]) if uv == h["uid_validity"] else 0
        for u in uids[:_TOI_DA_MOI_LUOT]:
            typ, dl = m.uid("FETCH", str(u), "(BODY.PEEK[])")
            raw = next((x[1] for x in dl or [] if isinstance(x, tuple) and len(x) > 1), None) if typ == "OK" else None
            if raw is None:
                break
            tt, muc = xu_ly_thu(so_id, raw, json.loads(h["nguoi_gui"] or "[]"), goi)
            if tt == "cho":
                break                     # model chưa hiểu được: dừng ở đây, lượt sau đọc lại từ thư này
            if muc:
                ghi.append(muc)
                try:
                    gui(so_id, _tin(muc))
                except Exception as exc:  # noqa: BLE001 — đã ghi sổ; báo hỏng thì vẫn thấy trên web
                    logger.warning({"event": "chi_tieu_email_bao_loi", "so_id": so_id, "error": str(exc)[:160]})
            xong = u
        with kho.db() as c:
            c.execute("UPDATE hop_thu SET uid_validity=?, uid_cuoi=?, luc_quet=?, loi='', so_da_ghi=so_da_ghi+?"
                      " WHERE id=?", (uv, xong, kho.bay_gio(), len(ghi), h["id"]))
    except Exception as exc:  # noqa: BLE001
        loi = _loi_de_hieu(exc, h["imap_host"])
        with kho.db() as c:
            c.execute("UPDATE hop_thu SET loi=?, luc_quet=? WHERE id=?", (loi, kho.bay_gio(), h["id"]))
        return {"loi": loi, "da_ghi": len(ghi), "ghi": ghi}
    finally:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass
    if ghi:
        logger.info({"event": "chi_tieu_email_ghi", "so_id": so_id, "hop_thu": h["id"], "so_muc": len(ghi)})
    return {"da_ghi": len(ghi), "ghi": ghi}


def quet_ngay(so_id: int, id_: int) -> dict[str, Any]:
    with _khoa_quet:
        return quet_hop_thu(_mot(so_id, id_))


def thu_ket_noi(so_id: int, id_: int) -> dict[str, Any]:
    h = _mot(so_id, id_)
    try:
        m, _uv = _mo(h)
    except Exception as exc:  # noqa: BLE001
        raise nv.LoiChiTieu(_loi_de_hieu(exc, h["imap_host"])) from None
    try:
        so = len(_uid_moi(m, {**h, "uid_validity": "", "uid_cuoi": 0}, ""))
    finally:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass
    return {"ket_noi": True, "so_thu_tu_dau_ky": so}


# ── Vòng nền ─────────────────────────────────────────────────────────────────
def quet_tat_ca() -> None:
    with kho.db() as c:
        ds = [dict(r) for r in c.execute("SELECT * FROM hop_thu WHERE bat=1")]
    for h in ds:
        with _khoa_quet:
            try:
                quet_hop_thu(h)
            except Exception as exc:  # noqa: BLE001
                logger.warning({"event": "chi_tieu_email_loi", "hop_thu": h["id"], "error": str(exc)[:160]})


def _vong() -> None:
    while True:
        time.sleep(QUET_GIAY)
        quet_tat_ca()


def start() -> None:
    global _luong
    if _luong is not None and _luong.is_alive():
        return
    _luong = threading.Thread(target=_vong, name="chi-tieu-email", daemon=True)
    _luong.start()
