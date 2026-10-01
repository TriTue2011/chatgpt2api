"""Firefox của riêng Grok — chỉ mở để lấy cookie, xong thì tắt.

Chat không dùng trình duyệt. Hồ sơ nằm trên ổ dữ liệu
(``data/grok_firefox``), không nằm trong ``/tmp``, nên lần sau mở lại vẫn
còn đăng nhập. ``cf_clearance`` hết hạn thì mở đúng hồ sơ đó, đợi grok.com
nhận phiên, ghi cookie, rồi tắt. Không gõ lại mật khẩu, không dùng Chrome
của captcha-solver.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

_HO_SO_TAM = Path("/tmp/ff-grok-hand")
_KHOA = threading.Lock()
_THEO_DOI: threading.Thread | None = None
_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:153.0) Gecko/20100101 Firefox/153.0"


def _log(event: str, **kw) -> None:
    try:
        from utils.log import logger
        logger.info({"event": event, **kw})
    except Exception:
        pass


def _data():
    from services.config import DATA_DIR
    return DATA_DIR


def ho_so() -> Path:
    return _data() / "grok_firefox"


def _nha() -> Path:
    return _data() / "grok_firefox_home"


def _file_cookie() -> Path:
    return _data() / "grok_web_cookies.json"


def _firefox_bin() -> str:
    for ten in ("/usr/bin/firefox-esr", "/usr/bin/firefox"):
        if os.path.isfile(ten) and os.access(ten, os.X_OK):
            return ten
    raise RuntimeError("Máy này chưa có Firefox để mở lại phiên Grok")


def doc_cookie_sqlite(profile: Path) -> dict[str, str]:
    """Đọc cookie grok.com. Bỏ ``cf_chl_*``. Không ghi giá trị ra log."""
    src = profile / "cookies.sqlite"
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


def ghi_cookie(cookies: dict[str, str]) -> None:
    if not cookies.get("sso"):
        return
    path = _file_cookie()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False)
    os.chmod(path, 0o600)
    _log("grok_firefox_thu_hoach", so_cookie=len(cookies), co_clearance="cf_clearance" in cookies)


def doc_cookie_file() -> dict[str, str]:
    path = _file_cookie()
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v}


def phien_song(cookies: dict[str, str]) -> bool:
    """GET /api/auth/session. Chỉ trả có/không, không trả user id."""
    if not cookies.get("sso"):
        return False
    jar = "; ".join(f"{k}={v}" for k, v in cookies.items())
    req = urllib.request.Request("https://grok.com/api/auth/session", headers={
        "Cookie": jar,
        "User-Agent": _UA,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False
    sess = data.get("session") if isinstance(data, dict) else None
    if not isinstance(sess, dict):
        return False
    return str(data.get("status") or "") == "authenticated" and bool(sess.get("userId"))


def _pid_mo(profile: Path) -> int | None:
    kim = str(profile)
    for ten in os.listdir("/proc"):
        if not ten.isdigit():
            continue
        try:
            cmd = open(f"/proc/{ten}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if "firefox" in cmd and kim in cmd and "--profile" in cmd:
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


def tat() -> None:
    for profile in (ho_so(), _HO_SO_TAM):
        pid = _pid_mo(profile)
        if pid:
            _tat_pid(pid)


def _copy_ho_so(src: Path, dst: Path) -> None:
    if dst.exists() or not src.is_dir():
        return
    bo = shutil.ignore_patterns(
        "cache2", "startupCache", "shader-cache", "thumbnails",
        "crashes", "minidumps", "lock", "parent.lock", ".parentlock",
    )
    shutil.copytree(src, dst, ignore=bo)
    _log("grok_firefox_giu_ho_so", tu=str(src))


def _ho_so_mo() -> Path:
    """Hồ sơ đã có cookie. Chưa copy sang ổ dữ liệu thì vẫn dùng hồ sơ tạm."""
    if (ho_so() / "cookies.sqlite").is_file():
        return ho_so()
    if (_HO_SO_TAM / "cookies.sqlite").is_file():
        return _HO_SO_TAM
    ho_so().mkdir(parents=True, exist_ok=True)
    return ho_so()


def mo() -> int:
    """Mở grok.com bằng hồ sơ đã lưu. Trả pid. Đã mở thì không mở thêm."""
    profile = _ho_so_mo()
    san = _pid_mo(profile)
    if san:
        return san
    profile.mkdir(parents=True, exist_ok=True)
    _nha().mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["DISPLAY"] = env.get("DISPLAY") or ":99"
    env["MOZ_DISABLE_CONTENT_SANDBOX"] = "1"
    env["MOZ_DISABLE_GMP_SANDBOX"] = "1"
    env["HOME"] = str(_nha())
    proc = subprocess.Popen(
        [_firefox_bin(), "--no-remote", "--new-instance", "--profile", str(profile), "https://grok.com/"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    _log("grok_firefox_mo", pid=proc.pid)
    return proc.pid


def _thu_tu_sqlite(profile: Path) -> dict[str, str]:
    cookies = doc_cookie_sqlite(profile)
    if cookies.get("sso") and phien_song(cookies):
        ghi_cookie(cookies)
        return cookies
    return {}


def lam_moi(cho: float = 90) -> dict[str, str]:
    """Cookie file còn sống thì tắt Firefox cho đỡ tốn. Hết hạn thì mở hồ sơ cũ."""
    with _KHOA:
        return _lam_moi(cho)


def _lam_moi(cho: float) -> dict[str, str]:
    _chuyen_ho_so_tam()
    san = doc_cookie_file()
    if san.get("sso") and phien_song(san):
        tat()
        return san
    if not (ho_so() / "cookies.sqlite").is_file() and not (_HO_SO_TAM / "cookies.sqlite").is_file():
        raise RuntimeError(
            "Chưa có hồ sơ Firefox của Grok trên ổ dữ liệu. "
            "Đăng nhập một lần trên noVNC của máy này.")
    mo()
    het = time.time() + cho
    while time.time() < het:
        cookies = _thu_tu_sqlite(_ho_so_mo())
        if cookies.get("sso"):
            _chuyen_ho_so_tam()
            tat()
            return cookies
        time.sleep(3)
    _bat_theo_doi()
    raise RuntimeError(
        "Phiên Grok chưa tự mới. Firefox đang mở trên noVNC của máy này. "
        "Đăng nhập xong thì cookie được ghi và Firefox tự tắt.")


def _chuyen_ho_so_tam() -> None:
    """Đưa hồ sơ /tmp sang ổ dữ liệu sau khi Firefox đã đóng, để còn đăng nhập."""
    if ho_so().is_dir() or not _HO_SO_TAM.is_dir():
        return
    pid = _pid_mo(_HO_SO_TAM)
    if pid:
        cookies = _thu_tu_sqlite(_HO_SO_TAM)
        if not cookies.get("sso"):
            return
        _tat_pid(pid)
        time.sleep(1)
    _copy_ho_so(_HO_SO_TAM, ho_so())


def _vong_theo_doi() -> None:
    """Người đang đăng nhập: thấy phiên sống thì ghi cookie và tắt Firefox."""
    het = time.time() + 15 * 60
    while time.time() < het:
        for profile in (ho_so(), _HO_SO_TAM):
            if _pid_mo(profile) is None:
                continue
            cookies = _thu_tu_sqlite(profile)
            if cookies.get("sso"):
                _chuyen_ho_so_tam()
                tat()
                return
        time.sleep(3)


def _bat_theo_doi() -> None:
    global _THEO_DOI
    if _THEO_DOI is not None and _THEO_DOI.is_alive():
        return
    _THEO_DOI = threading.Thread(target=_vong_theo_doi, name="grok-firefox", daemon=True)
    _THEO_DOI.start()


def chuan_bi() -> None:
    """Lúc mở app: phiên đã sống thì tắt Firefox. Chưa có cookie thì mở hồ sơ cũ."""
    try:
        with _KHOA:
            _chuyen_ho_so_tam()
            san = doc_cookie_file()
            dang_mo = _pid_mo(ho_so()) or _pid_mo(_HO_SO_TAM)
            if san.get("sso") and phien_song(san):
                if dang_mo:
                    tat()
                return
            if dang_mo:
                _bat_theo_doi()
                return
            if ho_so().is_dir():
                _lam_moi(90)
    except Exception as exc:
        _log("grok_firefox_chuan_bi_loi", loi=str(exc)[:160])


def start() -> None:
    threading.Thread(target=chuan_bi, name="grok-firefox-start", daemon=True).start()
