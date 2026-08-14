"""LibreTranslate — dịch máy TỰ CHỦ, không gọi Google/Azure/DeepL.

Máy chủ là image ``libretranslate/libretranslate`` (cổng 5000), nhân dịch là
Argos Translate chạy hẳn trong container. Đặt ``LT_LOAD_ONLY=en,vi`` để chỉ nạp
cặp Anh–Việt: nhẹ RAM, khởi động nhanh, và đủ cho cả hai đường dùng trong dự án
(lệnh ``/dich`` của bot + trục dịch trước/sau LLM ở ``translate_pivot``).

API dùng ở đây đọc thẳng từ mã nguồn LibreTranslate 1.9.6
(``libretranslate/app.py``), không suy diễn từ tài liệu:

    POST /translate   {q, source, target, format, alternatives, api_key}
        q       chuỗi HOẶC danh sách chuỗi — danh sách = dịch lô trong 1 lượt gọi
        source  mã ngôn ngữ hoặc "auto"      (BẮT BUỘC, thiếu là 400)
        target  mã ngôn ngữ                  (BẮT BUỘC, thiếu là 400)
        → {"translatedText": chuỗi|danh sách, "detectedLanguage"?: {...}}
    POST /detect      {q}  → [{"confidence": 0..100, "language": "vi"}]
    GET  /languages        → [{"code", "name", "targets": [...]}]
    GET  /health           → {"status": "ok"}   (miễn giới hạn tần suất)
    POST /translate_file   multipart {file, source, target, api_key}
        → {"translatedFileUrl": ".../download_file/<tên>"}
    GET  /frontend/settings → {"filesTranslation", "supportedFilesFormat", …}

Lỗi trả HTTP 400 / 403 / 429 / 500 kèm body ``{"error": "..."}``.

Hai chi tiết của LibreTranslate ảnh hưởng trực tiếp cách gọi ở đây:

* ``q`` dạng danh sách tính chi phí tần suất bằng ``len(q)`` — dịch lô rẻ về
  số lượt gọi HTTP nhưng không rẻ về hạn mức. Máy tự dựng không đặt hạn mức
  (``LT_REQ_LIMIT`` mặc định -1) nên đây chỉ là chuyện của instance công khai.
* Đoạn không có chữ cái nào (``detect_translatable``) được trả về nguyên văn,
  nên không cần tự lọc số/ký hiệu trước khi gửi.

Cấu hình (config.json, khoá top-level — xem ``services/config.py``):

    translate_url      "http://libretranslate:5000"   (rỗng = tắt hẳn)
    translate_api_key  ""     chỉ cần khi máy chủ bật LT_API_KEYS
    translate_timeout  120    giây (engine thần kinh chạy CPU cần nhiều)

URL này do admin đặt (dịch vụ nội bộ trong stack) nên KHÔNG đi qua
``net_guard`` — cùng nếp với self-call gateway và Home Assistant.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from services.config import config

logger = logging.getLogger(__name__)

VI = "vi"
EN = "en"

# Bộ đệm bản dịch phía client. Lý do có: lịch sử hội thoại được gửi lại MỖI
# LƯỢT, nên không đệm là mỗi lượt chat dịch lại toàn bộ quá khứ. Chặn trên cố
# định, hết chỗ thì xoá nửa cũ (đủ cho một tiến trình gateway, không cần LRU).
_CACHE_MAX = 1024
_cache: dict[tuple[str, str, str], str] = {}
_cache_lock = threading.Lock()

_LANGS_TTL = 600.0
_langs_cache: tuple[float, list[dict[str, Any]]] = (0.0, [])

#: Cầu dao máy dịch GPU: lỗi một lần thì nghỉ tới mốc thời gian này.
_gpu_nghi_toi = 0.0


class LoiDich(Exception):
    """Máy chủ dịch không dùng được (chưa cấu hình, mạng lỗi, HTTP lỗi)."""


# ── Đoạn KHÔNG được dịch ────────────────────────────────────────────────────
# Argos dịch cả code và URL nếu để nguyên: khối ```python``` thành văn xuôi,
# đường dẫn bị chèn dấu cách. Cách vá không phải là "dặn model đừng dịch" mà là
# CẮT các đoạn này ra khỏi phần gửi đi, dịch phần còn lại, rồi ghép lại đúng
# thứ tự — đoạn được bảo vệ không bao giờ chạm máy chủ dịch.
# Thứ tự các nhánh CÓ Ý NGHĨA: regex lấy nhánh khớp sớm nhất, nên khối mã phải
# đứng trước mọi thứ khác — bên trong nó có cả URL, dấu | và markup đầu dòng.
_KHONG_DICH = re.compile(
    r"```.*?```"                        # khối mã ba dấu huyền
    r"|~~~.*?~~~"                       # khối mã ba dấu ngã
    r"|`[^`\n]+`"                       # mã trong dòng
    r"|image://\S+"                     # marker ảnh nội bộ của dự án
    r"|https?://\S+"                    # URL
    r"|[\w.+-]+@[\w-]+\.[\w.]+"         # email
    r"|\{\{[^{}]{0,80}\}\}"             # {{bien}} của template
    r"|<[A-Za-z/!][^>\n]{0,200}>"       # thẻ HTML/XML
    # ── Bộ xương Markdown ───────────────────────────────────────────────────
    # Không chừa những thứ này ra thì Argos ăn luôn cả cấu trúc: "## Tiêu đề"
    # mất dấu thăng, "- mục" mất gạch đầu dòng, bảng mất cột. Bản dịch vẫn đúng
    # nghĩa nhưng hiện ra là một khối chữ liền — với câu trả lời có bảng thì coi
    # như mất sạch thông tin sắp xếp.
    r"|^[ \t]*(?:>[ \t]*)*(?:#{1,6}|[-*+]|\d{1,3}[.)])[ \t]*"  # markup đầu dòng
    r"|^[ \t]*[-*_=]{3,}[ \t]*$"        # đường kẻ ngang / dòng kẻ bảng
    r"|^[ \t]*\|?[-: \t|]+\|?[ \t]*$"   # dòng phân cách của bảng |---|:--:|
    r"|\|"                              # vách ô bảng — mỗi ô thành một đoạn riêng
    r"|^[ \t]*>[ \t]*",                 # trích dẫn không kèm markup nào khác
    re.DOTALL | re.MULTILINE,
)


def is_configured() -> bool:
    """Có URL máy chủ dịch hay không. Rỗng = tính năng dịch tắt hoàn toàn."""
    return bool(config.translate_url)


def _goi(path: str, payload: dict[str, Any] | None = None, *,
         base: str = "") -> Any:
    """Gọi máy chủ dịch. ``base`` rỗng = máy CPU mặc định (``translate_url``);
    truyền URL khác để gọi máy GPU (định tuyến theo lô ở ``translate_batch``)."""
    base = base or config.translate_url
    if not base:
        raise LoiDich("chưa cấu hình translate_url")
    url = base + path
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = dict(payload)
        key = config.translate_api_key
        if key:
            body["api_key"] = key
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=config.translate_timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # LibreTranslate trả {"error": "..."} cho 400/403/429/500 — lấy đúng câu
        # đó ra thay vì "HTTP Error 400: BAD REQUEST" vô nghĩa với người dùng.
        detail = ""
        try:
            detail = str((json.loads(exc.read().decode("utf-8")) or {}).get("error") or "")
        except Exception:
            pass
        raise LoiDich(detail or f"HTTP {exc.code}") from exc
    except Exception as exc:
        raise LoiDich(str(exc)) from exc


def health() -> dict[str, Any]:
    """Trạng thái máy chủ dịch — dùng cho trang cài đặt / kiểm tra nhanh."""
    if not is_configured():
        return {"configured": False, "ok": False, "url": ""}
    try:
        body = _goi("/health")
        ok = str((body or {}).get("status") or "") == "ok"
    except LoiDich as exc:
        return {"configured": True, "ok": False, "url": config.translate_url,
                "error": str(exc)}
    return {"configured": True, "ok": ok, "url": config.translate_url}


def languages(force: bool = False) -> list[dict[str, Any]]:
    """Danh sách ngôn ngữ máy chủ đang nạp. Đệm 10 phút (danh sách chỉ đổi khi
    máy chủ khởi động lại với LT_LOAD_ONLY khác)."""
    global _langs_cache
    ts, cached = _langs_cache
    if cached and not force and (time.time() - ts) < _LANGS_TTL:
        return cached
    body = _goi("/languages")
    langs = [x for x in (body or []) if isinstance(x, dict) and x.get("code")]
    _langs_cache = (time.time(), langs)
    return langs


def lang_codes() -> set[str]:
    try:
        return {str(x.get("code")).lower() for x in languages()}
    except LoiDich:
        return set()


def detect(text: str) -> tuple[str, float]:
    """(mã ngôn ngữ, độ tự tin 0..100). Chuỗi rỗng → ("", 0.0)."""
    t = (text or "").strip()
    if not t:
        return "", 0.0
    body = _goi("/detect", {"q": t})
    if not isinstance(body, list) or not body:
        return "", 0.0
    top = body[0] if isinstance(body[0], dict) else {}
    try:
        conf = float(top.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    return str(top.get("language") or "").lower(), conf


def _cache_get(source: str, target: str, text: str) -> str | None:
    with _cache_lock:
        return _cache.get((source, target, text))


def _cache_put(source: str, target: str, text: str, out: str) -> None:
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            for k in list(_cache)[: _CACHE_MAX // 2]:
                _cache.pop(k, None)
        _cache[(source, target, text)] = out


def translate_batch(texts: list[str], target: str, source: str = "auto") -> list[str]:
    """Dịch nhiều chuỗi trong MỘT lượt gọi (``q`` dạng danh sách).

    Trả về danh sách cùng độ dài, cùng thứ tự. Chuỗi rỗng/chỉ khoảng trắng đi
    thẳng qua không gửi lên máy chủ.

    Lưu ý về ``source="auto"``: LibreTranslate nhận diện ngôn ngữ trên CẢ LÔ và
    chọn MỘT ngôn ngữ nguồn duy nhất (``detect_languages`` lấy trung bình theo
    độ dài). Lô trộn nhiều ngôn ngữ thì nên gọi ``detect`` trước rồi truyền
    ``source`` tường minh.
    """
    tgt = str(target or "").lower()
    src = str(source or "auto").lower()
    out: list[str] = list(texts)
    can_gui: list[int] = []
    for i, t in enumerate(texts):
        if not str(t or "").strip():
            out[i] = t
            continue
        hit = _cache_get(src, tgt, t)
        if hit is not None:
            out[i] = hit
        else:
            can_gui.append(i)
    if not can_gui:
        return out
    payload = {"q": [texts[i] for i in can_gui], "source": src, "target": tgt,
               "format": "text"}
    # Định tuyến theo LÔ: lô đủ lớn đi máy GPU (nếu khai), lỗi thì rơi về máy
    # CPU tại chỗ — thêm GPU không bao giờ làm đứt dịch vụ. Câu lẻ luôn đi CPU
    # (GPU thua CPU với câu đơn vì overhead — số đo cộng đồng LibreTranslate).
    # CẦU DAO: GPU lỗi một lần thì nghỉ 5 phút — máy NVR treo (không tắt hẳn)
    # làm mỗi lô chờ trọn timeout mới rơi về CPU, phim trăm lô là cộng dồn
    # hàng giờ; ngắt hẳn một lúc rồi thử lại rẻ hơn nhiều.
    global _gpu_nghi_toi
    body = None
    gpu = config.translate_url_lo
    if (gpu and len(can_gui) >= config.translate_lo_toi_thieu
            and time.time() >= _gpu_nghi_toi):
        try:
            body = _goi("/translate", payload, base=gpu)
        except LoiDich as exc:
            _gpu_nghi_toi = time.time() + 300
            logger.warning("máy dịch GPU %s lỗi (%s) — rơi về máy CPU, "
                           "nghỉ GPU 5 phút", gpu, str(exc)[:120])
    if body is None:
        body = _goi("/translate", payload)
    got = (body or {}).get("translatedText")
    if not isinstance(got, list) or len(got) != len(can_gui):
        raise LoiDich("máy chủ trả translatedText không khớp số đoạn đã gửi")
    for pos, i in enumerate(can_gui):
        val = str(got[pos] if got[pos] is not None else "")
        out[i] = val
        _cache_put(src, tgt, texts[i], val)
    return out


def translate(text: str, target: str, source: str = "auto") -> str:
    """Dịch một chuỗi, GIỮ NGUYÊN khối mã / URL / email / thẻ / marker ảnh.

    Cách làm: cắt chuỗi thành các đoạn dịch-được và đoạn được-bảo-vệ, gửi TẤT
    CẢ đoạn dịch-được trong một lượt gọi lô, rồi ghép lại theo thứ tự gốc.
    """
    raw = text or ""
    if not raw.strip():
        return raw
    doan = _tach_doan(raw)
    idx = [i for i, (dich_duoc, s) in enumerate(doan) if dich_duoc and s.strip()]
    if not idx:
        return raw
    dich = translate_batch([doan[i][1] for i in idx], target, source)
    ket: list[str] = [s for _, s in doan]
    for pos, i in enumerate(idx):
        ket[i] = dich[pos]
    return "".join(ket)


def _tach_doan(text: str) -> list[tuple[bool, str]]:
    """Cắt văn bản thành [(dịch_được, đoạn), ...] theo ``_KHONG_DICH``."""
    doan: list[tuple[bool, str]] = []
    vi_tri = 0
    for m in _KHONG_DICH.finditer(text):
        if m.start() > vi_tri:
            doan.append((True, text[vi_tri:m.start()]))
        doan.append((False, m.group(0)))
        vi_tri = m.end()
    if vi_tri < len(text):
        doan.append((True, text[vi_tri:]))
    return doan


def to_english(text: str, source: str = "auto") -> str:
    return translate(text, EN, source)


def to_vietnamese(text: str, source: str = "auto") -> str:
    return translate(text, VI, source)


def chon_dich_sang(nguon: str) -> str:
    """Ngôn ngữ đích khi người dùng KHÔNG chỉ định.

    Câu/tệp tiếng Việt → tiếng Anh; mọi thứ khác → tiếng Việt. Đây là việc người
    dùng Việt cần trong gần như mọi trường hợp, và là quy tắc DUY NHẤT — lệnh
    /dich, dịch tệp và dịch ảnh đều gọi hàm này để không lệch nhau.
    """
    return EN if str(nguon or "").lower() == VI else VI


def giai_ma_target(nguon: str, target: str = "") -> str:
    """Mã đích từ lựa chọn người dùng + ngôn ngữ nguồn ĐÃ nhận diện.

    Ba dạng ``target`` (tab Dịch web chọn theo CẶP, chốt 14/08):

    - ``""``        → cặp Việt ↔ Anh mặc định (``chon_dich_sang``).
    - ``"cap:zh"``  → cặp Việt ↔ Trung: nguồn tiếng Việt thì sang ``zh``,
      còn lại về ``vi``. Tương tự ``cap:ja``, ``cap:ko``, ``cap:en``.
    - mã trơ (``"en"``) → như cũ, dành cho bot chat "/dich tiếng anh …".
    """
    t = str(target or "").strip().lower()
    if not t:
        return chon_dich_sang(nguon)
    if t.startswith("cap:"):
        kia = t[4:] or EN
        return kia if str(nguon or "").lower() == VI else VI
    return t


# ── Dịch TỆP ────────────────────────────────────────────────────────────────
#: Đuôi tệp ``/translate_file`` xử lý được, đọc từ argos-translate-files: Txt,
#: Odt, Odp, Docx, Pptx, Epub, Html. Đây là bản DỰ PHÒNG khi không đọc được
#: ``/frontend/settings``; danh sách thật lấy từ máy chủ (nó còn phụ thuộc cờ
#: LT_DISABLE_FILES_TRANSLATION).
#:
#: Chú ý cái KHÔNG có: **pdf** và **xlsx**. Argos không dựng lại được hai định
#: dạng này, nên hai loại đó đi đường khác — trích chữ rồi dịch chữ.
DINH_DANG_TEP_ARGOS: tuple[str, ...] = (
    ".txt", ".odt", ".odp", ".docx", ".pptx", ".epub", ".html", ".htm",
)

_setting_cache: tuple[float, dict[str, Any]] = (0.0, {})


def frontend_settings(force: bool = False) -> dict[str, Any]:
    """``/frontend/settings`` — đệm 10 phút. Rỗng nếu máy chủ không trả được."""
    global _setting_cache
    ts, cached = _setting_cache
    if cached and not force and (time.time() - ts) < _LANGS_TTL:
        return cached
    try:
        body = _goi("/frontend/settings")
    except LoiDich as exc:
        logger.debug("không đọc được /frontend/settings: %s", exc)
        return {}
    body = body if isinstance(body, dict) else {}
    _setting_cache = (time.time(), body)
    return body


def dinh_dang_tep_ho_tro() -> tuple[str, ...]:
    """Đuôi tệp máy chủ dịch được TRỰC TIẾP (giữ nguyên định dạng gốc)."""
    st = frontend_settings()
    if st and not st.get("filesTranslation", True):
        return ()          # admin đã tắt dịch tệp trên máy chủ
    ds = st.get("supportedFilesFormat")
    if isinstance(ds, list) and ds:
        return tuple(str(x).lower() for x in ds if str(x or "").startswith("."))
    return DINH_DANG_TEP_ARGOS


def _multipart(path: str, name: str, fields: dict[str, str]) -> tuple[bytes, str]:
    """Dựng thân multipart/form-data cho ``/translate_file``. Trả (thân, ranh giới)."""
    ranh = "c2a" + str(int(time.time() * 1000))
    khoi: list[bytes] = []
    for k, v in fields.items():
        khoi.append(
            f"--{ranh}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"
            .encode("utf-8"))
    with open(path, "rb") as f:
        du_lieu = f.read()
    khoi.append(
        f"--{ranh}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
        .encode("utf-8"))
    khoi.append(du_lieu)
    khoi.append(f"\r\n--{ranh}--\r\n".encode("utf-8"))
    return b"".join(khoi), ranh


def _duong_tai(url: str) -> str:
    """URL máy chủ trả về → chỉ PHẦN ĐƯỜNG DẪN (kèm query nếu có).

    Vì sao không dùng thẳng URL đó: nó do Flask dựng bằng ``url_for(_external=
    True)``, tức lấy từ header Host — sau một reverse proxy nó có thể là
    ``http://localhost:5000/...``, địa chỉ mà gateway không gọi tới được. Đường
    dẫn thì luôn đúng, ghép lại vào ``translate_url`` là ra địa chỉ gọi được.
    """
    from urllib.parse import urlparse
    p = urlparse(str(url or ""))
    return p.path + (("?" + p.query) if p.query else "")


def _tai_ve(url: str) -> bytes:
    """Tải tệp đã dịch từ máy chủ dịch."""
    duong = _duong_tai(url)
    if not duong:
        raise LoiDich("máy chủ không trả đường tải tệp đã dịch")
    req = urllib.request.Request(config.translate_url + duong,
                                headers={"Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=config.translate_timeout) as resp:
            return resp.read()
    except Exception as exc:
        raise LoiDich(f"tải tệp đã dịch lỗi: {exc}") from exc


def translate_file(path: str, name: str, target: str,
                   source: str = "auto") -> tuple[bytes, str]:
    """Dịch tệp GIỮ NGUYÊN định dạng qua ``/translate_file``. Trả (bytes, tên tệp).

    Chỉ dùng cho đuôi nằm trong ``dinh_dang_tep_ho_tro()``. LibreTranslate xoá
    tệp đã dịch sau 30 phút (``remove_translated_files``) nên phải tải về ngay,
    không lưu URL lại dùng sau.
    """
    body, ranh = _multipart(path, name, {
        "source": str(source or "auto").lower(),
        "target": str(target or "").lower(),
        **({"api_key": config.translate_api_key} if config.translate_api_key else {}),
    })
    base = config.translate_url
    if not base:
        raise LoiDich("chưa cấu hình translate_url")
    req = urllib.request.Request(
        base + "/translate_file", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={ranh}",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=max(60, config.translate_timeout)) as resp:
            ket = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = str((json.loads(exc.read().decode("utf-8")) or {}).get("error") or "")
        except Exception:
            pass
        raise LoiDich(detail or f"HTTP {exc.code}") from exc
    except Exception as exc:
        raise LoiDich(str(exc)) from exc
    du_lieu = _tai_ve(str((ket or {}).get("translatedFileUrl") or ""))
    goc = str(name or "tep")
    dot = goc.rfind(".")
    ten_moi = (f"{goc[:dot]}.{target}{goc[dot:]}" if dot > 0 else f"{goc}.{target}")
    return du_lieu, ten_moi


def chu_thanh_docx(text: str, stem: str = "") -> tuple[bytes, str]:
    """Bản dịch dài → tệp .docx. Trả (bytes, tên tệp).

    ``stem`` là tên tệp KHÔNG có đuôi (vd ``"bao-cao.vi"``) — hàm này chỉ gắn
    thêm ``.docx``, không tự bóc đuôi, vì bóc thì mất luôn hậu tố ngôn ngữ.

    Dùng đúng bộ dựng docx sẵn có của dự án (``pdf_to_word._markdown_to_docx``:
    heading, bảng, danh sách, **đậm**) chứ không viết bộ thứ hai — bản dịch một
    tài liệu vẫn là Markdown, và hai bộ dựng song song là lý do sửa một chỗ mà
    chỗ kia vẫn ra bản cũ.
    """
    import os
    import tempfile

    from services.pdf_to_word import _markdown_to_docx
    goc = str(stem or "ban-dich").strip()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".docx")
    tmp.close()
    try:
        _markdown_to_docx(text, tmp.name)
        with open(tmp.name, "rb") as f:
            return f.read(), f"{goc or 'ban-dich'}.docx"
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def _dong_goi_chu(text: str, stem: str, nguon: str, dich: str,
                  chi_chu: bool) -> dict[str, Any]:
    """Bản dịch dạng chữ → gửi thẳng, hoặc đóng thành .docx nếu quá dài.

    Ngưỡng: ``config.translate_docx_threshold`` (mặc định 3000 ký tự). Trên
    ngưỡng mà kênh gửi được tệp thì trả ``kieu="tep"`` — Telegram chặn tin ở
    4096 ký tự, nên bản dịch một tài liệu vài trang nếu gửi bằng tin nhắn sẽ bị
    cắt thành một chuỗi tin vụn, đọc không nổi.
    """
    chung = {"nguon": nguon or "auto", "dich": dich}
    nguong = config.translate_docx_threshold
    if chi_chu or not nguong or len(text) <= nguong:
        return {"ok": True, "kieu": "chu", "text": text, **chung}
    try:
        data, ten_docx = chu_thanh_docx(text, stem or "ban-dich")
    except Exception as exc:   # thiếu python-docx / dựng docx lỗi
        logger.warning("đóng bản dịch thành .docx lỗi, gửi bằng chữ: %s", exc)
        return {"ok": True, "kieu": "chu", "text": text, **chung}
    return {"ok": True, "kieu": "tep", "data": data, "ten": ten_docx,
            "text": text, **chung}


def _trich_chu_tep(path: str) -> str:
    """PDF / xlsx / doc cũ → chữ. Dùng đúng đường đọc tài liệu sẵn có của dự án
    (``pdf_intent.extract_markdown``: pdf-inspector → OCR vision → markitdown),
    không dựng thêm bộ đọc thứ hai."""
    from services.pdf_intent import extract_markdown
    return (extract_markdown(path) or "").strip()


def dich_tep(path: str, name: str, target: str = "", *,
             chi_chu: bool = False) -> dict[str, Any]:
    """Dịch một tệp đã tải về đĩa. KHÔNG raise — lỗi trả trong khoá ``error``.

    ``chi_chu=True`` buộc trả về CHỮ dù định dạng có dựng lại được. Dành cho kênh
    không gửi được tệp (Zalo Bot) — ở đó trả ``kieu="tep"`` là một bản dịch không
    có đường nào tới tay người dùng.

    Trả::

        {"ok": True, "kieu": "tep", "data": b"...", "ten": "bao-cao.vi.docx",
         "nguon": "en", "dich": "vi"}
        {"ok": True, "kieu": "chu", "text": "…", "nguon": "en", "dich": "vi"}
        {"ok": False, "error": "…"}

    ``kieu="tep"`` = trả lại tài liệu cùng định dạng (docx/pptx/odt/txt/epub/
    html) do chính LibreTranslate dựng lại. ``kieu="chu"`` = định dạng Argos
    không dựng lại được (PDF, Excel, doc/ppt cũ) nên trích chữ rồi dịch chữ —
    và bản chữ dài hơn ``translate_docx_threshold`` cũng được đóng thành .docx
    (xem ``_dong_goi_chu``).
    """
    if not is_configured():
        return {"ok": False, "error": "chưa cấu hình máy chủ dịch (translate_url)"}
    ten = str(name or "").strip() or "tep"
    duoi = ten[ten.rfind("."):].lower() if "." in ten else ""
    try:
        if duoi in dinh_dang_tep_ho_tro() and not chi_chu:
            # Cần biết ngôn ngữ tệp TRƯỚC khi gọi để chọn đích. Máy chủ cũng tự
            # nhận diện được với source="auto", nhưng nó không chọn đích thay ta.
            nguon, _ = detect(_trich_chu_tep(path)[:3000] or ten)
            dich = giai_ma_target(nguon, target)
            if nguon and nguon == dich:
                return {"ok": False, "error": f"tệp đã là tiếng `{dich}`"}
            data, ten_moi = translate_file(path, ten, dich, nguon or "auto")
            return {"ok": True, "kieu": "tep", "data": data, "ten": ten_moi,
                    "nguon": nguon or "auto", "dich": dich}
        chu = _trich_chu_tep(path)
        if not chu:
            return {"ok": False, "error": "không đọc được nội dung tệp"}
        nguon, _ = detect(chu[:5000])
        dich = giai_ma_target(nguon, target)
        if nguon and nguon == dich:
            return {"ok": False, "error": f"tệp đã là tiếng `{dich}`"}
        ban_dich = translate(chu, dich, nguon or "auto")
        goc = ten[:-len(duoi)] if duoi else ten
        return _dong_goi_chu(ban_dich, f"{goc}.{dich}", nguon, dich, chi_chu)
    except LoiDich as exc:
        logger.warning("dịch tệp %s lỗi: %s", ten, exc)
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # đọc tài liệu lỗi (doc_guard, file hỏng…)
        logger.warning("đọc tệp %s để dịch lỗi: %s", ten, exc)
        return {"ok": False, "error": str(exc)[:200]}


def bao_cao_dich(ket: dict[str, Any], name: str = "") -> str:
    """Kết quả ``dich_tep`` / ``dich_anh`` → câu trả lời cho người dùng.

    Dùng chung cho cả ba kênh (Telegram, Zalo Bot, Zalo cá nhân) để lời báo
    không lệch nhau. Với ``kieu="tep"`` thì đây là CAPTION của tài liệu gửi kèm,
    kênh vẫn phải tự gửi bytes bằng hàm gửi tệp của mình.
    """
    if not ket.get("ok"):
        return f"🌐 Không dịch được{' ' + name if name else ''}: {ket.get('error') or 'lỗi không rõ'}"
    huong = f"{ket.get('nguon') or 'auto'} → {ket.get('dich') or ''}"
    if ket.get("kieu") == "tep":
        return f"🌐 Bản dịch ({huong})"
    dau = f"🌐 Dịch {name} ({huong})" if name else f"🌐 Bản dịch ({huong})"
    return f"{dau}\n\n{ket.get('text') or ''}".strip()


#: Lời nhắc OCR gửi cho model vision khi dịch ẢNH. Yêu cầu chép nguyên văn,
#: không diễn giải — có diễn giải là bản dịch sau đó dịch lời model, không phải
#: dịch chữ trong ảnh.
NHAC_OCR = (
    "Đọc và chép lại TOÀN BỘ chữ xuất hiện trong ảnh, giữ đúng thứ tự và cách "
    "xuống dòng. Chỉ chép chữ, không mô tả ảnh, không giải thích, không thêm "
    "lời nào của bạn. Không có chữ nào thì trả lời đúng một từ: KHONGCOCHU"
)


def dich_anh(image_bytes: bytes, target: str = "", *, channel: str = "",
             chi_chu: bool = False) -> dict[str, Any]:
    """Dịch chữ TRONG ảnh: OCR bằng model vision sẵn có → dịch bằng máy chủ dịch.

    LibreTranslate không đọc ảnh (Argos chỉ dựng lại được tài liệu văn bản), nên
    bước đọc chữ phải nhờ đường vision của dự án — cùng hàm mà «Phân tích ảnh»
    đang dùng. Trả cùng khuôn với ``dich_tep``: ``kieu="chu"``, hoặc
    ``kieu="tep"`` (.docx) nếu bản dịch dài quá ngưỡng và kênh gửi được tệp.
    ``goc`` là chữ OCR đọc được, để người dùng đối chiếu.
    """
    if not is_configured():
        return {"ok": False, "error": "chưa cấu hình máy chủ dịch (translate_url)"}
    try:
        from services.photo_intent import analyze_photo
        # neo_tieng_viet=False: câu neo "trả lời hoàn toàn bằng tiếng Việt" của
        # analyze_photo sẽ khiến model TỰ DỊCH ảnh sang tiếng Việt, và máy dịch
        # nhận vào một bản đã Việt hoá — mất sạch việc cần làm.
        chu = (analyze_photo(image_bytes, NHAC_OCR, channel=channel,
                             neo_tieng_viet=False, max_tokens=2000) or "").strip()
    except Exception as exc:
        logger.warning("OCR ảnh để dịch lỗi: %s", exc)
        return {"ok": False, "error": f"không đọc được chữ trong ảnh: {str(exc)[:150]}"}
    if not chu or "KHONGCOCHU" in chu.upper():
        return {"ok": False, "error": "không thấy chữ nào trong ảnh"}
    try:
        nguon, _ = detect(chu[:5000])
        dich = giai_ma_target(nguon, target)
        ban_dich = chu if (nguon and nguon == dich) else translate(
            chu, dich, nguon or "auto")
    except LoiDich as exc:
        logger.warning("dịch chữ trong ảnh lỗi: %s", exc)
        return {"ok": False, "error": str(exc)}
    ket = _dong_goi_chu(ban_dich, "chu-trong-anh." + dich, nguon, dich, chi_chu)
    ket["goc"] = chu
    return ket


# ── Lệnh /dich của bot ──────────────────────────────────────────────────────
# Tên ngôn ngữ tiếng Việt → mã ISO. Chỉ nhận sau chữ "tiếng" ("/dich tiếng anh
# …"), KHÔNG nhận tên trơ. Lý do: gần như mọi tên ngôn ngữ trong tiếng Việt đều
# là từ thông dụng — "anh" (đại từ), "nga", "đức", "thơ", "hoa", "nhất". Nhận
# tên trơ thì "/dich anh ơi giúp em với" biến thành "dịch sang tiếng Anh câu
# 'ơi giúp em với'". Dạng "tiếng X" không bao giờ nhập nhằng.
#
# Mã ở đây là mã MODEL của Argos ("zh"); `_chuan_ma` đổi sang mã máy chủ khai ra
# ("zh-Hans") trước khi so với /languages.
_TEN_NGON_NGU: dict[str, str] = {
    "viet": VI, "vietnam": VI, "vn": VI,
    "anh": EN, "english": EN,
    "trung": "zh", "trungquoc": "zh", "hoa": "zh",
    "nhat": "ja", "nhatban": "ja",
    "han": "ko", "hanquoc": "ko", "trieutien": "ko",
    "phap": "fr",
    "duc": "de",
    "nga": "ru",
    "tbn": "es", "spanish": "es",
    "y": "it", "italia": "it",
    "bodaonha": "pt", "portugal": "pt",
    "thai": "th", "thailan": "th",
    "indo": "id", "indonesia": "id",
    "arap": "ar", "arab": "ar",
    "an": "hi", "hindi": "hi",
    "balan": "pl",
    "halan": "nl", "hoalan": "nl",
    "tho": "tr", "thonhiky": "tr",
    "ukraina": "uk", "ukraine": "uk",
    "sec": "cs", "hungary": "hu", "hylap": "el",
}

_LENH_DICH = {"/dich", "/dịch", "/translate", "/tr"}

#: Mã ngôn ngữ ISO: "en", "vi", "pt-BR", "zh-Hans" (đã hạ chữ thường).
_MA_ISO = re.compile(r"^[a-z]{2,3}(-[a-z]{2,4})?$")

#: Bí danh mã ngôn ngữ của LibreTranslate — bảng `aliases` trong
#: `libretranslate/language.py`. `/languages` trả mã ĐÃ ĐỔI TÊN: model ``zh`` ra
#: ``zh-Hans``, ``zt`` ra ``zh-Hant``, ``pb`` ra ``pt-BR``.
#:
#: Thiếu bảng này là một lỗi im lặng thật: `_TEN_NGON_NGU` cho "trung" → ``zh``,
#: so với `/languages` (chỉ có ``zh-Hans``) thì TRƯỢT, và "/dich tiếng trung xin
#: chào" biến thành "dịch cả câu 'tiếng trung xin chào'".
_BI_DANH_MA: dict[str, str] = {"zh": "zh-hans", "zt": "zh-hant", "pb": "pt-br"}


def _bo_dau(s: str) -> str:
    from services.agent.vi_text import fold
    return fold(s)


def _bo_tag_dau(text: str) -> str:
    """Bỏ ĐÚNG MỘT tag bot ở đầu tin ("@BenBap /dich xin chào").

    Cố ý không dùng ``photo_intent.bo_tag``: hàm đó xoá MỌI cụm ``@…`` trong
    câu, tức là "/dich gửi mail cho john@example.com" bị mất luôn tên miền —
    với lệnh dịch thì đó là làm hỏng chính thứ cần dịch.
    """
    s = (text or "").strip()
    if not s.startswith("@"):
        return s
    phan = s.split(maxsplit=1)
    return phan[1].strip() if len(phan) > 1 else ""


def la_lenh_dich(text: str) -> bool:
    """Tin nhắn này có phải lệnh /dich.

    Nhận "/dich", "/dịch", "/translate", "/tr", cả dạng "/dich@TenBot" (nhóm
    Telegram) và "@TenBot /dich ..." (nhóm Zalo luôn kèm tag ở đầu).
    """
    dau = _bo_tag_dau(text).split(maxsplit=1)
    if not dau:
        return False
    return dau[0].split("@", 1)[0].lower() in _LENH_DICH


def _phan_giai_dich(noi_dung: str) -> tuple[str, str]:
    """Bóc chỉ định ngôn ngữ đích ở đầu nội dung → (mã ISO, phần còn lại).

    Hai dạng được nhận, ngoài ra coi như không chỉ định:

        "en xin chào"          → ("en", "xin chào")     mã ISO
        "tiếng anh xin chào"   → ("en", "xin chào")     tên tiếng Việt sau "tiếng"
        "tiếng trung 你好"      → ("zh-hans", "你好")     qua `_chuan_ma`

    Mã trả về là mã ĐÚNG NHƯ máy chủ khai trong ``/languages`` (xem
    ``_chuan_ma``), và phải nằm trong danh sách nó đang nạp — gõ "/dich ja …"
    khi máy chủ chỉ có en,vi thì "ja" là NỘI DUNG, không phải ngôn ngữ đích.
    """
    tach = (noi_dung or "").strip().split()
    if not tach:
        return "", ""
    co = lang_codes()
    dau = _bo_dau(tach[0]).strip(":,.")
    if dau == "tieng" and len(tach) >= 2:
        ma = _chuan_ma(_TEN_NGON_NGU.get(_bo_dau(tach[1]).strip(":,."), ""), co)
        if ma:
            return ma, " ".join(tach[2:]).strip()
        return "", noi_dung.strip()
    if _MA_ISO.match(dau):
        ma = _chuan_ma(dau, co)
        if ma:
            return ma, " ".join(tach[1:]).strip()
    return "", noi_dung.strip()


def _chuan_ma(ma: str, co: set[str]) -> str:
    """Mã người dùng gõ → mã ĐÚNG NHƯ máy chủ khai trong ``/languages``.

    Trả "" nếu máy chủ không nạp ngôn ngữ đó. ``co`` rỗng (đọc ``/languages``
    lỗi, thường là đang tải model) thì tin mã người dùng gõ — ``/translate`` sẽ
    tự báo nếu sai; chặn ở client lúc đó là chặn oan.
    """
    m = (ma or "").lower()
    if not m or not co:
        return m
    if m in co:
        return m
    bd = _BI_DANH_MA.get(m, "")
    if bd and bd in co:
        return bd
    # Bí danh chưa phủ hết: đúng MỘT mã của máy chủ mở rộng từ mã này ("zh" →
    # "zh-Hans") thì lấy nó. Nhiều hơn một thì không đoán — đoán sai biến thể
    # chữ Hán là trả về thứ người dùng không đọc được.
    nhanh = sorted(c for c in co if c.startswith(m + "-"))
    return nhanh[0] if len(nhanh) == 1 else ""


def _tro_giup() -> str:
    ma = sorted(lang_codes())
    dong = "Ngôn ngữ máy chủ đang nạp: " + (", ".join(ma) if ma else "(chưa đọc được)")
    return ("🌐 **Dịch văn bản** (LibreTranslate tự dựng, không qua bên thứ ba)\n"
            "`/dich <nội dung>` — tự nhận diện: câu tiếng Việt → tiếng Anh, "
            "còn lại → tiếng Việt\n"
            "`/dich en <nội dung>` — chỉ định bằng mã ngôn ngữ\n"
            "`/dich tiếng anh <nội dung>` — hoặc bằng tên tiếng Việt\n" + dong)


def lenh_dich(text: str) -> str:
    """Xử lý lệnh /dich → chuỗi để bot gửi thẳng cho người dùng.

    Chỉ gọi sau khi ``la_lenh_dich`` trả True. Hàm này KHÔNG raise: mọi lỗi máy
    chủ dịch đều thành câu tiếng Việt nói rõ lỗi — người gõ đích danh lệnh này
    xứng đáng biết vì sao không có gì xảy ra, thay vì bot im lặng.
    """
    if not is_configured():
        return ("🌐 Chưa cấu hình máy chủ dịch. Đặt `translate_url` "
                "(ví dụ `http://libretranslate:5000`) trong Cài đặt.")
    phan = _bo_tag_dau(text).split(maxsplit=1)
    noi_dung = phan[1].strip() if len(phan) > 1 else ""
    if not noi_dung:
        return _tro_giup()

    dich_sang, noi_dung = _phan_giai_dich(noi_dung)
    if not noi_dung:
        return _tro_giup()

    try:
        nguon, tin = detect(noi_dung)
        dich_sang = dich_sang or chon_dich_sang(nguon)
        if nguon and nguon == dich_sang:
            return f"🌐 Văn bản đã là `{dich_sang}` rồi ạ."
        ket = translate(noi_dung, dich_sang, nguon or "auto")
    except LoiDich as exc:
        logger.warning("lenh /dich lỗi: %s", exc)
        return f"🌐 Máy chủ dịch lỗi: {exc}"
    nhan = f"{nguon or 'auto'} → {dich_sang}"
    if nguon and tin:
        nhan += f" ({tin:.0f}%)"
    return f"🌐 {nhan}\n{ket}"
