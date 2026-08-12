"""Đăng bài lên Facebook Page qua Graph API — client gọn, không dùng SDK.

Vì sao KHÔNG dùng facebook-python-business-sdk: SDK là bộ máy quảng cáo
(~991 module adobjects, kéo theo pycountry/aiohttp/six), phần Page chỉ là phụ;
bộ upload video chunked của nó hardcode vào edge `advideos` của ad-account nên
không dùng được cho Page; và `FacebookAdsApi.init` mặc định `crash_log=True`
còn cài sys.excepthook gửi traceback về Meta. Nhu cầu ở đây gói trong 5 endpoint:

    /oauth/access_token   đổi token dài hạn (grant_type=fb_exchange_token)
    /me/accounts          liệt kê Page + page access token (thực tế không hết hạn)
    /{page}/feed          bài chữ, bài link, bài (nhiều) ảnh qua attached_media
    /{page}/photos        nạp ảnh published=false — Facebook TỰ KÉO qua URL
    /{page}/videos        video qua file_url — Facebook tự xử lý (hiện ra reel)

Media đưa cho Facebook bằng URL CÔNG KHAI (config.base_url + /images/…, ký HMAC
qua services.signed_url vì Facebook tự đi tải, không gửi được header) — đúng
kiểu Postiz, khỏi multipart/chunked upload.

Cấu hình `config.json["facebook"]` (các trường *_secret/*_token tự được
services.settings_secrets che trong UI):

    app_id, app_secret   app Meta tự tạo (developers.facebook.com, loại Business;
                         admin/developer của app có sẵn quyền pages_manage_posts,
                         khỏi App Review khi tự dùng)
    user_token           token dán từ Graph API Explorer — CHỈ dùng để đổi
    user_token_long      server tự ghi sau khi đổi dài hạn (~60 ngày)
    pages                [{id, name, access_token, picture}] server tự nạp
    thread_pages         {"kenh:chat[#topic]": [page_id, …]} — thread gắn Page
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import ipaddress
import logging
import re
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from services.config import config

logger = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v23.0"

# Chỉ dành cho test bơm httpx.MockTransport; chạy thật luôn để None.
_transport: httpx.BaseTransport | None = None

# ── Lỗi ──────────────────────────────────────────────────────────────────────

# Dịch lỗi Graph API ra tiếng Việt theo error_subcode — bảng rút từ
# facebook.provider.ts của Postiz (đối chiếu vận hành thật của họ).
_LOI_THEO_SUBCODE: dict[int, str] = {
    1366046: "Ảnh phải nhỏ hơn 4 MB và là JPG/PNG",
    1390008: "Đăng quá nhanh — chờ một lát rồi thử lại",
    1346003: "Nội dung bị Facebook gắn cờ lạm dụng",
    1404102: "Nội dung vi phạm Tiêu chuẩn cộng đồng của Facebook",
    1404078: "Page chưa cấp quyền đăng — cần nối lại tài khoản Facebook",
    1366051: "Những ảnh này đã được đăng trước đó",
    1609008: "Facebook không cho đăng link facebook.com",
    2061006: "URL trong bài không đúng định dạng",
    4854002: "Cần mở app Facebook trên điện thoại xác minh danh tính "
             "trước khi đăng dưới danh nghĩa Page này",
    2069019: "Tệp không hợp lệ với Facebook",
}
# Theo code (khi không có subcode khớp). 190 = token hỏng/thu hồi/hết hạn.
_LOI_THEO_CODE: dict[int, str] = {
    190: "Token Facebook hết hạn hoặc bị thu hồi — vào Cài đặt ▸ Facebook nối lại",
    200: "Thiếu quyền đăng lên Page này (cần pages_manage_posts)",
    100: "Tham số gửi lên Facebook không hợp lệ",
}
# Mã thuộc nhóm rate-limit — đáng thử lại sau khi chờ.
_CODE_THU_LAI = frozenset({4, 17, 32, 613})


class LoiFacebook(Exception):
    """Một lời gọi Graph API thất bại, đã dịch sang thông điệp người đọc được.

    `can_noi_lai=True` nghĩa là token hỏng — sửa bằng cách nối lại tài khoản,
    thử lại vô ích. Caller (capability) dùng cờ này để nhắc đúng việc.
    """

    def __init__(self, thong_diep: str, *, ma: int = 0, ma_phu: int = 0,
                 goc: str = "", can_noi_lai: bool = False):
        super().__init__(thong_diep)
        self.ma = ma
        self.ma_phu = ma_phu
        self.goc = goc
        self.can_noi_lai = can_noi_lai


def _dich_loi(err: dict[str, Any]) -> LoiFacebook:
    ma = int(err.get("code") or 0)
    ma_phu = int(err.get("error_subcode") or 0)
    goc = str(err.get("message") or "")
    thong_diep = (_LOI_THEO_SUBCODE.get(ma_phu)
                  or _LOI_THEO_CODE.get(ma)
                  or str(err.get("error_user_msg") or "")
                  or f"Facebook báo lỗi: {goc[:200]}")
    return LoiFacebook(thong_diep, ma=ma, ma_phu=ma_phu, goc=goc,
                       can_noi_lai=(ma == 190 or ma_phu == 1404078))


# ── Gọi Graph API ────────────────────────────────────────────────────────────

def _appsecret_proof(token: str) -> str:
    """HMAC-SHA256(app_secret, token) — Meta khuyến nghị kèm mọi lời gọi server."""
    secret = str(nap().get("app_secret") or "")
    if not secret:
        return ""
    return _hmac.new(secret.encode("utf-8"), token.encode("utf-8"),
                     hashlib.sha256).hexdigest()


def goi_graph(phuong_thuc: str, duong: str, tham_so: dict | None = None, *,
              token: str, timeout: float = 30.0) -> dict:
    """Một lời gọi Graph API, tự thử lại lỗi thoáng qua, tự dịch lỗi.

    Thử lại (tối đa 2 lần, chờ 3s/6s): HTTP 429, `is_transient` trong body,
    mã rate-limit (4/17/32/613), hoặc 5xx không đọc được lỗi. Các lỗi còn lại
    ném LoiFacebook ngay — token hỏng hay nội dung vi phạm thì thử lại vô ích.
    """
    url = f"{GRAPH}/{duong.lstrip('/')}"
    q: dict[str, Any] = {"access_token": token}
    proof = _appsecret_proof(token)
    if proof:
        q["appsecret_proof"] = proof

    loi_cuoi: LoiFacebook | None = None
    for lan in range(3):
        try:
            with httpx.Client(timeout=timeout, transport=_transport) as cl:
                if phuong_thuc.upper() == "GET":
                    resp = cl.get(url, params={**q, **(tham_so or {})})
                else:
                    resp = cl.post(url, params=q, json=(tham_so or {}))
        except httpx.HTTPError as exc:
            loi_cuoi = LoiFacebook(f"Không gọi được Facebook: {exc}", goc=str(exc))
            time.sleep(3 * (lan + 1))
            continue

        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code < 400 and "error" not in body:
            return body if isinstance(body, dict) else {}

        err = body.get("error") if isinstance(body, dict) else None
        if not isinstance(err, dict):
            err = {"message": resp.text[:300], "code": 0}
        loi = _dich_loi(err)
        thoang_qua = (resp.status_code == 429
                      or bool(err.get("is_transient"))
                      or loi.ma in _CODE_THU_LAI
                      or (resp.status_code >= 500 and loi.ma == 0))
        if not thoang_qua:
            raise loi
        loi_cuoi = loi
        time.sleep(3 * (lan + 1))

    assert loi_cuoi is not None
    raise loi_cuoi


# ── Cấu hình ─────────────────────────────────────────────────────────────────

def nap() -> dict:
    try:
        cfg = (config.get() or {}).get("facebook")
    except Exception:
        cfg = None
    return dict(cfg) if isinstance(cfg, dict) else {}


def _luu(cap_nhat: dict) -> None:
    moi = {**nap(), **cap_nhat}
    config.update({"facebook": moi})


# ── Token & Page ─────────────────────────────────────────────────────────────

def ket_noi(user_token: str = "") -> list[dict]:
    """Đổi user token → dài hạn, nạp danh sách Page, LƯU vào config.

    Gọi khi bấm «Kết nối» trong Cài đặt (user_token vừa dán) hoặc «làm tươi»
    (dùng lại user_token_long đã có). Trả danh sách page đã lưu.

    Page access token lấy qua /me/accounts từ user token DÀI HẠN thực tế không
    hết hạn (chỉ chết khi đổi mật khẩu/thu hồi quyền) — nên đây là việc làm
    một lần, không cần vòng refresh định kỳ.
    """
    cfg = nap()
    app_id = str(cfg.get("app_id") or "").strip()
    app_secret = str(cfg.get("app_secret") or "").strip()
    # «Làm tươi» không dán token mới: user_token ngắn hạn bị XOÁ sau mỗi lần
    # kết nối thành công, nên phải rơi tiếp về user_token_long — token dài hạn
    # đổi lại chính nó qua fb_exchange_token vẫn hợp lệ. Thiếu fallback này,
    # bấm «Kết nối» lần hai luôn báo «Chưa đủ … user_token» (đo thật 11/08).
    token = str(user_token or cfg.get("user_token")
                or cfg.get("user_token_long") or "").strip()
    if not (app_id and app_secret and token):
        raise LoiFacebook("Chưa đủ app_id / app_secret / user_token — "
                          "điền trong Cài đặt ▸ Facebook trước")

    doi = goi_graph("GET", "oauth/access_token", {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": token,
    }, token=token)
    token_dai = str(doi.get("access_token") or "")
    if not token_dai:
        raise LoiFacebook("Facebook không trả token dài hạn",
                          goc=str(doi)[:200])

    pages: list[dict] = []
    duong = "me/accounts"
    tham_so: dict[str, Any] = {
        "fields": "id,name,access_token,picture.type(large)", "limit": 100}
    # /me/accounts phân trang bằng paging.cursors.after — Page nhà thường < 100
    # nhưng vòng while rẻ và tránh đúng kiểu sót-trang-hai từng gặp ở Postiz.
    while True:
        trang = goi_graph("GET", duong, tham_so, token=token_dai)
        for p in trang.get("data") or []:
            if not isinstance(p, dict) or not p.get("id"):
                continue
            pages.append({
                "id": str(p["id"]),
                "name": str(p.get("name") or ""),
                "access_token": str(p.get("access_token") or ""),
                "picture": str(((p.get("picture") or {}).get("data") or {})
                               .get("url") or ""),
            })
        sau = (((trang.get("paging") or {}).get("cursors") or {})
               .get("after") or "")
        if not sau or not (trang.get("paging") or {}).get("next"):
            break
        tham_so["after"] = sau

    _luu({"user_token_long": token_dai, "pages": pages,
          # user_token ngắn hạn đã dùng xong — xoá để không ai tưởng nó còn sống.
          "user_token": ""})
    logger.info("facebook: kết nối xong, %d page", len(pages))
    return pages


def danh_sach_page() -> list[dict]:
    pages = nap().get("pages")
    return [p for p in pages if isinstance(p, dict)] if isinstance(pages, list) else []


def _page_theo_id(page_id: str) -> dict:
    for p in danh_sach_page():
        if str(p.get("id")) == str(page_id):
            return p
    raise LoiFacebook(f"Không tìm thấy Page {page_id} — vào Cài đặt ▸ Facebook "
                      "bấm Kết nối lại để nạp danh sách Page")


def pages_cho_thread(user_id: str) -> list[dict]:
    """Các Page mà thread của phiên này được gắn.

    Khoá gắn dạng `kenh:chat#topic` rồi `kenh:chat` (hẹp thắng rộng, cùng nếp
    chatlog_settings). Thread chưa gắn gì: nếu cả hệ chỉ có MỘT page thì dùng
    luôn (nhà một Page là trường hợp thường), nhiều page thì trả rỗng — bắt gắn
    tường minh để không đăng nhầm Page.
    """
    from services.agent.scope import tach_khoa_phien
    sc = tach_khoa_phien(user_id)
    gan = nap().get("thread_pages")
    gan = gan if isinstance(gan, dict) else {}
    cac_khoa = []
    if sc.chat:
        if sc.topic:
            cac_khoa.append(f"{sc.kenh}:{sc.chat}#{sc.topic}")
        cac_khoa.append(f"{sc.kenh}:{sc.chat}")
    for k in cac_khoa:
        ids = gan.get(k)
        if isinstance(ids, list) and ids:
            return [p for p in danh_sach_page() if str(p.get("id")) in
                    {str(i) for i in ids}]
    tat_ca = danh_sach_page()
    return tat_ca if len(tat_ca) == 1 else []


# ── URL media công khai ──────────────────────────────────────────────────────

def _host_rieng_tu(host: str) -> bool:
    if not host or host.lower() in {"localhost", "host.docker.internal"}:
        return True
    try:
        return ipaddress.ip_address(host).is_private or \
            ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False  # hostname công khai bình thường


def url_cong_khai(url: str) -> str:
    """Chuẩn hoá một URL/đường dẫn media thành URL Facebook TỰ KÉO được.

    - Đường tương đối `/images/…` → ghép config.base_url.
    - Ký HMAC (signed_url.ky_url) khi URL thuộc chính mình: nếu đang bật
      `security.signed_media_required` thì thiếu chữ ký là Facebook nhận 403;
      chưa bật thì query thừa vô hại. TTL 1 giờ đủ cho cả video chờ xử lý.
    - Chặn host LAN/loopback ngay tại đây: đưa URL 172.16.x cho Facebook thì
      nó chỉ thất bại ở xa, khó lần — báo sớm kèm cách sửa dễ hơn nhiều.
    """
    u = str(url or "").strip()
    if not u:
        raise LoiFacebook("Thiếu URL media")
    if u.startswith("/"):
        base = str(getattr(config, "base_url", "") or "").rstrip("/")
        u = f"{base}{u}"
    phan = urlsplit(u)
    if phan.scheme not in ("http", "https") or _host_rieng_tu(phan.hostname or ""):
        raise LoiFacebook(
            "URL media không công khai — Facebook phải tự kéo được file. "
            "Đặt `base_url` (Cài đặt ▸ Hệ thống) về địa chỉ tunnel công khai.")
    la_cua_minh = False
    try:
        base_host = urlsplit(str(getattr(config, "base_url", "") or "")).hostname
        la_cua_minh = bool(base_host) and phan.hostname == base_host
    except Exception:
        pass
    if la_cua_minh and "/images/" in phan.path:
        try:
            from services.signed_url import ky_url
            return ky_url(u, pham_vi="images", song_giay=3600.0)
        except Exception as exc:
            logger.warning("facebook: ký URL media lỗi (dùng URL trần): %s", exc)
    return u


# ── Đăng bài ─────────────────────────────────────────────────────────────────

def _url_bai(body: dict) -> str:
    permalink = str(body.get("permalink_url") or "")
    if permalink.startswith("/"):
        return f"https://www.facebook.com{permalink}"
    if permalink:
        return permalink
    post_id = str(body.get("post_id") or body.get("id") or "")
    return f"https://www.facebook.com/{post_id}" if post_id else ""


def dang_bai_chu(page_id: str, noi_dung: str, link: str = "") -> dict:
    """Bài chữ, kèm link nếu có. Trả {id, url}."""
    page = _page_theo_id(page_id)
    tham_so: dict[str, Any] = {"message": noi_dung, "published": True,
                               "fields": "id,permalink_url"}
    if link:
        tham_so["link"] = link
    body = goi_graph("POST", f"{page['id']}/feed", tham_so,
                     token=page["access_token"])
    return {"id": str(body.get("id") or ""), "url": _url_bai(body)}


def dang_anh(page_id: str, ds_url: list[str], caption: str = "") -> dict:
    """Bài 1..n ảnh: từng ảnh vào /photos published=false, rồi MỘT bài /feed
    gom `attached_media` — đúng khuôn Postiz, 1 ảnh chỉ là trường hợp n=1."""
    page = _page_theo_id(page_id)
    if not ds_url:
        raise LoiFacebook("Chưa có ảnh nào để đăng")
    fbids = []
    for u in ds_url:
        anh = goi_graph("POST", f"{page['id']}/photos",
                        {"url": url_cong_khai(u), "published": False},
                        token=page["access_token"])
        fbids.append({"media_fbid": str(anh.get("id") or "")})
    body = goi_graph("POST", f"{page['id']}/feed", {
        "message": caption, "attached_media": fbids, "published": True,
        "fields": "id,permalink_url",
    }, token=page["access_token"])
    return {"id": str(body.get("id") or ""), "url": _url_bai(body)}


def dang_video(page_id: str, url_video: str, mo_ta: str = "") -> dict:
    """Video qua file_url — Facebook tự tải và xử lý (hiện hiển thị dạng reel).

    POST trả về ngay video_id; việc transcode chạy nền phía Facebook, bài sẽ
    tự hiện khi xong — không cần poll như luồng story."""
    page = _page_theo_id(page_id)
    body = goi_graph("POST", f"{page['id']}/videos", {
        "file_url": url_cong_khai(url_video),
        "description": mo_ta, "published": True,
    }, token=page["access_token"], timeout=90.0)
    vid = str(body.get("id") or "")
    return {"id": vid,
            "url": f"https://www.facebook.com/reel/{vid}" if vid else ""}


def luu_media_cong_khai(du_lieu: bytes, duoi: str = "mp4") -> str:
    """Ghi bytes vào `images_dir/media` và trả URL đầy đủ để Facebook tự kéo.

    Dùng cho VIDEO gửi qua kênh — ảnh đã có `conversation.save_image_bytes`
    (nó sniff định dạng ảnh, đưa video vào sẽ bị gán đuôi .png). Chưa ký HMAC
    ở đây: `url_cong_khai` ký lúc đăng, cùng chỗ với mọi media khác.
    """
    import uuid as _uuid
    out_dir = config.images_dir / "media"
    out_dir.mkdir(parents=True, exist_ok=True)
    ten = f"{_uuid.uuid4().hex[:12]}.{str(duoi or 'mp4').lstrip('.')}"
    (out_dir / ten).write_bytes(du_lieu)
    base = str(getattr(config, "base_url", "") or "").rstrip("/")
    return f"{base}/images/media/{ten}"


def menu_ask(user_id: str) -> str:
    """Nội dung menu /facebook — khối <<<ASK>>> để kênh dựng nút / danh sách số.

    `send` của mỗi mục là câu lệnh tiếng Việt tự nhiên: lượt sau đi qua
    orchestrator nên ChatGPT tham gia hỏi tiếp / soạn nội dung, còn việc đăng
    thật vẫn chốt bằng tool `dang_facebook` + cổng duyệt.
    """
    if not danh_sach_page():
        return ("📘 Chưa kết nối Facebook. Vào Cài đặt ▸ Facebook: điền app_id, "
                "app_secret, dán user token rồi bấm Kết nối.")
    dong = ["📘 Facebook — anh/chị muốn làm gì?"]
    cua = pages_cho_thread(user_id)
    if cua:
        dong.append("Đăng lên: " + ", ".join(p.get("name") or p["id"] for p in cua))
    else:
        dong.append("⚠️ Thread này chưa gắn Page — vào Cài đặt ▸ Facebook, mục "
                    "«Gắn Page theo thread» trước khi đăng.")
    dong += [
        "<<<ASK>>>",
        # Chữ / link / video-URL: `send` là SENTINEL do code bắt (bat_dau_flow),
        # KHÔNG phải câu lệnh cho LLM. Vì sao: ba mục này cần nhập tiếp một tin
        # tự do (nội dung/link/url); để LLM tự dẫn thì một URL lạ (repo GitHub…)
        # kéo model sang việc khác là đứt mạch (đo thật 11/08). Code giữ trạng
        # thái chờ, bắt đúng tin kế tiếp làm input rồi mới qua cổng duyệt.
        # Gom xong nội dung mới hỏi «đăng y nguyên hay để AI viết» — nhánh AI
        # giao lại cho vòng agent, xem `_hoi_cach_dang`.
        f"✍️ Đăng bài chữ | {FLOW_CHU}",
        f"🔗 Đăng link | {FLOW_LINK}",
        # Ảnh vẫn để LLM dẫn: ảnh gửi qua kênh có luồng photo-intent CÓ trạng
        # thái chờ riêng (kèm mục «Đăng Facebook»), không dính lỗi này.
        "🖼️ Đăng ảnh | tôi muốn đăng ảnh lên facebook: nhắc tôi gửi ảnh vào đây "
        "(gửi được nhiều ảnh), gom đủ rồi hỏi tôi caption",
        f"🎬 Đăng video | {FLOW_VIDEO}",
        "✨ Nhờ AI soạn bài | nhờ AI soạn bài đăng facebook: hỏi tôi chủ đề và ý "
        "chính, soạn xong đọc lại cho tôi duyệt rồi mới đăng",
        "🔎 Kiểm tra kết nối | kiểm tra kết nối facebook",
        "<<<END>>>",
    ]
    return "\n".join(dong)


# ── Luồng đăng bài CÓ TRẠNG THÁI CHỜ (chữ / link / video-URL) ────────────────
# Menu /facebook trước đây chỉ đẩy một câu lệnh tiếng Việt cho LLM rồi xoá bản
# chờ ngay; tin kế tiếp (link/nội dung) thành một lượt chat trắng, và một URL lạ
# (vd repo GitHub) kéo LLM sang việc khác là đứt mạch. Nay bắt input ở CODE
# (giống pdf_intent/photo_intent), không qua LLM diễn giải; bước đăng thật vẫn
# đi qua capability `dang_facebook` (risk=CHANGE) + cổng duyệt như thường.

FLOW_CHU = "__fb_flow__:chu"
FLOW_LINK = "__fb_flow__:link"
FLOW_VIDEO = "__fb_flow__:video"
_FLOW_SENTINELS = {FLOW_CHU, FLOW_LINK, FLOW_VIDEO}

_flow_lock = threading.RLock()
_flow: dict[str, dict[str, Any]] = {}   # key -> {stage, ts, link?/video?}
_FLOW_TTL = 15 * 60

# Chỉ THOÁT flow khi người dùng nói RÕ là thôi — không dùng `la_yeu_cau_moi`
# rộng như pdf/ảnh, vì nội dung bài đăng có thể trông y như một câu lệnh và bị
# hiểu nhầm là "yêu cầu mới", đá văng đúng nội dung họ vừa gõ.
_HUY_RE = re.compile(r"^\s*(hu[ỷy]|th[ôo]i|tho[áa]t|d[ừu]ng|cancel)\b", re.I)
_BO_LOI_DAN = {"đăng", "dang", "đăng luôn", "dang luon", "bỏ qua", "bo qua",
               "không", "khong", "ko", "trống", "trong", "-", "."}

# Có nội dung rồi thì hỏi thêm MỘT bước: đăng y nguyên, hay để AI phát triển
# thành bài. Trước đây chỉ có nhánh y nguyên, nên gõ một YÊU CẦU ("viết bài về
# repo này") là nó lên Page đúng câu yêu cầu đó (đo thật 12/08).
# Nhánh AI trả quyền lại cho vòng agent (skill `viet-bai-facebook` +
# `read_webpage` + `dang_facebook`). LLM chỉ vào cuộc khi người dùng BẤM CHỌN,
# nên URL lạ vẫn không tự kéo model đi việc khác — đúng lý do luồng này tồn tại.
CHON_NGUYEN = "__fb_flow__:nguyen"
CHON_AI = "__fb_flow__:ai"

# Bước lời dẫn kèm link: bấm chọn được, khỏi phải gõ. Bốn hướng thật sự khác
# nhau ở chỗ AI có viết không và lấy ý từ đâu — gộp lại thì mất một hướng.
# Bài LINK làm được «AI tự đọc rồi viết» vì `read_webpage` đọc được trang; bài
# chữ và bài video không có gì cho AI đọc nên bước của chúng giữ như cũ.
CHON_AI_LINK = "__fb_flow__:ai_link"   # AI đọc link rồi viết, khỏi gõ gì
CHON_AI_Y = "__fb_flow__:ai_y"         # người dùng cho ý chính, AI viết
CHON_TU_GO = "__fb_flow__:tu_go"       # tự gõ lời dẫn, đăng y nguyên
CHON_TRAN = "__fb_flow__:tran"         # đăng link trần

# Câu nhắc của từng bước — để một chỗ vì bước bắt đầu VÀ bước hỏi lại (khi
# người dùng gửi ảnh giữa chừng) đều cần đúng câu này.
_NHAC = {
    "cho_chu": "✍️ Anh/chị gõ NỘI DUNG bài đăng nhé. (gõ «huỷ» để thôi)",
    "cho_link": "🔗 Anh/chị dán LINK cần đăng nhé. (gõ «huỷ» để thôi)",
    "cho_y_chinh": "💡 Anh/chị cho em ý chính đi (vài chữ cũng được), em viết "
                   "thành bài rồi đọc lại cho duyệt:",
    "cho_loi_dan": "📝 Anh/chị gõ lời dẫn nhé — em đăng y nguyên chữ đó:",
    "cho_video": "🎬 Anh/chị dán LINK video mp4 công khai (hoặc gửi thẳng video "
                 "vào đây cũng được). (gõ «huỷ» để thôi)",
    "cho_video_mo_ta": "📝 Mô tả kèm video (hoặc gõ «đăng» để đăng không mô tả):",
}

# Gửi thẳng ảnh/video vào bot thì kênh (Zalo/Telegram) KHÔNG đưa tệp cho luồng
# này, mà bơm vào orchestrator một câu tiếng Việt kèm URL đã lưu công khai —
# xem telegram_bot.py `inject` / zalo_personal.py `_vinject`. Máy trạng thái ở
# đây chặn trước LLM nên nuốt luôn cả câu đó làm nội dung/link: chọn «Đăng
# link» rồi gửi một video là link của bài thành nguyên câu "thêm video vào bài
# đăng facebook: https://…" (đo thật 12/08). Bắt riêng ở đây.
_TIN_MEDIA_RE = re.compile(
    r"^\s*th[êe]m\s+([ảa]nh|video)\s+v[àa]o\s+b[àa]i\s+[đd][ăa]ng\s+facebook:\s*(\S+)",
    re.I)


def _flow_get(key: str) -> dict | None:
    with _flow_lock:
        p = _flow.get(str(key))
        if not p:
            return None
        if time.time() - float(p.get("ts") or 0) > _FLOW_TTL:
            _flow.pop(str(key), None)
            return None
        return p


def co_flow(key: str) -> bool:
    return _flow_get(key) is not None


def xoa_flow(key: str) -> None:
    with _flow_lock:
        _flow.pop(str(key), None)


def _flow_set(key: str, stage: str, **extra: Any) -> None:
    with _flow_lock:
        cur = _flow.get(str(key)) or {}
        cur.update(extra)
        cur["stage"] = stage
        cur["ts"] = time.time()
        _flow[str(key)] = cur


def _hoi_cach_dang() -> str:
    return "\n".join([
        "Đăng y nguyên chữ vừa gõ, hay để em viết thành bài rồi đọc lại cho "
        "anh/chị duyệt ạ?",
        "<<<ASK>>>",
        f"📄 Đăng y nguyên | {CHON_NGUYEN}",
        f"✨ Để em viết thành bài | {CHON_AI}",
        "<<<END>>>",
    ])


def _hoi_loi_dan_link() -> str:
    return "\n".join([
        "📝 Lời dẫn kèm link — bấm chọn hoặc gõ thẳng lời dẫn cũng được ạ:",
        "<<<ASK>>>",
        f"✨ Em đọc link rồi tự viết bài | {CHON_AI_LINK}",
        f"💡 Anh/chị cho ý chính, em viết | {CHON_AI_Y}",
        f"📝 Anh/chị tự gõ lời dẫn | {CHON_TU_GO}",
        f"📄 Đăng link trần, không lời dẫn | {CHON_TRAN}",
        "<<<END>>>",
    ])


def _nhac_cua(stage: str) -> str:
    """Câu hỏi của bước đang đứng — dùng để hỏi lại mà không mất bản chờ."""
    if stage == "cho_link_loi_dan":
        return _hoi_loi_dan_link()
    return _NHAC.get(stage) or _hoi_cach_dang()


def _args_dang(p: dict) -> dict:
    """Bản chờ đã đủ → args cho capability `dang_facebook` (đăng y nguyên)."""
    loai = str(p.get("loai") or "chu")
    args: dict[str, Any] = {"loai": loai, "message": str(p.get("noi_dung") or "")}
    if loai == "link":
        args["link"] = str(p.get("link") or "")
    elif loai == "video":
        args["media_urls"] = [str(p.get("video") or "")]
    return args


def _yeu_cau_ai(p: dict) -> str:
    """Câu giao việc cho vòng agent khi người dùng chọn «để em viết thành bài».

    Viết ở đây (cạnh luồng) chứ không ở orchestrator: chỗ này biết bài có link
    hay video kèm theo, orchestrator thì không.
    """
    y = str(p.get("noi_dung") or "").strip()
    dong = [f"nhờ AI soạn bài đăng facebook theo yêu cầu sau: «{y}»." if y
            else "nhờ AI soạn bài đăng facebook.",
            "Dùng skill viết bài Facebook giọng người thật (bớt giọng AI)."]
    link = str(p.get("link") or "")
    if link:
        # Bản trước ép "đọc MỘT lượt, đừng tra lại nhiều vòng" — viết thế khi
        # trần bước còn là 4, để model đừng cạn bước trước lúc viết. Trần nay là
        # 7 nên đổi lại được, và PHẢI đổi: đọc một lượt thì bài ra chung chung,
        # toàn câu "giúp AI hiểu code nhanh hơn" mà không nói nó làm gì (đo thật
        # 12/08 19:32, chủ máy nhận xét "ngắn và xúc tích quá").
        dong.append(
            f"Bài đăng kèm link {link} — ĐỌC KỸ trang đó lấy dữ liệu thật, tra "
            "thêm vài lượt cũng được nếu chưa đủ chi tiết, nhưng không bịa. "
            "Bài phải nói RÕ nó là cái gì, làm được gì, dùng ra sao, ai nên "
            "dùng — nêu đích danh thứ có thật trên trang (công nghệ dùng, cách "
            "cài và chạy, nó dựng được những quan hệ nào, nối được công cụ "
            "nào). Đừng dừng ở câu chung chung kiểu «giúp AI hiểu code nhanh "
            "hơn». Cỡ 300–450 từ, đủ để người đọc hiểu mà quyết có thử không.")
    video = str(p.get("video") or "")
    if video:
        dong.append(f"Bài đăng kèm video {video}.")
    # PHẢI nói rõ "gọi tool", và nói rõ gọi tool KHÔNG phải tự đăng. Đo thật
    # 12/08 19:32: câu "soạn xong đọc lại cho tôi duyệt rồi mới đăng" làm model
    # dán bài ra rồi dừng; lượt sau hỏi "đăng bài chưa" nó trả lời không thấy
    # yêu cầu nào đang chờ — bài viết xong mà rơi mất. Cổng duyệt (risk=CHANGE)
    # CHÍNH LÀ bước đọc lại cho duyệt, và nó giữ trạng thái, không phụ thuộc
    # việc model có nhớ qua lượt hay không.
    if link:
        goi = f'dang_facebook với loai="link", link="{link}", message=<bài vừa soạn>'
    elif video:
        goi = ('dang_facebook với loai="video", media_urls=["' + video
               + '"], message=<bài vừa soạn>')
    else:
        goi = 'dang_facebook với loai="chu", message=<bài vừa soạn>'
    dong.append(
        f"Soạn xong thì GỌI NGAY tool {goi}. Gọi tool chính là bước đọc lại cho "
        "tôi duyệt: cổng duyệt hiện bài ra và chặn lại chờ tôi xác nhận, nên "
        "gọi tool KHÔNG phải là tự đăng. Đừng chỉ in bài ra rồi ngồi chờ tôi "
        "trả lời. Trường message chỉ chứa nội dung bài, viết trơn — không bọc "
        "trong khung, thẻ, hay dấu «:::» nào.")
    return " ".join(dong)


def bat_dau_flow(key: str, send_text: str) -> str | None:
    """`send_text` (đã qua resolve_reply) là sentinel của mục cần nhập tiếp?
    Có → đặt trạng thái chờ + trả câu nhắc. Không → None (không phải flow FB)."""
    s = (send_text or "").strip()
    if s not in _FLOW_SENTINELS:
        return None
    if not pages_cho_thread(key):
        if not danh_sach_page():
            return ("📘 Chưa kết nối Facebook. Vào Cài đặt ▸ Facebook: điền "
                    "app_id, app_secret, dán user token rồi bấm Kết nối.")
        return ("Thread này chưa gắn Page nào ạ. Vào Cài đặt ▸ Facebook, mục "
                "«Gắn Page theo thread» để chọn Page cho chỗ này trước.")
    buoc = {FLOW_CHU: "cho_chu", FLOW_LINK: "cho_link"}.get(s, "cho_video")
    _flow_set(key, buoc)
    return _NHAC[buoc]


def tiep_flow(key: str, text: str) -> dict | None:
    """Nhận tin kế tiếp khi đang chờ. Trả một trong:
      {"huy": True}      — người dùng xin thôi (đã xoá bản chờ)
      {"hoi": "<nhắc>"}  — cần thêm input, GIỮ bản chờ
      {"dang": {args}}   — đủ input → args cho capability `dang_facebook`
    None nếu không có bản chờ cho key này.
    """
    p = _flow_get(key)
    if not p:
        return None
    t = (text or "").strip()
    if not t or _HUY_RE.match(t):
        xoa_flow(key)
        return {"huy": True}
    stage = str(p.get("stage") or "")

    m = _TIN_MEDIA_RE.match(t)
    if m:
        kieu = "video" if m.group(1).lower() == "video" else "ảnh"
        if stage == "cho_video" and kieu == "video":
            # Đúng lời hứa in ra ở bước này: «hoặc gửi thẳng video vào đây».
            _flow_set(key, "cho_video_mo_ta", video=m.group(2))
            return {"hoi": _NHAC["cho_video_mo_ta"]}
        # Các bước khác: bài đang soạn không ghép media rời vào được. Nói thẳng
        # và GIỮ bản chờ — nuốt hay xoá đều mất công người dùng đã gõ.
        return {"hoi": f"Bài đang soạn dở không ghép {kieu} vào được ạ. Muốn "
                       f"đăng {kieu} thì gõ «huỷ» rồi chọn mục «🖼️ Đăng ảnh» "
                       f"hoặc «🎬 Đăng video» ở menu /facebook nhé.\n\n"
                       + _nhac_cua(stage)}

    if stage == "cho_chu":
        _flow_set(key, "cho_cach", loai="chu", noi_dung=t)
        return {"hoi": _hoi_cach_dang()}
    if stage == "cho_link":
        _flow_set(key, "cho_link_loi_dan", link=t)
        return {"hoi": _hoi_loi_dan_link()}
    if stage == "cho_link_loi_dan":
        # Bỏ lời dẫn thì không còn gì cho AI phát triển → đăng thẳng, khỏi hỏi.
        if t == CHON_TRAN or t.lower() in _BO_LOI_DAN:
            xoa_flow(key)
            return {"dang": {"loai": "link", "link": str(p.get("link") or ""),
                             "message": ""}}
        if t == CHON_AI_LINK:                  # khỏi gõ gì, AI tự đọc trang
            xoa_flow(key)
            return {"ai": _yeu_cau_ai({**p, "loai": "link", "noi_dung": ""})}
        if t == CHON_AI_Y:
            _flow_set(key, "cho_y_chinh", loai="link")
            return {"hoi": _NHAC["cho_y_chinh"]}
        if t == CHON_TU_GO:
            _flow_set(key, "cho_loi_dan", loai="link")
            return {"hoi": _NHAC["cho_loi_dan"]}
        # Gõ thẳng lời dẫn (không bấm nút): chưa rõ muốn y nguyên hay nhờ viết
        # → hỏi tiếp như các loại bài khác.
        _flow_set(key, "cho_cach", loai="link", noi_dung=t)
        return {"hoi": _hoi_cach_dang()}
    if stage == "cho_y_chinh":                 # đã chốt nhờ AI viết từ trước
        xoa_flow(key)
        return {"ai": _yeu_cau_ai({**p, "noi_dung": t})}
    if stage == "cho_loi_dan":                 # đã chốt đăng y nguyên từ trước
        xoa_flow(key)
        loi = "" if t.lower() in _BO_LOI_DAN else t
        return {"dang": {**_args_dang(p), "message": loi}}
    if stage == "cho_video":
        _flow_set(key, "cho_video_mo_ta", video=t)
        return {"hoi": _NHAC["cho_video_mo_ta"]}
    if stage == "cho_video_mo_ta":
        if t.lower() in _BO_LOI_DAN:
            xoa_flow(key)
            return {"dang": {"loai": "video",
                             "media_urls": [str(p.get("video") or "")],
                             "message": ""}}
        _flow_set(key, "cho_cach", loai="video", noi_dung=t)
        return {"hoi": _hoi_cach_dang()}
    if stage == "cho_cach":
        if t == CHON_AI:
            xoa_flow(key)
            return {"ai": _yeu_cau_ai(p)}
        if t == CHON_NGUYEN:
            xoa_flow(key)
            return {"dang": _args_dang(p)}
        # Gõ gì khác (không bấm nút) → hỏi lại, GIỮ nguyên bài đã soạn. Không
        # đoán ý ở đây: đoán sai là đăng nhầm lên Page, không lùi được.
        return {"hoi": _hoi_cach_dang()}
    xoa_flow(key)
    return {"huy": True}


def kiem_tra() -> str:
    """Báo cáo kết nối, mỗi Page một dòng — dùng cho menu «Kiểm tra kết nối»."""
    pages = danh_sach_page()
    if not pages:
        return ("Chưa kết nối Facebook. Vào Cài đặt ▸ Facebook: điền app_id, "
                "app_secret, dán user token rồi bấm Kết nối.")
    dong = []
    for p in pages:
        try:
            goi_graph("GET", str(p["id"]), {"fields": "id,name"},
                      token=str(p.get("access_token") or ""))
            dong.append(f"✅ {p.get('name') or p['id']} — token còn sống")
        except LoiFacebook as exc:
            dong.append(f"❌ {p.get('name') or p['id']} — {exc}")
    return "\n".join(dong)
