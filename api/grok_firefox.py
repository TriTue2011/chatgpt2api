"""Tài khoản Grok — mỗi tài khoản một hồ sơ Firefox riêng, chỉ mở để đăng nhập / lấy cookie, xong thì tắt.

Chủ máy 01/10/2026: "các provider khác như nào thì grok cũng phải như vậy trên web ui" — nên Grok có danh sách tài
khoản có THỨ TỰ trong ``providers.grok_web.accounts`` (như Flow, Gemini Web API, Claude), thẻ Cài đặt, nhánh trang
Tài khoản. Khác các provider kia ở đường ĐĂNG NHẬP: grok.com chặn Chrome của captcha-solver trên máy này
(Cloudflare), nên mỗi tài khoản là một hồ sơ Firefox mở trên noVNC; người đăng nhập tay (Google hay email đều
được), thấy phiên sống thì cookie được ghi và Firefox tự tắt. Chat không dùng trình duyệt (`api/grok_web.py`).

Hồ sơ: ``data/grok_ho_so/<profile>/``, cookie: ``data/grok_ho_so/<profile>.cookies.json`` (0600). Hồ sơ cũ một
tài khoản (``data/grok_firefox`` + ``data/grok_web_cookies.json``) tự chuyển thành tài khoản đầu tiên.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_KHOA = threading.RLock()
_THEO_DOI: dict[str, threading.Thread] = {}
_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:153.0) Gecko/20100101 Firefox/153.0"
_TEN_RE = re.compile(r"grok-[a-z0-9_-]{1,40}")


def _log(event: str, **kw) -> None:
    try:
        from utils.log import logger
        logger.info({"event": event, **kw})
    except Exception:
        pass


def _data() -> Path:
    from services.config import DATA_DIR
    return Path(DATA_DIR)


def _goc() -> Path:
    return _data() / "grok_ho_so"


def ho_so(profile: str) -> Path:
    return _goc() / profile


def _nha() -> Path:
    return _data() / "grok_firefox_home"


def _file_cookie(profile: str) -> Path:
    return _goc() / f"{profile}.cookies.json"


def _firefox_bin() -> str:
    for ten in ("/usr/bin/firefox-esr", "/usr/bin/firefox"):
        if os.path.isfile(ten) and os.access(ten, os.X_OK):
            return ten
    raise RuntimeError("Máy này chưa có Firefox để đăng nhập Grok")


# ── Cấu hình tài khoản ──────────────────────────────────────────────────────
def _cfg() -> dict[str, Any]:
    from services.config import config
    c = (config.data.get("providers") or {}).get("grok_web")
    return c if isinstance(c, dict) else {}


def _luu_cfg(c: dict[str, Any]) -> None:
    from services.config import config
    providers = dict(config.data.get("providers") or {})
    providers["grok_web"] = c
    config.update({"providers": providers})


def tai_khoan() -> list[dict[str, Any]]:
    """Tài khoản theo thứ tự ưu tiên (đầu = Main)."""
    _di_tru_cu()
    return [dict(a) for a in _cfg().get("accounts") or [] if isinstance(a, dict) and a.get("profile")]


def dang_bat() -> list[dict[str, Any]]:
    c = _cfg()
    if c.get("enabled") is False:
        return []
    return [a for a in tai_khoan() if a.get("enabled") is not False]


def _sua_ds(sua) -> list[dict[str, Any]]:
    with _KHOA:
        c = dict(_cfg())
        ds = [dict(a) for a in c.get("accounts") or [] if isinstance(a, dict)]
        ds = sua(ds)
        c["accounts"] = ds
        c.setdefault("enabled", True)
        _luu_cfg(c)
        return ds


def them(label: str = "") -> dict[str, Any]:
    """Thêm một tài khoản trống (hồ sơ Firefox mới) — đăng nhập bằng `mo` sau đó."""
    ds = tai_khoan()
    co = {a["profile"] for a in ds}
    n = 1
    while f"grok-{n}" in co:
        n += 1
    nhan = str(label or "").strip()[:40] or ["Main", "Backup", "Spare 1", "Spare 2"][min(len(ds), 3)]
    moi = {"profile": f"grok-{n}", "label": nhan, "email": "", "enabled": True}
    _sua_ds(lambda d: d + [moi])
    _log("grok_tai_khoan_them", profile=moi["profile"])
    return moi


def _kiem_ten(profile: str) -> str:
    if not _TEN_RE.fullmatch(str(profile or "")):
        raise ValueError(f"Tài khoản Grok «{profile}» không hợp lệ.")
    if profile not in {a["profile"] for a in tai_khoan()}:
        raise ValueError(f"Không có tài khoản Grok «{profile}».")
    return profile


def bat_tat(profile: str, bat: bool) -> None:
    _kiem_ten(profile)
    _sua_ds(lambda d: [{**a, "enabled": bool(bat)} if a.get("profile") == profile else a for a in d])


def xoa(profile: str) -> None:
    """Gỡ khỏi danh sách và xoá hồ sơ + cookie của nó (đăng xuất hẳn khỏi máy)."""
    _kiem_ten(profile)
    tat(profile)
    _sua_ds(lambda d: [a for a in d if a.get("profile") != profile])
    if ho_so(profile).is_dir():
        shutil.rmtree(ho_so(profile))
    _file_cookie(profile).unlink(missing_ok=True)
    _log("grok_tai_khoan_xoa", profile=profile)


def doi_thu_tu(profiles: list[str]) -> None:
    ds = tai_khoan()
    if sorted(profiles) != sorted(a["profile"] for a in ds):
        raise ValueError("Thứ tự phải gồm đúng mọi tài khoản Grok hiện có.")
    theo = {a["profile"]: a for a in ds}
    _sua_ds(lambda d: [theo[p] for p in profiles])


def _di_tru_cu() -> None:
    """Hồ sơ cũ một tài khoản (`data/grok_firefox`, e99bafe) → tài khoản đầu tiên `grok-1`. Chỉ chạy khi cấu hình
    chưa có tài khoản nào và hồ sơ cũ có cookie — Firefox phải đang tắt (đổi chỗ hồ sơ đang mở là hỏng)."""
    cu, cookie_cu = _data() / "grok_firefox", _data() / "grok_web_cookies.json"
    if _cfg().get("accounts") or not (cu / "cookies.sqlite").is_file() or _pid_mo(cu):
        return
    with _KHOA:
        if _cfg().get("accounts"):
            return
        _goc().mkdir(parents=True, exist_ok=True)
        if not ho_so("grok-1").exists():
            shutil.move(str(cu), str(ho_so("grok-1")))
        if cookie_cu.is_file() and not _file_cookie("grok-1").exists():
            shutil.move(str(cookie_cu), str(_file_cookie("grok-1")))
        email = (thong_tin_phien(doc_cookie_file("grok-1")) or {}).get("email") or ""
        c = dict(_cfg())
        c.update(enabled=c.get("enabled", True),
                 accounts=[{"profile": "grok-1", "label": "Main", "email": email, "enabled": True}])
        _luu_cfg(c)
    _log("grok_di_tru_ho_so_cu", co_email=bool(email))


# ── Cookie và phiên ─────────────────────────────────────────────────────────
def doc_cookie_sqlite(profile_dir: Path) -> dict[str, str]:
    """Đọc cookie grok.com. Bỏ ``cf_chl_*``. Không ghi giá trị ra log."""
    src = profile_dir / "cookies.sqlite"
    if not src.is_file():
        return {}
    tmp = Path(f"/tmp/grok-ck-{os.getpid()}-{threading.get_ident()}.sqlite")
    for extra in ("", "-wal", "-shm"):
        goc = Path(str(src) + extra) if extra else src
        dich = Path(str(tmp) + extra) if extra else tmp
        if goc.is_file():
            shutil.copy2(goc, dich)
    try:
        con = sqlite3.connect(tmp)
        rows = con.execute(
            "SELECT host, name, value, lastAccessed FROM moz_cookies "
            "WHERE host LIKE '%grok.com%'"
        ).fetchall()
        con.close()
    except sqlite3.Error:
        return {}
    finally:
        for extra in ("", "-wal", "-shm"):
            dich = Path(str(tmp) + extra) if extra else tmp
            if dich.exists():
                dich.unlink()
    best: dict[str, tuple[int, str]] = {}
    for _host, name, value, accessed in rows:
        if not name or not value:
            continue
        if str(name).startswith("cf_") and name != "cf_clearance":
            continue
        prev = best.get(str(name))
        if prev is None or int(accessed or 0) >= prev[0]:
            best[str(name)] = (int(accessed or 0), str(value))
    return {name: pair[1] for name, pair in best.items()}


def ghi_cookie(profile: str, cookies: dict[str, str]) -> None:
    if not cookies.get("sso"):
        return
    path = _file_cookie(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False)
    os.chmod(path, 0o600)
    _log("grok_firefox_thu_hoach", profile=profile, so_cookie=len(cookies), co_clearance="cf_clearance" in cookies)


def doc_cookie_file(profile: str) -> dict[str, str]:
    path = _file_cookie(profile)
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v}


def thong_tin_phien(cookies: dict[str, str]) -> dict[str, str] | None:
    """GET /api/auth/session: {"email"} khi phiên sống, None khi không. Không trả user id ra ngoài."""
    if not cookies.get("sso"):
        return None
    jar = "; ".join(f"{k}={v}" for k, v in cookies.items())
    req = urllib.request.Request("https://grok.com/api/auth/session", headers={
        "Cookie": jar,
        "User-Agent": _UA,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    sess = data.get("session") if isinstance(data, dict) else None
    if not isinstance(sess, dict) or str(data.get("status") or "") != "authenticated" or not sess.get("userId"):
        return None
    user = sess.get("user") if isinstance(sess.get("user"), dict) else {}
    return {"email": str(user.get("email") or sess.get("email") or "")}


def phien_song(cookies: dict[str, str]) -> bool:
    return thong_tin_phien(cookies) is not None


# ── Hạn mức lượt hỏi ────────────────────────────────────────────────────────
#: Hạn mức đọc từ `POST /rest/rate-limits` theo modelName. Đo 02/10/2026 tài khoản miễn phí: grok-3 (= mode fast)
#: 30 lượt / 86.400 s, grok-4 7 lượt / 86.400 s. Gói trả phí có cửa sổ khác (giờ, tuần) — hiện theo đúng
#: `windowSizeSeconds` máy chủ trả, kèm hạn mức con `lowEffortRateLimits` / `highEffortRateLimits` nếu có.
_HAN_MUC_MODEL = {"grok-3": "Fast", "grok-4": "Grok 4"}
_HAN_MUC_GIAY = 300
_han_muc: dict[str, dict[str, Any]] = {}
_han_muc_dang: set[str] = set()


def _mot_han_muc(ten: str, d: Any, luc: float) -> dict[str, Any] | None:
    if not isinstance(d, dict) or "remainingQueries" not in d:
        return None
    cho = d.get("waitTimeSeconds")
    return {"ten": ten, "con": int(d.get("remainingQueries") or 0), "tong": int(d.get("totalQueries") or 0),
            "cua_so": int(d.get("windowSizeSeconds") or 0),
            "hoi_luc": luc + float(cho) if isinstance(cho, (int, float)) and cho > 0 else None}


def han_muc(cookies: dict[str, str]) -> list[dict[str, Any]]:
    """Lượt còn / tổng, độ dài cửa sổ và lúc hồi — mỗi model một mục (cộng hạn mức con nếu gói có)."""
    jar = "; ".join(f"{k}={v}" for k, v in cookies.items())
    ra: list[dict[str, Any]] = []
    for model, ten in _HAN_MUC_MODEL.items():
        req = urllib.request.Request(
            "https://grok.com/rest/rate-limits", method="POST",
            data=json.dumps({"requestKind": "DEFAULT", "modelName": model}).encode(),
            headers={"Content-Type": "application/json", "Cookie": jar, "Origin": "https://grok.com",
                     "Referer": "https://grok.com/", "User-Agent": _UA})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                d = json.loads(resp.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            continue
        luc = time.time()
        for khoa, them in (("", ""), ("lowEffortRateLimits", " · nhẹ"), ("highEffortRateLimits", " · nặng")):
            m = _mot_han_muc(ten + them, d.get(khoa) if khoa else d, luc)
            if m:
                ra.append(m)
    return ra


def _lay_han_muc(profile: str) -> None:
    try:
        ds = han_muc(doc_cookie_file(profile))
        if ds:
            _han_muc[profile] = {"luc": time.time(), "ds": ds}
    except Exception as exc:  # noqa: BLE001 — không đọc được hạn mức thì web chỉ thiếu dòng hạn mức
        _log("grok_han_muc_loi", profile=profile, loi=str(exc)[:160])
    finally:
        _han_muc_dang.discard(profile)


def han_muc_cua(profile: str, *, cho: bool) -> dict[str, Any] | None:
    """Bản lưu tạm ≤ 5 phút. ``cho``: cũ thì hỏi grok.com ngay; không thì trả bản cũ và làm mới chạy nền
    (cây tài khoản phải tải nhanh)."""
    cu = _han_muc.get(profile)
    if cu and time.time() - cu["luc"] < _HAN_MUC_GIAY:
        return cu
    if cho:
        _lay_han_muc(profile)
        return _han_muc.get(profile)
    with _KHOA:
        if profile not in _han_muc_dang:
            _han_muc_dang.add(profile)
            threading.Thread(target=_lay_han_muc, args=(profile,), name=f"grok-han-muc-{profile}", daemon=True).start()
    return cu


# ── Firefox ─────────────────────────────────────────────────────────────────
def _pid_mo(profile_dir: Path) -> int | None:
    kim = f"--profile {profile_dir} "
    for ten in os.listdir("/proc"):
        if not ten.isdigit():
            continue
        try:
            cmd = open(f"/proc/{ten}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if "firefox" in cmd and kim in cmd + " ":
            return int(ten)
    return None


def _tat_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(40):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            _log("grok_firefox_tat", pid=pid)
            return
        time.sleep(0.25)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    _log("grok_firefox_tat", pid=pid)


def dang_mo(profile: str) -> bool:
    return _pid_mo(ho_so(profile)) is not None


def tat(profile: str | None = None) -> None:
    for p in ([profile] if profile else [a["profile"] for a in tai_khoan()]):
        pid = _pid_mo(ho_so(p))
        if pid:
            _tat_pid(pid)


def mo(profile: str) -> int:
    """Mở grok.com bằng hồ sơ của tài khoản trên màn hình noVNC. Đã mở thì không mở thêm."""
    thu_muc = ho_so(profile)
    san = _pid_mo(thu_muc)
    if san:
        return san
    thu_muc.mkdir(parents=True, exist_ok=True)
    _nha().mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["DISPLAY"] = env.get("DISPLAY") or ":99"
    env["MOZ_DISABLE_CONTENT_SANDBOX"] = "1"
    env["MOZ_DISABLE_GMP_SANDBOX"] = "1"
    env["HOME"] = str(_nha())
    proc = subprocess.Popen(
        [_firefox_bin(), "--no-remote", "--new-instance", "--profile", str(thu_muc), "https://grok.com/"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    _log("grok_firefox_mo", profile=profile, pid=proc.pid)
    return proc.pid


def _thu_tu_sqlite(profile: str) -> dict[str, str]:
    """Cookie trong hồ sơ còn phiên sống thì ghi file, cập nhật email của tài khoản, trả cookie."""
    cookies = doc_cookie_sqlite(ho_so(profile))
    tt = thong_tin_phien(cookies) if cookies.get("sso") else None
    if tt is None:
        return {}
    ghi_cookie(profile, cookies)
    if tt.get("email"):
        _sua_ds(lambda d: [{**a, "email": tt["email"]} if a.get("profile") == profile else a for a in d])
    return cookies


def dang_nhap(profile: str) -> dict[str, Any]:
    """Nút «Đăng nhập» trên web: mở Firefox của tài khoản trên noVNC rồi canh — phiên sống thì ghi cookie, tắt."""
    _kiem_ten(profile)
    pid = mo(profile)
    _bat_theo_doi(profile)
    return {"pid": pid, "profile": profile}


def lam_moi(profile: str, cho: float = 90) -> dict[str, str]:
    """Cookie file còn sống thì tắt Firefox cho đỡ tốn. Hết hạn thì mở lại đúng hồ sơ — còn đăng nhập thì grok.com
    tự cấp phiên mới, không gõ mật khẩu."""
    with _KHOA:
        san = doc_cookie_file(profile)
        if san.get("sso") and phien_song(san):
            tat(profile)
            return san
        if not (ho_so(profile) / "cookies.sqlite").is_file():
            raise RuntimeError(f"Tài khoản Grok {profile} chưa đăng nhập. Bấm «Đăng nhập» ở Cài đặt › Grok.")
        mo(profile)
        het = time.time() + cho
        while time.time() < het:
            cookies = _thu_tu_sqlite(profile)
            if cookies.get("sso"):
                tat(profile)
                return cookies
            time.sleep(3)
    _bat_theo_doi(profile)
    raise RuntimeError(f"Phiên Grok {profile} chưa tự mới — Firefox đang mở trên noVNC, đăng nhập lại là xong.")


def _vong_theo_doi(profile: str) -> None:
    """Người đang đăng nhập: thấy phiên sống thì ghi cookie và tắt Firefox. Firefox bị đóng tay thì thôi."""
    het = time.time() + 15 * 60
    while time.time() < het and dang_mo(profile):
        if _thu_tu_sqlite(profile).get("sso"):
            tat(profile)
            return
        time.sleep(3)


def _bat_theo_doi(profile: str) -> None:
    with _KHOA:
        t = _THEO_DOI.get(profile)
        if t is not None and t.is_alive():
            return
        t = threading.Thread(target=_vong_theo_doi, args=(profile,), name=f"grok-firefox-{profile}", daemon=True)
        _THEO_DOI[profile] = t
        t.start()


def trang_thai(kiem_phien: bool = True) -> list[dict[str, Any]]:
    """Cho web: từng tài khoản kèm phiên còn sống không (``kiem_phien`` — gọi grok.com, tới 20 giây mỗi tài khoản;
    cây tài khoản tắt đi cho nhanh, khi đó ``phien_song`` là None), Firefox đang mở không, cookie ghi lúc nào."""
    ra = []
    for i, a in enumerate(tai_khoan()):
        p = a["profile"]
        f = _file_cookie(p)
        ra.append({**a, "ordinal": i + 1, "is_primary": i == 0,
                   "phien_song": phien_song(doc_cookie_file(p)) if kiem_phien else None,
                   "da_dang_nhap": (ho_so(p) / "cookies.sqlite").is_file(),
                   "firefox_mo": dang_mo(p),
                   "cookie_luc": f.stat().st_mtime if f.is_file() else None,
                   "han_muc": han_muc_cua(p, cho=kiem_phien) if a.get("enabled", True) else None})
    return ra


def chuan_bi() -> None:
    """Lúc mở app: chuyển hồ sơ cũ; tài khoản nào phiên còn sống mà Firefox đang mở thì tắt."""
    try:
        for a in tai_khoan():
            p = a["profile"]
            if dang_mo(p):
                if phien_song(doc_cookie_file(p)):
                    tat(p)
                else:
                    _bat_theo_doi(p)
    except Exception as exc:
        _log("grok_firefox_chuan_bi_loi", loi=str(exc)[:160])


def start() -> None:
    threading.Thread(target=chuan_bi, name="grok-firefox-start", daemon=True).start()
