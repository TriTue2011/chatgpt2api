"""Account auto-recovery + Telegram notification.

When an account fails during use (token expired / 401 on the web flow), try to
recover it automatically by REUSING its refresh_token to mint a fresh OAuth
token, and notify the admin Telegram chat of: the error, the action taken, and
the result. Accounts without a refresh_token can't be auto-refreshed — we
notify that a manual re-login (noVNC / onboard) is required.

Debounced per account so a burst of failures doesn't spam Telegram.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from utils.log import logger

_last_attempt: dict[str, float] = {}
_lock = threading.Lock()
_COOLDOWN_S = 600.0  # one recovery attempt / notification per account per 10 min


def _notify(text: str, detail: dict[str, Any] | None = None) -> None:
    """Push recovery status to admin bots + account log file.

    Bot fan-out dùng category="account_log" → mỗi kênh (Telegram / Zalo bot /
    Zalo cá nhân) bật/tắt riêng bằng account_log_notify_* (fallback key cũ).
    Also append LOG_TYPE_ACCOUNT so UI Logs shows them; detail mang
    provider/email/profile/step để log đầy đủ tài khoản nào, provider nào,
    đến bước khôi phục nào.
    """
    try:
        from services.notifier import notify_admin
        notify_admin(text, category="account_log")
    except Exception as exc:
        logger.warning({"event": "recovery_notify_failed", "error": str(exc)[:120]})
    try:
        from services.log_service import LOG_TYPE_ACCOUNT, log_service
        # Skip bot fan-out from log_service to avoid double Telegram messages:
        # notify_admin above already delivered to the enabled channels.
        summary = (text or "").replace("\n", " · ")[:240]
        det: dict[str, Any] = {"source": "account_recovery", "notify_bots": False}
        if detail:
            det.update({k: v for k, v in detail.items() if v not in (None, "")})
        log_service.add(LOG_TYPE_ACCOUNT, summary, det)
    except Exception:
        pass


def _acct_label(account: dict[str, Any]) -> str:
    return str(account.get("email") or (account.get("access_token") or "")[:12] or "?")


_GRELOGIN_COOLDOWN_S = 1800.0  # browser login đắt → 1 lần / account / 30 phút

# Đăng nhập Google phải chạy LẦN LƯỢT trên toàn hệ thống. Nhiều tài khoản chết
# gần nhau sẽ spawn nhiều thread recover cùng lúc; nếu để chúng cùng bấm
# auto-login-saved thì Google thấy một chùm login tự động từ một IP máy chủ →
# bung captcha hàng loạt. Bấm tay "Chỉ đăng nhập" không dính captcha chỉ vì nó
# tự nhiên là từng-lần-một. Khoá này ép máy làm y hệt: mỗi thời điểm CHỈ một
# phiên Google, cách nhau tối thiểu _GLOGIN_GAP_S.
_glogin_serial = threading.Lock()
_glogin_last_done = 0.0            # mốc kết thúc phiên Google gần nhất (giữ dưới _glogin_serial)
_GLOGIN_GAP_S = 25.0              # cách nhau tối thiểu giữa 2 phiên đăng nhập Google
# Trần thời gian 1 lượt khôi phục. Phải CHỨA ĐỦ cả thang, nếu không tầng cuối bị
# cắt giữa đường (đo thật 30/07: trần 300s < riêng một lượt đăng nhập Google, nên
# tầng 2-sau-đăng-nhập không bao giờ chạy):
#   T2 mở đăng nhập Codex trong workspace    ≤ 180s
#   T3 đăng nhập lại tài khoản Google        ≤ 700s  (xem _freshen_google)
#   T2 lặp lại sau khi đăng nhập xong        ≤ 180s
#   T3 hàng loạt (acc trong codex_auto_list) ≤ 420s
_RECOVER_BUDGET_S = 1200.0
_CAPTCHA_PROFILES = "/app/data/captcha/profiles"


def _solver_cfg() -> tuple[str, str]:
    """(url, api_key) của captcha-solver — lấy từ config như flow/gemini_web."""
    from services.config import config
    prov = config.data.get("providers") or {}
    for n in ("flow", "gemini_web_api", "gemini_web"):
        c = prov.get(n) or {}
        raw = str(c.get("captcha_solver_url") or "").strip()
        if raw:
            from services.captcha import captcha_base
            return captcha_base(raw), str(c.get("captcha_solver_api_key") or "")
    return "http://127.0.0.1:8010", ""


def _profile_for(email: str) -> str:
    """Tên profile browser của tài khoản này trong captcha-solver.

    Trên đĩa đang tồn tại VÀI quy ước đặt tên khác nhau, do các đường tạo profile
    khác nhau:
      · web UI            → hạ chữ + đổi ký tự lạ thành '-'  (google-ben-bap)
      · api/accounts.py, jwt_refresh_scheduler → đổi ký tự lạ, GIỮ hoa/thường
      · hàm này (bản cũ)  → nguyên localpart, kể cả dấu chấm (google-Ben.Bap)
    Đoán một kiểu rồi trả về luôn thì với email có dấu chấm/chữ hoa sẽ trỏ vào
    thư mục KHÔNG tồn tại → `has_profile` False → tầng 2 bị bỏ oan, và tầng 3 lại
    đăng nhập vào một profile mới toanh thay vì profile đang có session.
    Vì vậy: sinh các ứng viên rồi ưu tiên cái CÓ THẬT trên đĩa.
    """
    local = (email or "").split("@", 1)[0] or "default"
    an_toan = "".join(c if c.isalnum() or c == "-" else "-" for c in local)
    ung_vien = [f"google-{local}", f"google-{an_toan}", f"google-{an_toan.lower()}"]
    try:
        import os
        co_that = {n.lower(): n for n in os.listdir(_CAPTCHA_PROFILES)}
    except OSError:
        co_that = {}
    for ten in ung_vien:
        thuc = co_that.get(ten.lower())
        if thuc:
            return thuc
    # Chưa có profile nào → dùng cùng quy ước với api/accounts.py và
    # jwt_refresh_scheduler để cả hệ thống nói về cùng một thư mục.
    return ung_vien[1]


def _dong_hang_loat(email: str) -> list[str] | None:
    """Dòng của email trong `codex_auto_list` (nguồn của nút "Đăng nhập hàng
    loạt"), None nếu không có dòng nào.

    ĐÂY là dấu hiệu phân loại tài khoản, theo đúng cách hệ thống được dùng
    (người vận hành chốt 30/07): **có dòng trong danh sách → tài khoản đăng nhập
    hàng loạt; KHÔNG có dòng → tài khoản Google.**

    Bản cũ phân loại bằng đuôi email (`@gmail.com` = Google) nên sai cả hai chiều:
      · acc hàng loạt dùng Gmail bị đẩy sang nhánh Google;
      · acc Google (Workspace, đuôi công ty) bị đẩy sang nhánh hàng loạt rồi chết
        ngay vì không có dòng nào trong `codex_auto_list` để mà đăng nhập.
    """
    from services.config import config
    cfg = config.data if isinstance(config.data, dict) else {}
    raw = str(cfg.get("codex_auto_list") or "")
    muc_tieu = (email or "").strip().lower()
    if not muc_tieu:
        return None
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split("|") if "|" in ln else ln.split(":")
        if parts and parts[0].strip().lower() == muc_tieu:
            return [p.strip() for p in parts]
    return None


def _has_profile(profile: str) -> bool:
    import os
    return os.path.isdir(os.path.join(_CAPTCHA_PROFILES, profile))


def _has_google_creds(profile: str, email: str = "") -> bool:
    """True if captcha accounts_db has password for this profile/email."""
    try:
        import os
        import sqlite3

        db = "/app/data/captcha/accounts.db"
        if not os.path.isfile(db):
            return False
        con = sqlite3.connect(db)
        try:
            # By email first
            if email:
                row = con.execute(
                    "SELECT password FROM accounts WHERE lower(email)=lower(?) LIMIT 1",
                    (email,),
                ).fetchone()
                if row and row[0]:
                    return True
            # By profile localpart (same rules as resolve_account)
            local = profile
            for pfx in ("google-", "chatgpt-", "codex-", "claude-", "gemini-"):
                if local.startswith(pfx):
                    local = local[len(pfx):]
                    break
            local = local.replace("-", "").replace(".", "").lower()
            rows = con.execute("SELECT email, password FROM accounts").fetchall()
            for em, pw in rows:
                if not pw:
                    continue
                lp = str(em or "").split("@")[0].lower().replace(".", "").replace("-", "")
                if lp == local:
                    return True
        finally:
            con.close()
        return False
    except Exception:
        return False


# Trạng thái auto-login CUỐI của từng profile, để tầng trên báo ĐÚNG nguyên nhân
# thay vì một câu "không khôi phục được" chung chung. Chỉ ghi/đọc chuỗi ngắn, một
# khoá mỗi profile — không phải cache, không cần hết hạn.
_LAST_LOGIN_STATE: dict[str, str] = {}

# Lý do đọc được đi kèm trạng thái đó — CHÍNH LÀ thứ solver nói ("Hồ sơ đang bận
# — chưa tới lượt", "no saved Google credentials…") hoặc lỗi mạng của chính lượt
# gọi này. Thiếu nó thì mọi kiểu trượt đều bị in ra bằng một câu đoán mò.
_LAST_LOGIN_NOTE: dict[str, str] = {}


def _ghi_ket_qua(profile: str, state: str, note: str = "") -> None:
    """Ghi trạng thái + lý do của lượt đăng nhập Google gần nhất."""
    if state:
        _LAST_LOGIN_STATE[profile] = state
    _LAST_LOGIN_NOTE[profile] = (note or "")[:200]


# Những trạng thái nghĩa là PHẢI CÓ NGƯỜI, máy chờ thêm cũng vô ích:
# - need_captcha : Google bắt captcha; auto_login chỉ gắn cờ rồi đợi người gõ
#                  trên noVNC. Thiếu nó trong danh sách này thì vòng poll chờ hết
#                  ~310 s mới bỏ — mỗi lần thử đốt 5 phút và mở một phiên trình
#                  duyệt ngồi im ở màn hình captcha (đo thật 30/07: 10:03:01 phát
#                  hiện captcha → 10:08:02 đóng, state=failed).
# - need_code / need_tap : 2FA không có TOTP → cần người bấm.
_CAN_NGUOI = ("need_captcha", "need_code", "need_tap")


def _freshen_google(profile: str, *,
                    khi_toi_luot: Callable[[float], None] | None = None) -> bool:
    """Tầng 2 — 'Đăng nhập tài khoản Google': làm tươi session Google bằng
    credentials đã lưu trong solver (accounts_db, có totp → tự chạy). Trả True
    nếu login thành công. Password KHÔNG rời khỏi solver.

    ``khi_toi_luot`` được gọi ĐÚNG lúc lượt này bắt đầu chạy thật, kèm số giây
    đã nằm chờ. Người gọi báo tin ở đó chứ đừng báo trước khi gọi hàm này: chờ
    tới lượt có thể mất hàng chục phút, mà tin báo gửi trước thì nói rằng mọi
    tài khoản đang đăng nhập cùng lúc — đúng thứ khoá dưới đây sinh ra để tránh.
    """
    import requests
    url, api_key = _solver_cfg()
    base = url.rstrip("/")
    H = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    # Chờ tới lượt: chỉ MỘT phiên đăng nhập Google trên toàn hệ thống tại một
    # thời điểm. 6 tài khoản chết cùng lúc → 6 thread xếp hàng ở đây, không bắn
    # login đồng thời (thứ làm Google bung captcha). Lock giữ suốt cả lượt poll
    # nên tài khoản sau chỉ bắt đầu khi tài khoản trước đã xong.
    global _glogin_last_done
    vao_hang = time.time()
    _glogin_serial.acquire()
    try:
        cho = _GLOGIN_GAP_S - (time.time() - _glogin_last_done)
        if cho > 0:
            time.sleep(cho)  # giãn cách như bấm tay lần lượt
        if khi_toi_luot is not None:
            try:
                khi_toi_luot(time.time() - vao_hang)
            except Exception:
                pass
        r = requests.post(f"{base}/v1/session/auto-login-saved", headers=H,
                          json={"profile": profile}, timeout=30)
        d = r.json() or {}
        st = d.get("state", "")
        _ghi_ket_qua(profile, st, str(d.get("error") or d.get("message") or ""))
        if st in ("failed", "blocked", "error"):
            return False
        # Poll tối đa ~700s — KHỚP ngân sách thật của auto_login: 420s cho giai
        # đoạn vào ô mật khẩu (lặp 'Thử lại' + bấm lại vào mail, ~100 lượt) + 240s
        # cho bước 2FA + lề. Chờ ngắn hơn là bỏ cuộc oan khi nó VẪN ĐANG thử —
        # đúng kiểu "cắt bớt số lần thử" mà bản trước mắc.
        # 'running' = đang thử lại → cứ chờ tiếp.
        for _ in range(140):
            time.sleep(5)
            try:
                s = requests.get(f"{base}/v1/session/{profile}/auto-login-status",
                                 headers=H, timeout=15).json()
            except Exception:
                continue
            state = str(s.get("state") or "")
            _ghi_ket_qua(profile, state, str(s.get("error") or s.get("message") or ""))
            if state in ("success", "done", "logged_in"):
                return True
            if state in ("failed", "blocked", "error") or state in _CAN_NGUOI:
                # Cần người → bỏ NGAY, đừng chờ hết ngân sách. Chờ thêm không
                # làm captcha tự biến mất, chỉ giữ trình duyệt mở vô ích.
                return False
        _LAST_LOGIN_STATE.setdefault(profile, "timeout")
        _LAST_LOGIN_NOTE.setdefault(profile, "hết 700s vẫn chưa xong")
        return False
    except Exception as exc:
        # KHÔNG được nuốt. Lượt trượt vì lỗi mạng/timeout trông y hệt lượt trượt
        # vì Google chặn, nếu chỗ này im lặng. Đo thật 09/08/2026
        # (benbap115@gmail.com): handler `/v1/session/auto-login-saved` treo vì hồ
        # sơ đang bận, POST hết hạn 30s, `except Exception: return False` trần
        # nuốt sạch — không log, không trạng thái — nên tin báo cho chủ máy nói
        # "không vào được ô mật khẩu (Google chặn)" về một trình duyệt chưa mở.
        _ghi_ket_qua(profile, "error", f"{type(exc).__name__}: {exc}")
        logger.warning({
            "event": "freshen_google_error",
            "profile": profile,
            "error": str(exc)[:200],
        })
        return False
    finally:
        # Đóng mốc SAU khi phiên này xong để tài khoản kế tiếp tính giãn cách từ
        # đây, rồi mới nhả lượt cho nó.
        _glogin_last_done = time.time()
        _glogin_serial.release()


def trang_thai_dang_nhap_cuoi(profile: str) -> str:
    """Trạng thái auto-login cuối của profile ("" nếu chưa từng thử)."""
    return _LAST_LOGIN_STATE.get(profile, "")


def ly_do_dang_nhap_cuoi(profile: str) -> str:
    """Lý do đọc được kèm trạng thái đó ("" nếu không có)."""
    return _LAST_LOGIN_NOTE.get(profile, "")


# ── Steps riêng theo provider ────────────────────────────────────────────────

def _codex_pick_working(email: str) -> str:
    """Quet pool tim token codex CON SONG cua email; don token chet cung email.

    FIX: khong duoc giu account_service._lock xuyen suot vong goi mang
    (list_models, timeout=30) - lock nay gate gan nhu moi thao tac account o
    request-path, mot luot quet nhieu account chet co the khoa ca traffic
    song hang chuc giay moi lan. Snapshot token duoi lock -> probe network
    KHONG lock -> ghi ket qua qua update_account() (tu lock ngan moi lan).
    Theo dung pattern services/providers/antigravity.py::_try_refresh_antigravity_token.
    """
    from services.account_service import account_service, account_group
    from services.openai_backend_api import OpenAIBackendAPI
    good = ""
    with account_service._lock:
        candidates = [
            k for k, a in account_service._accounts.items()
            if isinstance(a, dict) and account_group(a) == "codex"
            and str(a.get("email") or "").lower() == email.lower()
            and str(k).startswith("eyJ")
        ]

    for token in candidates:
        try:
            OpenAIBackendAPI(access_token=token).list_models()
            good = token
            account_service.update_account(token, {"status": "active"})
        except Exception:
            account_service.update_account(token, {"status": "disabled"})
    return good


def _codex_exchange_from_redirect(redirect_url: str, state: str) -> None:
    """Đổi code → token. Lỗi "state đã dùng" ở đây được NUỐT CÓ CHỦ Ý.

    Trình duyệt chạy trong CÙNG container, nên khi nó đi tới
    http://localhost:1455/auth/callback?code=… thì listener :1455
    (services/codex_callback_listener) bắt được và đổi code TRƯỚC. State là
    dùng-một-lần, nên lần đổi thứ hai này chắc chắn ném ValueError.

    Đo thật 30/07 (smarthomebanbap2011@gmail.com): tầng 2 lấy code lúc 21:00:33,
    token mới vào pool và account về active — nhưng lần đổi thứ hai ném lỗi, lỗi
    đó xuyên qua _codex_reuse ra tới scheduler và được ghi thành
    `dead_recovery_t13_error`; người vận hành nhận ❌ trong khi tài khoản ĐÃ sống.

    Ai thắng cuộc đua không quan trọng. Người phán xử là _codex_pick_working():
    có token dùng được hay không.
    """
    from urllib.parse import urlparse, parse_qs
    from services.oauth_service import exchange_codex_code
    q = parse_qs(urlparse(redirect_url or "").query)
    code = (q.get("code") or [""])[0]
    st = (q.get("state") or [state])[0]
    try:
        exchange_codex_code(code, st)
    except Exception as exc:
        logger.info({
            "event": "codex_exchange_skipped",
            "error": str(exc)[:160],
            "hint": "thường là listener :1455 đã đổi code trước — kiểm token trong pool",
        })


def _cho_token_song(email: str, so_lan: int = 4, nghi: float = 4.0) -> str:
    """Chờ token mới hiện trong pool rồi trả về token còn sống ('' nếu không có).

    `codex-google-onboard` trả về NGAY khi bắt được request callback, tức có thể
    sớm hơn lúc việc đổi code xong vài giây. Hỏi pool đúng một lần là dễ hụt.
    """
    tok = ""
    for lan in range(so_lan):
        tok = _codex_pick_working(email)
        if tok:
            return tok
        if lan < so_lan - 1:
            time.sleep(nghi)
    return tok


def _codex_reuse(profile: str, email: str) -> str:
    """Tầng 1/2-retry — ride session Google, authorize Codex → token. '' nếu fail."""
    import requests
    from services.oauth_service import get_codex_auth_url
    url, api_key = _solver_cfg()
    auth = get_codex_auth_url("http://localhost:1455")
    try:
        r = requests.post(f"{url.rstrip('/')}/v1/codex-google-onboard",
                          headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                          json={"profile": profile, "auth_url": auth["auth_url"],
                                "email": email, "headless": True}, timeout=180)
        data = r.json()
    except Exception:
        return ""
    if data.get("state") != "success":
        # Tài khoản bị OpenAI xóa/vô hiệu hóa — VĨNH VIỄN, y hệt nhánh T3 hàng
        # loạt bên dưới. Không bắt ở đây thì tài khoản giữ nguyên status 'error'
        # và lượt quét định kỳ lôi ra thử lại mỗi 2 tiếng, mãi mãi.
        _deact = f"{data.get('error_code') or ''} {data.get('error') or ''}".lower()
        if "account_deactivated" in _deact:
            from services.codex_deactivated import handle_deactivated, CodexAccountDeactivated
            handle_deactivated(
                email,
                reason="T2 mở đăng nhập Codex trong workspace → account_deactivated",
            )
            raise CodexAccountDeactivated(email)
        return ""
    _codex_exchange_from_redirect(data.get("redirect_url") or "", auth["state"])
    return _cho_token_song(email)


def _codex_batch(email: str) -> str:
    """Tầng 3 — 'Danh sách Tài khoản Codex' (config.codex_auto_list).

    Cùng endpoint/code Playwright với nút "Đăng nhập hàng loạt":
      POST captcha-solver /v1/codex-onboard → run_codex_onboard
      (Microsoft OTC + IMAP + Tiếp tục + bắt OAuth callback).

    IMAP: ưu tiên cột 3–4 trên dòng; nếu trống → IMAP Gmail dùng chung
    (config.codex_imap_gmail_email / codex_imap_gmail_app_password).
    """
    import requests
    from services.config import config
    from services.oauth_service import get_codex_auth_url
    cfg = config.data if isinstance(config.data, dict) else {}
    line = _dong_hang_loat(email)
    if not line or len(line) < 2:
        return ""
    g_email, g_pass = line[0].strip(), line[1].strip()
    # Per-line IMAP optional; shared IMAP from settings (same as UI batch)
    shared_imap = str(cfg.get("codex_imap_gmail_email") or "").strip()
    shared_pass = str(cfg.get("codex_imap_gmail_app_password") or "").strip()
    imap_email = (line[2].strip() if len(line) > 2 and line[2].strip() else shared_imap)
    imap_pass = (line[3].strip() if len(line) > 3 and line[3].strip() else shared_pass)
    if not imap_email or not imap_pass:
        logger.warning({
            "event": "codex_batch_missing_imap",
            "email": email,
            "hint": "Điền IMAP Gmail dùng chung trong Settings Codex hoặc thêm |imap|pass trên dòng",
        })
        return ""
    url, api_key = _solver_cfg()
    auth = get_codex_auth_url("http://localhost:1455")
    try:
        # 420s: OTC + IMAP poll + consent can exceed 4 min
        r = requests.post(
            f"{url.rstrip('/')}/v1/codex-onboard",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "auth_url": auth["auth_url"],
                "github_email": g_email,
                "github_password": g_pass,
                "gmail_email": imap_email,
                "gmail_app_password": imap_pass,
            },
            timeout=420,
        )
        data = r.json()
    except Exception as exc:
        logger.warning({"event": "codex_batch_request_failed", "email": email, "error": str(exc)[:160]})
        return ""
    # Tài khoản đã bị xóa/vô hiệu hóa (OpenAI account_deactivated) — VĨNH VIỄN,
    # không refresh được. Báo admin + hỏi xóa, rồi short-circuit (đừng báo
    # "KHÔNG khôi phục được" generic nữa).
    _deact = f"{data.get('error_code') or ''} {data.get('error') or ''}".lower()
    if "account_deactivated" in _deact:
        from services.codex_deactivated import handle_deactivated, CodexAccountDeactivated
        handle_deactivated(email, reason="refresh nhiều tầng (T3 bulk onboard) → account_deactivated")
        raise CodexAccountDeactivated(email)
    if data.get("state") != "success" or not data.get("redirect_url"):
        logger.warning({
            "event": "codex_batch_onboard_failed",
            "email": email,
            "error": str(data.get("error") or data.get("state") or "")[:200],
        })
        return ""
    _codex_exchange_from_redirect(data.get("redirect_url"), auth["state"])
    return _cho_token_song(email)


def _cgf_onboard_once(profile: str, *, reuse_session: bool, timeout_polls: int = 36) -> str:
    """One ChatGPT onboard attempt. Returns JWT or ''."""
    import requests
    url, api_key = _solver_cfg()
    base = url.rstrip("/")
    H = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        r = requests.post(
            f"{base}/v1/chatgpt/onboard",
            headers=H,
            json={
                "profile": profile,
                "email": "",
                "password": "",
                "reuse_session": reuse_session,
            },
            timeout=180,
        )
        init = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    except Exception as exc:
        logger.warning({
            "event": "cgf_onboard_request_failed",
            "profile": profile,
            "reuse": reuse_session,
            "error": str(exc)[:160],
        })
        return ""
    token = str(init.get("access_token") or "")
    state = str(init.get("state") or "")
    if state == "success" and token.startswith("eyJ"):
        return token
    if state != "success" or not token.startswith("eyJ"):
        for i in range(timeout_polls):  # default ~180s
            time.sleep(5)
            try:
                s = requests.get(
                    f"{base}/v1/chatgpt/{profile}/onboard-status",
                    headers=H,
                    timeout=15,
                ).json()
            except Exception:
                continue
            st = str(s.get("state") or "")
            tok = str(s.get("access_token") or "")
            if st == "success" and tok.startswith("eyJ"):
                return tok
            if st in ("failed", "error"):
                logger.warning({
                    "event": "cgf_onboard_failed",
                    "profile": profile,
                    "reuse": reuse_session,
                    "error": str(s.get("error") or s.get("message") or "")[:200],
                    "poll": i,
                })
                return ""
    if token.startswith("eyJ"):
        return token
    return ""


def _cgf_reuse(profile: str, email: str) -> str:
    """ChatGPT-free (web JWT): ride Google/ChatGPT session → scrape JWT →
    upsert free pool (chỉ email đã có). '' nếu fail.

    ĐÚNG MỘT lượt, `reuse_session=True`.

    Bản cũ thử thêm lượt hai với `reuse_session=False`, ý là "SSO đầy đủ hơn khi
    cookie ChatGPT chết nhưng profile Google vẫn còn". Ý đó không thực hiện được:
    `_cgf_onboard_once` luôn gửi email và mật khẩu RỖNG, nên lượt hai không có gì
    để đăng nhập Google — nó chỉ kịp XOÁ hồ sơ (đường `reuse_session=False` gọi
    `_nuke_profile`) rồi lặp vô ích.

    Đo thật 09/08/2026 (benbap115@gmail.com): lượt hai xoá mất phiên Google đang
    sống lúc 22:13:41, chạy tiếp 7 phút rưỡi với ô email trống ("bấm lại vào mail
    lần 35"), giữ khoá hồ sơ — nên tầng T3 xếp hàng phía sau treo luôn và cả
    thang khôi phục báo hỏng. Tài khoản đi từ "chỉ hỏng token" thành "mất luôn
    phiên Google", phải đăng nhập tay.
    """
    token = _cgf_onboard_once(profile, reuse_session=True)
    if not token or not token.startswith("eyJ"):
        return ""
    try:
        from services.account_service import account_service
        # Chỉ refresh/cập nhật tài khoản free ĐÃ có trong pool (cùng email).
        # Không tự thêm email mới từ profile captcha / saved accounts.
        existing = account_service.find_free_by_email(email)
        if not existing:
            logger.info({
                "event": "cgf_reuse_skip_not_in_pool",
                "email": email,
                "hint": "Chỉ refresh account free user đã thêm tay — không auto-add",
            })
            return ""
        account_service.upsert_free_token(token, {
            "status": "active",
            "email": email,
        })
        logger.info({
            "event": "cgf_reuse_ok",
            "email": email,
            "profile": profile,
            "reuse_session": True,
        })
        return token
    except Exception as exc:
        logger.warning({
            "event": "cgf_reuse_upsert_failed",
            "email": email,
            "error": str(exc)[:160],
        })
        return ""


# ── gma (Gemini web) — theo PROFILE (không có token pool, cookie fetch live) ──

def _gma_authenticated(profile: str) -> bool:
    """Session gma của profile có AUTHENTICATED không (account_status AVAILABLE).
    Đây là tín hiệu THẬT của gma (không dựa state string của onboard)."""
    try:
        import api.gemini_web as gw
        ck = gw._fetch_cookies_from_solver(profile)
        psid = ck.get("__Secure-1PSID", "")
        if not psid:
            return False
        cli = gw._get_client(psid, ck.get("__Secure-1PSIDTS", ""))
        st = getattr(cli, "account_status", None)
        return st is not None and getattr(st, "name", "") == "AVAILABLE"
    except Exception:
        return False


def _gma_has_session(profile: str) -> bool:
    """Profile có cookie session Google (__Secure-1PSID) không. Sau relogin,
    gma kích hoạt AVAILABLE ở lượt dùng kế — nên cookie-có-mặt là đủ để coi
    session đã khôi phục."""
    try:
        import api.gemini_web as gw
        return bool(gw._fetch_cookies_from_solver(profile).get("__Secure-1PSID"))
    except Exception:
        return False


def _gma_reuse(profile: str) -> bool:
    """Khôi phục session Gemini web cho profile. Nếu đang AUTHENTICATED thật
    (account_status AVAILABLE) → xong ngay. Nếu không → relogin-via-google
    (solver tự tra creds, ride SSO hoặc full login) → chờ session cookie xuất
    hiện lại (activation AVAILABLE diễn ra ở lượt dùng kế)."""
    if _gma_authenticated(profile):
        return True
    import requests
    url, api_key = _solver_cfg()
    H = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        requests.post(f"{url.rstrip('/')}/v1/gemini-web/{profile}/relogin-via-google",
                      headers=H, timeout=150)
    except Exception:
        pass
    for _ in range(18):  # chờ ~90s: session cookie khôi phục hoặc auth AVAILABLE
        time.sleep(5)
        if _gma_authenticated(profile) or _gma_has_session(profile):
            return True
    return False


def gma_recover_and_notify(profile: str, reason: str = "mất session") -> None:
    """Khôi phục 1 profile Gemini web (thread nền) + Telegram. Thang:
    T1 tái dùng (gemini-web onboard, ride Google) → T2 'Đăng nhập tài khoản
    Google' làm tươi rồi tái dùng lại → hết thì báo tay. Debounce 30ph/profile."""
    key = f"recover:gma:{profile}"
    with _lock:
        if time.time() - _last_attempt.get(key, 0.0) < _GRELOGIN_COOLDOWN_S:
            return
        _last_attempt[key] = time.time()

    started = time.time()
    det = {"provider": "gemini_web_api", "profile": profile}
    _notify(f"⚠️ Gemini web — {profile}\nLỗi: {reason}\n→ Đang tự khôi phục…",
            {**det, "step": "start", "reason": reason})
    if _gma_reuse(profile):
        _notify(f"✅ Gemini web — {profile}\nKhôi phục xong ([T1] tái dùng session Google).",
                {**det, "step": "T1-reuse-ok"})
        logger.info({"event": "recover_ok", "provider": "gemini_web_api", "tier": "reuse", "profile": profile})
        return
    if time.time() - started < _RECOVER_BUDGET_S:
        _notify(f"🔧 Gemini web — {profile}\n[T1] tái dùng lỗi → [T2] đang đăng nhập lại tài khoản Google…",
                {**det, "step": "T2-freshen"})
        if _freshen_google(profile) and _gma_reuse(profile):
            _notify(f"✅ Gemini web — {profile}\nKhôi phục xong ([T2] đăng nhập Google + tái dùng).",
                    {**det, "step": "T2-freshen-ok"})
            logger.info({"event": "recover_ok", "provider": "gemini_web_api", "tier": "freshen", "profile": profile})
            return
    _notify(f"❌ Gemini web — {profile}\nKHÔNG tự khôi phục được. Cần xử lý tay (noVNC cổng 6080).",
            {**det, "step": "failed"})
    logger.warning({"event": "recover_failed", "provider": "gemini_web_api", "profile": profile})


# ── flow (Google Labs Flow / Veo) — theo PROFILE, session labs.google ─────────

def _flow_session_trang_thai(profile: str) -> str:
    """Phiên Flow của profile: 'ok' | 'ban' | 'mat'.

    VÌ SAO PHẢI TÁCH 'ban' RA: `get-or-create-project` lấy trình duyệt bằng
    `pool.page()`, mà hàm đó fast-failover **429 Account Busy** ngay khi hồ sơ
    đang bị lượt khác giữ — tức là đúng lúc tài khoản đang TẠO ẢNH/VIDEO. Bản
    cũ chỉ đọc `project_id`, nên 429 rơi vào nhánh "không có project_id" và bị
    kết luận là MẤT PHIÊN.

    Hậu quả đo thật 09/08/2026 (chủ máy báo "tôi thấy vẫn vào và tạo được mà
    nhỉ"): bộ quét định kỳ bắt gặp một tài khoản đang tạo ảnh → báo "mất phiên
    labs.google" → chạy T2 đăng nhập lại Google (tuần tự toàn hệ thống, vài
    phút, và mỗi lần login tự động là một lần mời Google bung captcha) → kiểm
    lại vẫn bận → kết luận "KHÔNG tự khôi phục được, cần đăng nhập tay". Toàn
    bộ chuỗi đó xảy ra trên một tài khoản HOÀN TOÀN KHOẺ.

    Bận thì im lặng bỏ qua: vòng quét sau sẽ kiểm lại. Chỉ 'mat' mới được kích
    hoạt khôi phục.
    """
    import requests
    url, api_key = _solver_cfg()
    H = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        r = requests.post(f"{url.rstrip('/')}/v1/google/flow/get-or-create-project",
                          headers=H, json={"profile": profile, "headless": True,
                                           "timeout": 150}, timeout=170)
        if r.status_code == 429:
            return "ban"
        return "ok" if (r.json() or {}).get("project_id") else "mat"
    except Exception:
        return "mat"


def _flow_session_ok(profile: str) -> bool:
    """Còn giữ cho các chỗ chỉ cần biết phiên có dùng được ngay không.

    'ban' KHÔNG phải 'ok' (chưa chứng minh được phiên còn sống) nhưng cũng
    tuyệt đối không phải 'mat'. Nơi nào ra quyết định khôi phục thì phải gọi
    `_flow_session_trang_thai` để thấy đủ ba trạng thái.
    """
    return _flow_session_trang_thai(profile) == "ok"


def flow_recover_and_notify(profile: str, reason: str = "mất phiên") -> None:
    """Khôi phục 1 profile Flow (thread nền) + Telegram. T1 kiểm/tái lập phiên
    labs.google → T2 'Đăng nhập tài khoản Google' rồi thử lại. Debounce 30ph."""
    key = f"recover:flow:{profile}"
    with _lock:
        if time.time() - _last_attempt.get(key, 0.0) < _GRELOGIN_COOLDOWN_S:
            return
        _last_attempt[key] = time.time()

    started = time.time()
    det = {"provider": "flow", "profile": profile}
    # Kiểm TRƯỚC khi báo động. Hồ sơ đang bận tạo ảnh/video là tài khoản KHOẺ —
    # báo "đang tự khôi phục" rồi mới phát hiện ra thì người nhận đã hoảng, và
    # dòng "KHÔNG khôi phục được" ở cuối là lời báo sai.
    tt = _flow_session_trang_thai(profile)
    if tt == "ban":
        logger.info({"event": "recover_skip_busy", "provider": "flow", "profile": profile,
                     "reason": reason[:120]})
        return
    _notify(f"⚠️ Flow — {profile}\nLỗi: {reason}\n→ Đang tự khôi phục…",
            {**det, "step": "start", "reason": reason})
    if tt == "ok":
        _notify(f"✅ Flow — {profile}\nKhôi phục xong ([T1] phiên labs.google còn sống).",
                {**det, "step": "T1-reuse-ok"})
        logger.info({"event": "recover_ok", "provider": "flow", "tier": "reuse", "profile": profile})
        return
    if time.time() - started < _RECOVER_BUDGET_S:
        _notify(f"🔧 Flow — {profile}\n[T1] mất phiên → [T2] đang đăng nhập lại tài khoản Google…",
                {**det, "step": "T2-freshen"})
        # Sau khi đăng nhập lại, 'ban' cũng là tin tốt: hồ sơ đang phục vụ một
        # lượt việc khác, tức trình duyệt sống và có phiên. Đòi đúng 'ok' ở đây
        # là lại báo hỏng cho một tài khoản vừa khôi phục xong.
        if _freshen_google(profile) and _flow_session_trang_thai(profile) in ("ok", "ban"):
            _notify(f"✅ Flow — {profile}\nKhôi phục xong ([T2] đăng nhập Google + tái lập phiên).",
                    {**det, "step": "T2-freshen-ok"})
            logger.info({"event": "recover_ok", "provider": "flow", "tier": "freshen", "profile": profile})
            return
    _notify(f"❌ Flow — {profile}\nKHÔNG tự khôi phục được. Cần đăng nhập lại tay (noVNC cổng 6080).",
            {**det, "step": "failed"})
    logger.warning({"event": "recover_failed", "provider": "flow", "profile": profile})


# ── Registry provider (bật dần) ──────────────────────────────────────────────

_PROVIDERS: dict[str, dict[str, Any]] = {
    "codex": {"enabled": True, "label": "Codex",
              "reuse": _codex_reuse, "batch": _codex_batch},
    # Label dùng trong tin nhắn bot admin (log ChatGPT free / Codex)
    "free": {"enabled": True, "label": "ChatGPT free",
             "reuse": _cgf_reuse, "batch": None},
    # Bật dần tiếp:
    "gemini_web_api": {"enabled": False, "label": "Gemini web"},
    "claude": {"enabled": False, "label": "Claude"},
    "flow": {"enabled": False, "label": "Flow"},
}


def con_tang_trinh_duyet(email: str, provider: str) -> bool:
    """Sau tầng T0 (refresh_token) còn tầng TRÌNH DUYỆT nào chạy được không?

    T0 nằm ở `recover_and_notify`, các tầng trình duyệt nằm ở
    `recover_provider_account`, và người gọi (`codex_error_recovery_scheduler`)
    chạy LẦN LƯỢT cả hai. Nhưng T0 không hề biết điều đó nên nó tự kết luận
    "❌ Cần đăng nhập lại thủ công" ngay khi thiếu refresh_token — rồi vài giây
    sau tầng trình duyệt mới bắt đầu và báo "→ Đang tự khôi phục…". Người nhận
    đọc được lời tuyên bố thua TRƯỚC cả lúc hệ thống bắt đầu thử, nên hoặc đi
    đăng nhập tay một tài khoản mà máy tự chữa được, hoặc mất tin vào thông báo.

    Tách phép kiểm ra đây để T0 và tầng trình duyệt nói CÙNG một sự thật.
    """
    prov = _PROVIDERS.get(provider) or {}
    if not prov.get("enabled"):
        return False
    profile = _profile_for(email)
    can_google = bool(prov.get("reuse") and (_has_profile(profile)
                                             or _has_google_creds(profile, email)))
    can_batch = bool(prov.get("batch") and _dong_hang_loat(email) is not None)
    return can_google or can_batch


def recover_provider_account(account: dict[str, Any], provider: str, reason: str) -> None:
    """Các tầng khôi phục SAU KHI tầng 1 (refresh_token) đã trượt — thread nền.

    Phân loại tài khoản bằng **danh sách đăng nhập hàng loạt** (`codex_auto_list`),
    không bằng đuôi email — xem `_dong_hang_loat`.

    **KHÔNG có dòng trong danh sách → tài khoản Google**
      T2  Mở đăng nhập Codex trong workspace của tài khoản đó: `codex-google-onboard`
          ride session Google của profile rồi authorize Codex (cần đã có profile).
      T3  Đăng nhập lại tài khoản Google — đúng nút "Chỉ đăng nhập" ở thẻ
          "Provider qua tài khoản Google" (`auto-login-saved`, mật khẩu + TOTP nằm
          trong solver) — xong thì làm lại T2 để lấy token.

    **CÓ dòng trong danh sách → tài khoản đăng nhập hàng loạt**
      T3  Giống hệt nút "Đăng nhập hàng loạt" nhưng chỉ với dòng của tài khoản
          đang lỗi (`codex-onboard`: email|pass, mã dùng một lần qua IMAP,
          consent, callback). Luồng này tự dựng profile mới nên không có session
          nào để ride — vì vậy tài khoản hàng loạt không có T2.
          Nếu tài khoản đó tình cờ cũng có creds Google đã lưu thì sau khi T3
          trượt vẫn thử tiếp thang Google: có đường nào thì đi.

    Mỗi bước báo Telegram; debounce 30ph/account."""
    prov = _PROVIDERS.get(provider) or {}
    if not prov.get("enabled"):
        return  # provider chưa bật auto-recovery → giữ hành vi cũ
    if not isinstance(account, dict):
        return
    label = prov.get("label", provider)
    email = _acct_label(account)
    profile = _profile_for(email)
    key = f"recover:{provider}:{email}"

    with _lock:
        if time.time() - _last_attempt.get(key, 0.0) < _GRELOGIN_COOLDOWN_S:
            return
        _last_attempt[key] = time.time()

    reuse = prov.get("reuse")
    batch = prov.get("batch")
    hang_loat = _dong_hang_loat(email) is not None
    has_profile = _has_profile(profile)
    has_creds = _has_google_creds(profile, email)
    # Ngân sách thời gian tổng — ca vô vọng (account bị ban) sẽ bail thay vì treo
    # mãi qua từng tầng browser. Ca hợp lệ (session Google còn sống) xong T2 trong
    # ~40s nên không đụng trần.
    started = time.time()
    # Thời gian NẰM CHỜ tới lượt đăng nhập Google — không tính vào ngân sách.
    # Ngân sách 1200s là để cắt một ca vô vọng, không phải để phạt tài khoản
    # xếp hàng sau: một lượt T3 giữ khoá tới 700s, nên tài khoản thứ ba trở đi
    # là hết giờ ngay khi tới lượt, và bước T2 lấy token sau khi đăng nhập
    # THÀNH CÔNG bị bỏ qua — máy báo "không khôi phục được" cho một tài khoản
    # vừa đăng nhập xong, rồi để nó nằm chết tới lần quét sau.
    cho_hang_doi = 0.0
    tried: list[str] = []

    def _con_gio() -> bool:
        return time.time() - started - cho_hang_doi < _RECOVER_BUDGET_S

    # KHÔNG có tầng nào chạy được → bỏ qua im lặng, đừng báo "đang khôi phục…"
    # rồi "KHÔNG khôi phục được (đã thử: none)". Ca điển hình: acc ChatGPT free
    # tự thu thập — không có dòng hàng loạt, cũng không có profile/creds Google,
    # tức không tồn tại đường đăng nhập lại nào để mà thử.
    can_google = bool(reuse and (has_profile or has_creds))
    can_batch = bool(batch and hang_loat)
    # Giữ nguyên phép kiểm tại chỗ (đã có `reuse`/`batch` trong tay) — nó phải
    # cho cùng kết quả với `con_tang_trinh_duyet`, thứ mà T0 dùng để biết có nên
    # im lặng nhường lượt hay không.
    if not (can_google or can_batch):
        logger.info({
            "event": "recover_skip_no_tier",
            "provider": provider,
            "email": email,
            "hang_loat": hang_loat,
            "has_profile": has_profile,
            "has_google_creds": has_creds,
            "reason": reason[:120],
        })
        return

    kind = "đăng nhập hàng loạt" if hang_loat else "tài khoản Google"
    det = {"provider": provider, "email": email}
    _notify(f"⚠️ {label} — {email}\nLỗi: {reason}\n→ Đang tự khôi phục ({kind})…",
            {**det, "step": "start", "reason": reason})
    logger.info({
        "event": "recover_start",
        "provider": provider,
        "email": email,
        "hang_loat": hang_loat,
        "has_profile": has_profile,
        "has_google_creds": has_creds,
        "reason": reason[:120],
    })

    def _do_reuse(tag: str, step: str, note: str) -> bool:
        tried.append(tag)
        if not reuse(profile, email):
            return False
        _notify(f"✅ {label} — {email}\nKhôi phục xong ({note}).",
                {**det, "step": step})
        logger.info({"event": "recover_ok", "provider": provider,
                     "tier": tag, "email": email})
        return True

    def _do_freshen() -> bool:
        tried.append("T3-đăng-nhập-Google")

        def _bao_khi_toi_luot(cho_giay: float) -> None:
            nonlocal cho_hang_doi
            cho_hang_doi += cho_giay
            them = f" — sau {cho_giay / 60:.0f} phút xếp hàng" if cho_giay >= 60 else ""
            _notify(f"🔧 {label} — {email}\n[T3] Đang đăng nhập lại tài khoản Google "
                    f"(giống nút 'Chỉ đăng nhập'){them}…",
                    {**det, "step": "T3-google-login", "cho_giay": round(cho_giay)})

        if _freshen_google(profile, khi_toi_luot=_bao_khi_toi_luot):
            return True
        logger.warning({"event": "recover_freshen_failed",
                        "provider": provider, "email": email})
        return False

    google_login_failed = False

    # ── Tài khoản ĐĂNG NHẬP HÀNG LOẠT: T3 = chạy lại đúng luồng hàng loạt ─────
    # Cùng endpoint/code với nút "Đăng nhập hàng loạt" (/v1/codex-onboard), chỉ
    # với dòng của tài khoản đang lỗi. Không có T2 vì luồng này tự dựng profile
    # mới (force_recreate) nên chẳng có session nào để tái dùng.
    if can_batch and _con_gio():
        tried.append("T3-hàng-loạt")
        _notify(
            f"🔧 {label} — {email}\n"
            f"[T3] Đăng nhập lại giống nút 'Đăng nhập hàng loạt', chỉ với tài "
            f"khoản này (email|pass + mã dùng một lần qua IMAP)…",
            {**det, "step": "T3-batch"},
        )
        from services.codex_deactivated import CodexAccountDeactivated
        try:
            tok = batch(email)
        except CodexAccountDeactivated:
            # account_deactivated: đã báo admin + hỏi xóa trong handle_deactivated.
            # Dừng hẳn, KHÔNG rơi xuống thông báo "KHÔNG tự khôi phục được".
            logger.info({"event": "recover_stop_deactivated", "provider": provider, "email": email})
            return
        if tok:
            _notify(f"✅ {label} — {email}\nKhôi phục xong ([T3] đăng nhập hàng loạt).",
                    {**det, "step": "T3-batch-ok"})
            logger.info({"event": "recover_ok", "provider": provider,
                         "tier": "T3-hàng-loạt", "email": email})
            return

    # ── Tài khoản GOOGLE: T2 (đăng nhập Codex trong workspace) → T3 (đăng nhập
    #    lại Google) → T2 lần nữa ───────────────────────────────────────────────
    if can_google:
        # T2 ĐI TRƯỚC: rẻ, không phải mở màn đăng nhập Google, và session Google
        # của profile thường VẪN SỐNG dù token Codex đã chết (OpenAI thu hồi
        # token chứ không đăng xuất Google).
        #
        # Bản cũ: hễ `reason` có chữ "dead"/"401"/"expired" là bỏ qua T2, đăng
        # nhập Google trước. Nhưng scheduler LUÔN gửi reason "dead:…", nên trên
        # đường quét định kỳ T2 thực tế CHƯA BAO GIỜ được chạy — đo thật 30/07
        # (smarthomebanbap2011@gmail.com): chỉ chạy đúng "T2-freshen", nó báo
        # thất bại oan (trang đang ở myaccount.google.com, tức đang đăng nhập),
        # rồi cả thang bị chặn theo và tài khoản nằm chết.
        from services.codex_deactivated import CodexAccountDeactivated
        try:
            if has_profile and _con_gio():
                if _do_reuse("T2-workspace", "T2-ok",
                             "[T2] mở đăng nhập Codex trong workspace (tái dùng "
                             "session Google của profile)"):
                    return
            if has_creds and _con_gio():
                if _do_freshen():
                    if _con_gio() and _do_reuse(
                            "T2-sau-T3", "T3-ok",
                            "[T3] đăng nhập lại Google + [T2] đăng nhập Codex tại workspace"):
                        return
                else:
                    google_login_failed = True
        except CodexAccountDeactivated:
            # handle_deactivated đã báo admin + hỏi xóa/giữ. Dừng hẳn, KHÔNG rơi
            # xuống thông báo "KHÔNG tự khôi phục được" chung chung bên dưới.
            logger.info({"event": "recover_stop_deactivated",
                         "provider": provider, "email": email})
            return

    tried_s = " → ".join(tried) if tried else "none"
    # Nguyên nhân CỤ THỂ thắng gợi ý chung.
    #
    # Câu "Kiểm tra profile Google / pass+TOTP / codex_auto_list + IMAP" đưa người
    # đọc đi sai hướng khi thực tế là Google bắt captcha: mật khẩu, TOTP, IMAP đều
    # đúng cả, không có gì để "kiểm tra". Đo thật 30/07 với benbap2011@gmail.com —
    # log auto_login ghi rõ captcha, còn thông báo lại bảo đi soi cấu hình.
    #
    # Và KHÔNG khẳng định thứ chưa đo. Đo thật 09/08/2026 (benbap115@gmail.com):
    # lượt T3 hết hạn 30s ở tầng HTTP vì hồ sơ đang bận — trình duyệt chưa từng
    # mở — mà tin báo vẫn nói chắc "không vào được ô mật khẩu (Google chặn hoặc
    # đổi giao diện)". Chủ máy bấm tay "Chỉ đăng nhập" ngay sau đó thì vào bình
    # thường, nên câu đổ lỗi cho Google vừa sai vừa làm mất tin vào thông báo.
    trang_thai = trang_thai_dang_nhap_cuoi(profile) if can_google else ""
    ly_do = ly_do_dang_nhap_cuoi(profile) if can_google else ""
    if trang_thai == "need_captcha":
        hint = ("Google đang bắt CAPTCHA — vào noVNC cổng 6080 gõ captcha, hệ thống "
                "TỰ tiếp tục mật khẩu + 2FA. Mật khẩu/TOTP/IMAP không liên quan.")
    elif trang_thai in ("need_code", "need_tap"):
        hint = ("Google đòi mã 2FA phải người bấm (profile này chưa có TOTP) — "
                "xử lý trên noVNC cổng 6080, hoặc thêm TOTP cho profile.")
    elif google_login_failed:
        vi_sao = ly_do or f"solver báo trạng thái '{trang_thai or 'không rõ'}'"
        hint = (f"Đăng nhập lại Google chưa xong. Lý do: {vi_sao}. Đăng nhập tay "
                f"MỘT lần qua noVNC cổng 6080 (profile {profile}), xong hệ thống "
                f"tự dùng lại session đó.")
    elif hang_loat:
        hint = ("Soi lại dòng email|pass của tài khoản này trong Settings Codex "
                "(codex_auto_list) + IMAP Gmail dùng chung.")
    elif not (has_profile or has_creds):
        hint = ("Chưa có đường nào để đăng nhập lại: lưu tài khoản Google "
                "(email + mật khẩu + TOTP) ở thẻ 'Provider qua tài khoản Google', "
                "hoặc thêm dòng vào danh sách đăng nhập hàng loạt.")
    else:
        hint = "Kiểm tra profile Google + mật khẩu/TOTP đã lưu trong solver."
    _notify(
        f"❌ {label} — {email}\n"
        f"KHÔNG tự khôi phục được (đã thử: {tried_s}).\n"
        f"→ {hint}\n"
        f"→ Hoặc xử lý tay noVNC cổng 6080.",
        {**det, "step": "failed", "reason": f"tried: {tried_s}"},
    )
    logger.warning({
        "event": "recover_failed",
        "provider": provider,
        "email": email,
        "hang_loat": hang_loat,
        "tried": tried,
    })


def codex_google_relogin_and_notify(account: dict[str, Any], reason: str) -> None:
    """Wrapper tương thích call-site cũ → orchestrator chung cho codex."""
    recover_provider_account(account, "codex", reason)


def recover_and_notify(account: dict[str, Any], reason: str) -> str | None:
    """Recover a failing account (reuse refresh_token) and notify admin of the
    error → action → result. Returns the NEW access_token on success, else None.
    Best-effort; never raises. Debounced per account."""
    if not isinstance(account, dict):
        return None
    email = _acct_label(account)
    key = str(account.get("access_token") or email)
    # Nhãn provider để log đủ "tài khoản nào, provider nào" (codex/free/…)
    try:
        from services.account_service import account_group
        group = account_group(account)
    except Exception:
        group = ""
    label = _PROVIDERS.get(group, {}).get("label") or {
        "openai": "OpenAI", "antigravity": "Antigravity",
    }.get(group, group or "ChatGPT")
    det = {"provider": group or "chatgpt", "email": email}

    with _lock:
        if time.time() - _last_attempt.get(key, 0.0) < _COOLDOWN_S:
            return None  # attempted recently — skip to avoid spam
        _last_attempt[key] = time.time()

    if not str(account.get("refresh_token") or "").strip():
        # Acc tự thu thập (free/bulk): KHÔNG có email → không có đường đăng nhập
        # lại nào để mà refresh. Báo mỗi lần chỉ là nhiễu → chỉ ghi log.
        if not str(account.get("email") or "").strip():
            logger.info({"event": "recovery_skip_anonymous", "provider": group,
                         "email": email, "reason": reason[:120]})
            return None
        # CÒN tầng trình duyệt phía sau thì T0 KHÔNG được tuyên bố thua. Người
        # gọi sẽ chạy tiếp T1–T3 ngay sau đây; báo "cần đăng nhập tay" lúc này
        # là nói sai, và nói trước cả lúc hệ thống bắt đầu thử.
        if con_tang_trinh_duyet(email, group):
            logger.info({"event": "recovery_t0_nhuong_luot", "email": email,
                         "provider": group, "reason": reason[:120]})
            return None
        _notify(f"⚠️ {label} — {email}\nLỗi: {reason}\n"
                f"→ [T0] Không có refresh_token, và không còn đường đăng nhập lại "
                f"tự động nào cho tài khoản này.\n"
                f"❌ Cần đăng nhập lại thủ công qua noVNC (cổng 6080).",
                {**det, "step": "T0-no-refresh-token", "reason": reason})
        logger.warning({"event": "recovery_no_refresh", "email": email, "reason": reason})
        return None

    _notify(f"⚠️ {label} — {email}\nLỗi: {reason}\n→ [T0] Đang tự làm mới token (refresh)…",
            {**det, "step": "T0-refresh", "reason": reason})
    try:
        from services.codex_refresh_scheduler import _refresh_one
        from services.account_service import account_service
        updated = _refresh_one(account)
        if updated:
            new_token = str(updated.get("access_token") or "")
            old_token = str(account.get("access_token") or "")
            if new_token and new_token != old_token:
                # update_account() DA ho tro re-key qua updates["access_token"]
                # (services/account_service.py) va merge voi hang LIVE trong
                # _accounts (khong phai snapshot "account" cu chup truoc luc
                # goi mang refresh) - dung thang thay vi tu pop/normalize/
                # reinsert thu cong, tranh mat field doi song song trong luc
                # cho refresh network (notes sua tay, mark_image_result bump,
                # quota_watcher doi status...).
                result = account_service.update_account(old_token, updated)
                if result is not None:
                    _notify(f"✅ {label} — {email}\nKhôi phục xong ([T0] refresh token mới). Dùng lại bình thường.",
                            {**det, "step": "T0-refresh-ok"})
                    logger.info({"event": "recovery_ok", "email": email})
                    return new_token
    except Exception as exc:
        logger.warning({"event": "recovery_error", "email": email, "error": str(exc)[:150]})

    # Cùng lý do như nhánh thiếu refresh_token: còn tầng trình duyệt thì đây
    # CHƯA phải kết luận cuối, chỉ là một tầng trượt.
    if con_tang_trinh_duyet(email, group):
        _notify(f"🔧 {label} — {email}\n[T0] Refresh trượt ({reason}) — "
                f"chuyển sang đăng nhập lại bằng trình duyệt…",
                {**det, "step": "T0-refresh-failed-tiep-tuc", "reason": reason})
        return None
    _notify(f"❌ {label} — {email}\n[T0] Refresh THẤT BẠI ({reason}).\n"
            f"→ refresh_token có thể đã hết hạn, và không còn đường tự động nào "
            f"khác. Cần đăng nhập lại qua noVNC (`:6080`).",
            {**det, "step": "T0-refresh-failed", "reason": reason})
    return None
