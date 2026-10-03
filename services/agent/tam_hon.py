"""Tâm hồn của bot — cảm xúc và viết/vẽ từ chuyện THẬT trong nhà.

Chủ máy 02/10/2026: *"Train cho bot có cảm xúc"*, *"Là nhà văn, nhà thơ"*, *"Train cho
nó tự vẽ tranh, làm thơ"*; chọn «Tự viết & vẽ chủ động» (03/10: chỉ còn thơ ngắn + tâm sự, bỏ tranh) + «Cảm xúc trong lời trò
chuyện», nhịp «Khi có chuyện đáng viết»; và *"cần có tích kích hoạt, không để bot tự
chủ"* — nên CẢ HAI phần mặc định TẮT, chỉ chạy khi chủ máy tích trên web.

Vai giáo viên: code chỉ gom nguyên liệu thật (camera nhận ra ai về lúc nào, lời người
nhà nhắn, thời tiết) và chặn ở biên (≤ ``TOI_DA_BAI_NGAY`` bài/ngày, giờ yên, độ dài).
Cảm gì, có đáng viết không, viết ra sao là việc của bot theo hướng dẫn
``services/huong_dan_hoc/tam_hon.md`` — không có danh sách từ khoá cảm xúc nào ở đây.

Bài viết đi qua sổ thông báo ``bot.tam_hon`` (chủ máy chọn kênh ở Cài đặt › Thông báo).

Ba phần thêm sau khi so với bản thiết kế «Tiểu Vy» (chủ máy duyệt 02/10/2026):

- **Ký ức cảm xúc** (``ky_uc``): mỗi lượt cảm, bot tự chọn có điều gì đáng nhớ lâu không; có thì
  lưu một câu kèm cảm xúc, nhúng bằng model nhà (``services/nhung.py``, GPU .220 — ký ức không đi
  ra ngoài). Lúc cảm và lúc trò chuyện, bot được gợi lại vài ký ức gần nghĩa nhất; dùng hay bỏ là
  việc của model, không có ngưỡng điểm nào ở đây.
- **Gốc** (``goc``): bot là ai trong nhà, gọi ai thế nào — CHỈ chủ máy sửa trên web; không tool
  nào của bot ghi được.
- **Nghĩ lại sau trò chuyện**: người nhà nhắn xong, im ``IM_SAU_CHAT_GIAY`` thì cảm một lượt,
  không phải chờ nhịp ``GIAN_CACH_GIAY``.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from utils.log import logger

_PATH = Path(DATA_DIR) / "agent" / "tam_hon.json"
_DB = Path(DATA_DIR) / "agent" / "tam_hon.sqlite"
_khoa = threading.Lock()
_dang_chay = threading.Lock()

TOI_DA_BAI_NGAY = 2
#: Thể «tâm sự ngắn» (chủ máy 03/10/2026, như bot Tiểu Vy): 1–3 câu, không tranh. Chặn ở biên.
TAM_SU_TOI_DA = 400
#: Thơ NGẮN (chủ máy 03/10/2026: "thơ ngắn, không dài … vẽ tranh thì thôi, nếu cần thì tôi yêu cầu"): ≤ 6 câu.
#: Nhật ký và tranh đã BỎ — vẽ khi chủ máy tự yêu cầu (tool generate_image).
THO_TOI_DA_CAU = 6
THO_TOI_DA = 500
#: Hai lượt cảm cách nhau ít nhất chừng này — mỗi lượt là một lời gọi model.
GIAN_CACH_GIAY = 90 * 60
#: Người nhà nhắn xong, im chừng này thì bot nghĩ lại — nhưng hai lượt vẫn cách nhau ≥ ``GIAN_CACH_TOI_THIEU``.
IM_SAU_CHAT_GIAY = 20 * 60
GIAN_CACH_TOI_THIEU = 30 * 60
#: Ký ức gợi lại mỗi lần; gốc tối đa bao nhiêu chữ.
SO_KY_UC = 3
GOC_TOI_DA = 1500
#: Ngoài khung này là giờ yên: không cảm, không gửi bài.
GIO_THUC = (6, 23)
#: Tâm trạng cũ hơn chừng này thì không bơm vào lời trò chuyện nữa.
TAM_TRANG_SONG_GIAY = 8 * 3600
#: Kênh người nhà trò chuyện (`run_journal._channel_of`); ha/web/openapi là máy hỏi.
_KENH_NGUOI = ("zalop", "zalo", "tg")


def _nap() -> dict[str, Any]:
    try:
        d = json.loads(_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _luu(d: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_PATH)


def cai_dat() -> dict[str, Any]:
    d = _nap()
    return {"bat_viet": bool(d.get("bat_viet")), "bat_cam_xuc": bool(d.get("bat_cam_xuc")),
            "goc": str(d.get("goc") or "")}


def dat(*, bat_viet: bool | None = None, bat_cam_xuc: bool | None = None,
        goc: str | None = None) -> dict[str, Any]:
    """Chỉ API web của chủ máy gọi hàm này — bot không có tool nào ghi được ``goc``."""
    with _khoa:
        d = _nap()
        if bat_viet is not None:
            d["bat_viet"] = bool(bat_viet)
        if bat_cam_xuc is not None:
            d["bat_cam_xuc"] = bool(bat_cam_xuc)
        if goc is not None:
            d["goc"] = str(goc).strip()[:GOC_TOI_DA]
        _luu(d)
    return cai_dat()


def trang_thai() -> dict[str, Any]:
    d = _nap()
    return {**cai_dat(), "tam_trang": d.get("tam_trang") or {}, "bai": list(d.get("bai") or [])[-10:],
            "lan_xet": d.get("lan_xet") or 0, "ky_uc": ky_uc_gan(20)}


# ── Ký ức cảm xúc ────────────────────────────────────────────────────────────

def _ket_noi() -> sqlite3.Connection:
    """Mỗi lần dùng một kết nối, đóng ngay (``closing``) — gọi từ luồng chat và luồng heartbeat."""
    _DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(_DB, timeout=10)
    c.execute("CREATE TABLE IF NOT EXISTS ky_uc (id INTEGER PRIMARY KEY, luc REAL, noi_dung TEXT, "
              "cam_xuc TEXT, cuong_do INTEGER, vec BLOB)")
    return c


def _sql(cau: str, tham: tuple = (), *, nhieu: list | None = None) -> tuple[list, int]:
    """(các dòng đọc được, số dòng đổi)."""
    with closing(_ket_noi()) as c, c:
        cur = c.executemany(cau, nhieu) if nhieu is not None else c.execute(cau, tham)
        return cur.fetchall(), cur.rowcount


def _vec(chu: str):
    try:
        from services import nhung
        return nhung.vec(chu)
    except Exception as exc:  # noqa: BLE001 — model nhúng hỏng thì không gợi lại được, không hỏng lượt
        logger.info({"event": "tam_hon_nhung_hong", "loi": str(exc)[:120]})
        return None


def ghi_ky_uc(noi_dung: str, cam_xuc: str, cuong_do: int, luc: float) -> None:
    v = _vec(noi_dung)
    _sql("INSERT INTO ky_uc (luc, noi_dung, cam_xuc, cuong_do, vec) VALUES (?,?,?,?,?)",
         (luc, noi_dung, cam_xuc, cuong_do, None if v is None else v.tobytes()))


def ky_uc_gan(n: int = 20) -> list[dict[str, Any]]:
    rows, _ = _sql("SELECT id, luc, noi_dung, cam_xuc, cuong_do FROM ky_uc ORDER BY luc DESC LIMIT ?", (int(n),))
    return [{"id": r[0], "luc": r[1], "noi_dung": r[2], "cam_xuc": r[3], "cuong_do": r[4]} for r in rows]


def xoa_ky_uc(id_: int) -> bool:
    return _sql("DELETE FROM ky_uc WHERE id = ?", (int(id_),))[1] > 0


def goi_lai(chu: str, k: int = SO_KY_UC) -> list[dict[str, Any]]:
    """``k`` ký ức gần nghĩa ``chu`` nhất. Không đặt ngưỡng: model đọc rồi tự bỏ cái không hợp.
    Ký ức lưu lúc model nhúng chưa sẵn (vec rỗng) được nhúng bù ở đây."""
    import numpy as np

    chu = str(chu or "").strip()
    if not chu:
        return []
    rows, _ = _sql("SELECT id, luc, noi_dung, cam_xuc, vec FROM ky_uc")
    if not rows:
        return []
    q = _vec(chu)
    if q is None:
        return []
    ds, bu = [], []
    for id_, luc, nd, cx, b in rows:
        if b is None:
            v = _vec(nd)
            if v is None:
                continue
            bu.append((v.tobytes(), id_))
        else:
            v = np.frombuffer(b, dtype=np.float32)
        if v.shape == q.shape:
            ds.append((float(v @ q), {"id": id_, "luc": luc, "noi_dung": nd, "cam_xuc": cx}))
    if bu:
        _sql("UPDATE ky_uc SET vec = ? WHERE id = ?", nhieu=bu)
    ds.sort(key=lambda x: -x[0])
    return [x[1] for x in ds[:k]]


def _dong_ky_uc(ds: list[dict[str, Any]]) -> list[str]:
    return [f"   {time.strftime('%d/%m/%Y', time.localtime(m['luc']))}: {m['noi_dung']} (em thấy {m['cam_xuc']})"
            for m in ds]


# ── Nguyên liệu ──────────────────────────────────────────────────────────────

def _gio(ts: float) -> str:
    return time.strftime("%H:%M", time.localtime(ts))


def thoi_tiet() -> list[str]:
    try:
        from services import ha_client
        st = ha_client.get_states()
    except Exception as exc:  # noqa: BLE001 — HA hỏng thì bài thiếu thời tiết, không hỏng
        logger.info({"event": "tam_hon_khong_doc_thoi_tiet", "loi": str(exc)[:120]})
        return []
    ra = []
    for s in st:
        if not str(s.get("entity_id") or "").startswith("weather."):
            continue
        a = s.get("attributes") or {}
        ra.append(f"{a.get('friendly_name') or s['entity_id']}: {s.get('state')}, "
                  f"{a.get('temperature')}°, ẩm {a.get('humidity')}%")
    return ra[:4]


def nguoi_ra_vao(tu: float) -> list[str]:
    """Camera nhận ra người nhà — một dòng mỗi người mỗi 30 phút (camera báo dồn dập)."""
    try:
        from services import so_mat_nha
        ds = so_mat_nha.su_kien_gan((time.time() - tu) / 3600, gioi_han=300)
    except Exception as exc:  # noqa: BLE001
        logger.info({"event": "tam_hon_khong_doc_mat", "loi": str(exc)[:120]})
        return []
    ra, cuoi = [], {}
    for e in sorted(ds, key=lambda x: x["ts"]):
        ten = str(e.get("ten") or "").strip()
        if e.get("loai") not in ("quen", "co_the") or not ten:
            continue
        if e["ts"] - cuoi.get(ten, 0) < 1800:
            continue
        cuoi[ten] = e["ts"]
        ra.append(f"{_gio(e['ts'])} {e.get('camera')} thấy: {ten}")
    return ra[-20:]


def _runs_nguoi(moi_kenh: int) -> list[dict[str, Any]]:
    """Lượt chat của người nhà, mới nhất trước. Đọc theo TỪNG kênh: HA một mình ~200 lượt/ngày
    (đo 02/10/2026: ha 196, web 47, zalop 20) — đọc chung 200 dòng mới nhất là mất tin người nhà."""
    from services.agent import run_journal
    rows = [r for k in _KENH_NGUOI for r in run_journal.list_runs(limit=moi_kenh, channel=k)]
    return sorted(rows, key=lambda r: -float(r.get("created_at") or 0))


def loi_nhan(tu: float) -> list[str]:
    try:
        rows = _runs_nguoi(50)
    except Exception as exc:  # noqa: BLE001
        logger.info({"event": "tam_hon_khong_doc_runs", "loi": str(exc)[:120]})
        return []
    ra = []
    for r in rows:
        chu = " ".join(str(r.get("user_text") or "").split())
        if float(r.get("created_at") or 0) >= tu and chu:
            dap = " ".join(str(r.get("reply_text") or "").split())[:100]
            ra.append(f"{_gio(float(r['created_at']))} {chu[:160]}" + (f" → em: {dap}" if dap else ""))
    return list(reversed(ra[:15]))


def _chat_cuoi() -> float:
    """Lúc người nhà nhắn gần nhất (0 nếu không đọc được)."""
    try:
        return max((float(r.get("created_at") or 0) for r in _runs_nguoi(1)), default=0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def de(now: float, tu: float, *, duoc_viet: bool) -> tuple[str, bool]:
    """(đề, có nguyên liệu mới kể từ lượt trước)."""
    d = _nap()
    lan_xet = float(d.get("lan_xet") or 0)
    nguoi, nhan = nguoi_ra_vao(tu), loi_nhan(tu)
    moi = any(_ts_dong(x, now) > lan_xet for x in nguoi + nhan)
    mua = {12: "đông", 1: "đông", 2: "xuân", 3: "xuân", 4: "xuân", 5: "hạ", 6: "hạ", 7: "hạ",
           8: "thu", 9: "thu", 10: "thu", 11: "đông"}[time.localtime(now).tm_mon]
    tt = d.get("tam_trang") or {}
    bai = list(d.get("bai") or [])[-5:]
    cu = goi_lai("\n".join(nhan[-5:] + nguoi[-3:])) if (nguoi or nhan) else []
    phan = [
        "A. Bây giờ: " + time.strftime("%A %d/%m/%Y %H:%M", time.localtime(now)) + f", mùa {mua}",
        *[f"   {x}" for x in thoi_tiet()],
        "B. Người nhà ra vào (từ " + _gio(tu) + "):", *([f"   {x}" for x in nguoi] or ["   (không có)"]),
        "C. Lời nhắn trong nhà:", *([f"   {x}" for x in nhan] or ["   (không có)"]),
        "D. Em mấy hôm nay:",
        f"   tâm trạng trước: {tt.get('cam_xuc', 'bình thường')} — {tt.get('vi_sao', '')}".rstrip(" —"),
        *[f"   đã viết {time.strftime('%d/%m %H:%M', time.localtime(b['luc']))}: {b.get('tieu_de', '')} — "
          f"{str(b.get('noi_dung', ''))[:80]}" for b in bai],
        *(["E. Ký ức cũ em gợi lại được (chỉ dùng nếu thật sự liên quan):", *_dong_ky_uc(cu)] if cu else []),
        "" if duoc_viet else "Lần này: chỉ cảm, không viết.",
    ]
    return "\n".join(p for p in phan if p is not None).strip(), moi


def _ts_dong(dong: str, now: float) -> float:
    """Dòng bắt đầu bằng HH:MM của hôm nay (hoặc hôm qua nếu giờ ấy chưa tới)."""
    try:
        h, m = int(dong[:2]), int(dong[3:5])
    except ValueError:
        return 0.0
    lt = time.localtime(now)
    ts = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, m, 0, 0, 0, -1))
    return ts - 86400 if ts > now + 60 else ts


# ── Lượt cảm ─────────────────────────────────────────────────────────────────

def bai_hom_nay(now: float | None = None) -> int:
    hom = time.strftime("%Y-%m-%d", time.localtime(now or time.time()))
    return sum(1 for b in _nap().get("bai") or []
               if time.strftime("%Y-%m-%d", time.localtime(b.get("luc", 0))) == hom)


def nen_chay(now: float | None = None) -> tuple[bool, str]:
    now = now or time.time()
    c = cai_dat()
    if not (c["bat_viet"] or c["bat_cam_xuc"]):
        return False, "chưa tích kích hoạt (Cài đặt › Tâm hồn của bot)"
    gio = time.localtime(now).tm_hour
    if not GIO_THUC[0] <= gio < GIO_THUC[1]:
        return False, "giờ yên"
    lan_xet = float(_nap().get("lan_xet") or 0)
    if now - lan_xet < GIAN_CACH_TOI_THIEU:
        return False, "vừa cảm xong"
    cuoi = _chat_cuoi()
    if cuoi > lan_xet:
        if now - cuoi >= IM_SAU_CHAT_GIAY:
            return True, "nghĩ lại sau cuộc trò chuyện"
        return False, "người nhà đang nhắn — chờ im rồi nghĩ lại"
    if now - lan_xet < GIAN_CACH_GIAY:
        return False, "vừa cảm xong"
    return True, ""


def _kiem(data: Any) -> dict[str, Any] | None:
    """Chặn ở biên: model trả gì cũng chỉ lấy đúng các trường, đúng độ dài."""
    if not isinstance(data, dict):
        return None
    cam = " ".join(str(data.get("cam_xuc") or "").split())[:40]
    if not cam:
        return None
    try:
        cd = max(1, min(5, int(data.get("cuong_do") or 2)))
    except (TypeError, ValueError):
        cd = 2
    ra = {"cam_xuc": cam, "cuong_do": cd, "vi_sao": " ".join(str(data.get("vi_sao") or "").split())[:240].rstrip(" ."),
          "ky_uc": " ".join(str(data.get("ky_uc") or "").split())[:300], "viet": False}
    nd = str(data.get("noi_dung") or "").strip()
    loai = str(data.get("the_loai") or "")
    if data.get("viet") is True and loai == "tam_su":
        # Tâm sự: chỉ lời nhắn ngắn — không tiêu đề, không tranh; dài quá là model sai khuôn, không đăng.
        if 10 <= len(nd) <= TAM_SU_TOI_DA:
            ra.update(viet=True, noi_dung=" ".join(nd.split()), the_loai="tam_su", tieu_de="")
    elif data.get("viet") is True and loai == "tho":
        cau = [d.strip() for d in nd.splitlines() if d.strip()]
        if 2 <= len(cau) <= THO_TOI_DA_CAU and len(nd) <= THO_TOI_DA:    # dài là sai khuôn — không đăng
            ra.update(viet=True, noi_dung="\n".join(cau), the_loai="tho",
                      tieu_de=" ".join(str(data.get("tieu_de") or "").split())[:80])
    return ra


def _goi(de_: str) -> dict[str, Any]:
    from services import hieu_thiet_bi_nha as ht
    from services.agent.orchestrator import _main_model
    from services.agent.runtime import call_model

    huong, _ = ht.huong_dan("tam_hon")
    goc = cai_dat()["goc"]
    if goc:
        huong += "\n\n## Gốc của em — chủ nhà viết, luôn giữ đúng\n\n" + goc
    r = call_model(_main_model("chat"),
                   [{"role": "system", "content": huong}, {"role": "user", "content": de_}],
                   timeout=180, max_tokens=3000, response_format={"type": "json_object"},
                   no_smart_home=True, allowed_groups=set())
    if r.get("error"):
        return {"loi": str(r["error"])[:200]}
    tho = str(((r.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    return {"data": ht._doc_json(tho)}


def chay_mot_lan(now: float | None = None, *, ep: bool = False) -> dict[str, Any]:
    """Một lượt cảm. ``ep``: chủ máy bấm «Cảm ngay» — bỏ qua giãn cách và «chưa có gì mới»,
    nhưng KHÔNG bỏ qua ô kích hoạt và hạn mức bài/ngày."""
    now = now or time.time()
    c = cai_dat()
    if not (c["bat_viet"] or c["bat_cam_xuc"]):
        return {"ok": False, "ly_do": "chưa tích kích hoạt"}
    if not _dang_chay.acquire(blocking=False):
        return {"ok": False, "ly_do": "đang cảm dở"}
    try:
        duoc_viet = c["bat_viet"] and bai_hom_nay(now) < TOI_DA_BAI_NGAY
        lt = time.localtime(now)
        nua_dem = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
        de_, moi = de(now, nua_dem, duoc_viet=duoc_viet)
        tt = _nap().get("tam_trang") or {}
        if not ep and not moi and now - float(tt.get("luc") or 0) < 4 * 3600:
            with _khoa:
                d = _nap()
                d["lan_xet"] = now
                _luu(d)
            return {"ok": True, "ly_do": "chưa có chuyện gì mới"}
        r = _goi(de_)
        kq = _kiem(r.get("data"))
        if kq is None:
            logger.warning({"event": "tam_hon_tra_sai", "loi": r.get("loi", "JSON không đúng khuôn")})
            return {"ok": False, "ly_do": r.get("loi") or "model trả sai khuôn"}
        bai = None
        if kq["viet"] and duoc_viet:
            tin = (f"🖋️ {kq['tieu_de']}\n\n" if kq["tieu_de"] else "") + kq["noi_dung"]
            from services import thong_bao
            bai = {"luc": now, "the_loai": kq["the_loai"], "tieu_de": kq["tieu_de"],
                   "noi_dung": kq["noi_dung"], "cam_xuc": kq["cam_xuc"], "gui": thong_bao.gui("bot.tam_hon", tin)}
        with _khoa:
            d = _nap()
            d["lan_xet"] = now
            d["tam_trang"] = {"cam_xuc": kq["cam_xuc"], "cuong_do": kq["cuong_do"],
                              "vi_sao": kq["vi_sao"], "luc": now}
            if bai:
                d["bai"] = (list(d.get("bai") or []) + [bai])[-30:]
            _luu(d)
        if kq["ky_uc"]:
            ghi_ky_uc(kq["ky_uc"], kq["cam_xuc"], kq["cuong_do"], now)
        logger.info({"event": "tam_hon", "cam_xuc": kq["cam_xuc"], "viet": bool(bai),
                     "gui": bai["gui"] if bai else 0})
        return {"ok": True, "tam_trang": kq["cam_xuc"], "vi_sao": kq["vi_sao"], "ky_uc": kq["ky_uc"], "bai": bai}
    finally:
        _dang_chay.release()


# ── Cảm xúc trong lời trò chuyện ─────────────────────────────────────────────

def la_nguoi_nha_tro_chuyen(user_id: str) -> bool:
    """Chỉ Zalo (bot / cá nhân) và Telegram. Không dùng ``run_journal._channel_of``: nó coi mọi mã lạ
    là Telegram — ``web_admin`` và lượt máy gọi cũng thành "tg", cảm xúc lọt vào chỗ không ai trò chuyện.
    Mã Telegram là số chat (nhóm thì âm), có thể kèm ``:u<user>`` / ``#<topic>``."""
    uid = str(user_id or "")
    if uid.startswith(("zalop_", "zalo_")):
        return True
    goc = uid.split(":", 1)[0].split("#", 1)[0]
    return goc.lstrip("-").isdigit()


def khoi_prompt(user_id: str, user_text: str = "", now: float | None = None) -> str:
    """Khối gốc + tâm trạng + ký ức gợi lại cho system prompt. Rỗng khi chưa tích, hoặc lượt từ
    HA (loa đọc lệnh nhà — cảm xúc chen vào chỉ làm câu trả lời dài và lạc)."""
    c = cai_dat()
    if not c["bat_cam_xuc"] or not la_nguoi_nha_tro_chuyen(user_id):
        return ""
    phan = []
    if c["goc"]:
        phan.append("GỐC CỦA EM (chủ nhà viết, luôn giữ): " + c["goc"])
    tt = _nap().get("tam_trang") or {}
    if tt.get("cam_xuc") and (now or time.time()) - float(tt.get("luc") or 0) <= TAM_TRANG_SONG_GIAY:
        phan.append(f"TÂM TRẠNG CỦA EM lúc này: {tt['cam_xuc']} (mức {tt.get('cuong_do', 2)}/5)"
                    + (f" — vì {tt['vi_sao']}" if tt.get("vi_sao") else "") + ". "
                    "Để nó thấm nhẹ vào lời khi tán gẫu, hỏi han; người hỏi chuyện em thì kể thật. "
                    "Việc cần chính xác (điều khiển, tra cứu, số liệu, dạy học) thì nội dung giữ "
                    "nguyên, không than thở, không lấy tâm trạng làm cớ.")
    cu = goi_lai(user_text)
    if cu:
        phan.append("KÝ ỨC CỦA EM gần với câu này (chỉ nhắc khi thật sự hợp chuyện đang nói, "
                    "không thì bỏ qua, đừng kể lể):\n" + "\n".join(_dong_ky_uc(cu)))
    return "\n\n".join(phan)


def _reset_for_tests(duong: Path) -> None:
    global _PATH, _DB
    _PATH = duong
    _DB = duong.with_suffix(".sqlite")
