"""Sổ BÀI HỌC từ lỗi: bot sai một lần thì lần sau tự tránh.

VÌ SAO CẦN — chuỗi bằng chứng đo được ngày 10/09/2026:

  1. Bot trả lời sai hai lần trong một buổi sáng. Cả hai lượt nhật ký đều ghi
     là chạy đúng: một lượt `status=approved tools=["remember"]`, một lượt
     `status=ha_fastpath steps=0`. Không bộ dò lỗi nào bắt được.
  2. Cách chữa cũ là thêm danh sách từ khoá chặn. Riêng `services/` đã có 52
     file làm vậy. Danh sách luôn thiếu, và mỗi lần thiếu là một lần CHỦ MÁY
     phải làm người soát lỗi.
  3. Thử ba cách tự đoán lỗi từ nhật ký (từ khoá phàn nàn, độ dài câu, hỏi lại
     cùng ý) — cả ba đều nhiễu nặng: 152, 4-nhưng-cắt-mất-10%-câu-thật, và 65
     ca toàn luồng hỏi-đáp bình thường.

Nên đường đúng là hỏi thẳng người biết câu trả lời: chủ máy. Bot nói ra lúc nó
KHÔNG CHẮC (đi đường tắt khớp chuỗi, không qua model — đo được 59 lượt/30 ngày,
khoảng 2 lượt/ngày), chủ máy bấm đúng/sai, và sổ này nhớ lấy.

Đây là Reflexion — lưu bài học từ lỗi rồi tra lại khi gặp tình huống tương tự.
Đối chiếu tài liệu agent tự cải thiện 2026, dự án đã có ba trong bốn phương
pháp (`state` là memory-based, `_so_thich_trinh_bay` là prompt optimization,
`skill_quality` là tool refinement) và thiếu đúng mảnh này.

CÁCH CHẤM ĐIỂM mượn nguyên của `skill_quality.diem` — tỉ lệ thành công làm trơn
Laplace. Cùng bài toán "chấm một thứ theo kết quả quá khứ" thì dùng cùng công
thức, khỏi có hai định nghĩa lệch nhau.

KHỚP THEO TỪ CHUNG, KHÔNG THEO CHUỖI CON. Đây là điểm khác căn bản so với các
danh sách từ khoá mà module này thay thế: "con trai về nhà lúc mấy giờ" phải
tránh được nhờ bài học của "fingerprint#2 lần cuối lúc mấy giờ", dù hai câu
không chung một chuỗi con nào đáng kể.
"""

from __future__ import annotations

import json
import os
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any

from utils.log import logger

_lock = threading.RLock()


def _cfg() -> dict:
    """Cấu hình dưới ``mqtt.bai_hoc`` — cùng chỗ với `khoa_cua`, `canh_bao`.

    Đặt chung một nơi để chủ máy chỉnh mọi thứ liên quan tới nhà ở một trang,
    không phải đi tìm từng chỗ.
    """
    try:
        from services.config import config
        raw = (config.data.get("mqtt") or {}).get("bai_hoc")
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def is_enabled() -> bool:
    """Tắt thì bot chạy y như trước: không hỏi lại, không tra bài học."""
    return bool(_cfg().get("bat", True))


def _so(khoa: str, mac_dinh: float) -> float:
    try:
        v = _cfg().get(khoa)
        return float(v) if v is not None else mac_dinh
    except (TypeError, ValueError):
        return mac_dinh

#: Đủ mẫu mới dám kết luận một bộ dò là dở. Chưa dùng lần nào KHÁC với dùng
#: nhiều mà hay sai — cùng ngưỡng `skill_quality._DU_MAU`.
_DU_MAU = 4
_DIEM_TOI = 0.5

#: Ngưỡng coi hai câu là CÙNG MỘT Ý (Jaccard). Đo trên câu thật của chủ máy:
#:   0.38  "ai mở cửa lúc mấy giờ"  ← phải khớp bài học câu vân tay
#:   0.33  "mấy giờ rồi"            ← KHÔNG được khớp
#:   0.29  "bây giờ là mấy giờ"     ← KHÔNG được khớp
#: 0.34 là chỗ tách được hai nhóm mà không chặn nhầm câu hỏi giờ thường.
_GIONG_TOI_THIEU = 0.34

#: Bài học cũ hơn ngần này thì thôi tính — nhà thay đổi, thiết bị thay đổi.
_HAN_NGAY = 180

#: Từ đệm bỏ khi so câu. Giữ lại từ MANG NGHĨA. Cùng cách làm với
#: `services/agent/so_da_luu._BO`, không dựng định nghĩa thứ hai.
_TU_DEM = {
    "la", "thi", "ma", "va", "cua", "cho", "voi", "o", "tai", "trong", "ra",
    "vao", "di", "den", "toi", "em", "anh", "chi", "a", "ah", "ao", "nhe",
    "nha", "the", "nay", "do", "kia", "ay", "co", "khong", "duoc", "bao",
    "nhieu", "gi", "sao", "hay", "giup", "oi", "u", "day", "roi", "day",
}


def _duong() -> Path:
    from services.config import DATA_DIR
    return Path(DATA_DIR) / "agent" / "bai_hoc.json"


def _doc() -> dict[str, Any]:
    try:
        p = _duong()
        if p.is_file():
            d = json.loads(p.read_text("utf-8") or "{}")
            return d if isinstance(d, dict) else {}
    except Exception as exc:
        logger.warning({"event": "bai_hoc_doc_loi", "loi": str(exc)[:150]})
    return {}


def _ghi(d: dict) -> bool:
    """Ghi nguyên tử — mất điện giữa chừng không để lại JSON hỏng."""
    tmp: Path | None = None
    try:
        p = _duong()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
        os.replace(tmp, p)
        return True
    except Exception as exc:
        logger.warning({"event": "bai_hoc_ghi_loi", "loi": str(exc)[:150]})
        return False
    finally:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


# ── so câu theo Ý, không theo chuỗi ─────────────────────────────────────────
def _tu_dac_trung(cau: str) -> set[str]:
    """Các từ MANG NGHĨA của một câu, đã bỏ dấu và bỏ từ đệm."""
    n = unicodedata.normalize("NFKD", (cau or "").lower())
    thuong = "".join(c for c in n if not unicodedata.combining(c)).replace("đ", "d")
    ra = set()
    for w in thuong.replace("?", " ").replace(",", " ").replace(".", " ").split():
        w = w.strip("#:«»\"'()[]")
        if len(w) >= 2 and w not in _TU_DEM:
            ra.add(w)
    return ra


def do_giong(a: str, b: str) -> float:
    """Hai câu cùng ý tới mức nào — 0 tới 1.

    Chia cho tập NHỎ HƠN để câu dài thêm chi tiết vẫn nhận ra là cùng ý: "mấy
    giờ rồi" và "anh ơi cho em hỏi bây giờ mấy giờ rồi ạ" phải ra cao.

    Dùng Jaccard (chung / hợp) chứ KHÔNG chia cho tập nhỏ hơn. Đo thật trên
    câu của chủ máy:

      chia cho tập nhỏ  →  "mấy giờ rồi" ra 1.00 với "fingerprint#2 lần cuối
                           lúc mấy giờ", vì hai từ của nó nằm trọn trong câu
                           kia. Hệ quả: đánh dấu câu vân tay là sai thì câu
                           hỏi giờ bình thường bị chặn theo.
      Jaccard           →  0.33, dưới ngưỡng, không chặn nhầm.

    Giới hạn đã biết và CHẤP NHẬN: "con trai về nhà lúc mấy giờ" cũng ra 0.33
    nên không được bảo vệ bởi bài học của câu vân tay. Hai ca này không tách
    được bằng cách đếm từ, và thà bỏ sót còn hơn chặn nhầm câu hỏi thường —
    thêm luật đặc biệt cho "lúc" là quay lại đúng lối danh sách từ khoá mà
    module này sinh ra để thay thế.
    """
    ta, tb = _tu_dac_trung(a), _tu_dac_trung(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


#: KHÔNG có ngưỡng dưới. Đo thật 10/09/2026: cặp CÙNG Ý và cặp KHÁC HẲN đều
#: ra 0.00 như nhau —
#:   0.00  "fingerprint#2 lần cuối lúc mấy giờ" / "vân tay số 2 mở cửa hồi nào"
#:   0.00  "bật đèn bếp"                        / "giá vàng hôm nay"
#: nên không có mức nào tách được hai nhóm. Đành hỏi AI cho mọi câu chưa vượt
#: ngưỡng đếm từ, và chặn chi phí bằng TRẦN SỐ LẦN HỎI mỗi lượt thay vì bằng
#: ngưỡng điểm.
#:
#: Chi phí thực tế thấp: chỉ so với các BÀI HỌC ĐÃ CÓ (sổ rỗng thì không hỏi
#: lần nào), và mỗi lượt tối đa `_AI_TOI_DA` lần.
_AI_TOI_DA = 3


def model_hoc() -> str:
    """Model dùng cho phần học hỏi. Rỗng = theo định tuyến chung (`burst`).

    Tách riêng vì việc ở đây khác hẳn việc trả lời chủ máy: chỉ so hai câu có
    cùng ý không, trả về đúng một từ. Một model nhỏ và nhanh làm tốt việc này
    với chi phí thấp hơn nhiều, mà chọn sai cũng không hỏng gì — không kết luận
    được thì `_ai_cung_y` trả None và phần đếm từ vẫn quyết định.

    Đặt ở `mqtt.bai_hoc.model`, chọn trong Cài đặt → MQTT. Cùng khoá cho cả
    `du_doan_nha`, để chủ máy không phải chỉnh hai nơi cho một việc.
    """
    return str(_cfg().get("model") or "").strip()


def dung_ai() -> bool:
    """Có nhờ AI so ý khi đếm từ không kết luận nổi không. Mặc định BẬT.

    VÌ SAO CẦN — đo thật 10/09/2026, bốn cặp câu CÙNG MỘT Ý:

        0.00  "fingerprint#2 lần cuối lúc mấy giờ" / "vân tay số 2 mở cửa hồi nào"
        0.00  "bật đèn bếp"                        / "làm sáng chỗ nấu ăn"
        0.20  "thời tiết hôm nay"                  / "trời hôm nay thế nào"

    Đếm từ không nhận ra cái nào, vì chúng không chung từ nào. Bot học được
    bài học từ câu này thì lần sau chủ máy hỏi cách khác là nó lại sai.
    """
    return bool(_cfg().get("dung_ai", True))


def _ai_cung_y(a: str, b: str) -> bool | None:
    """Hai câu có cùng một ý không — hỏi model.

    Trả None khi không kết luận được (model hỏng, tắt, trả lời lạ) → caller
    giữ nguyên kết quả đếm từ, KHÔNG đoán bừa.
    """
    if not dung_ai():
        return None
    try:
        from services.agent.orchestrator import _main_model
        from services.agent.runtime import call_model
    except Exception:
        return None
    try:
        r = call_model(
            model_hoc() or _main_model("burst"),
            [{"role": "system", "content":
              "Hai câu dưới đây có hỏi/yêu cầu CÙNG MỘT VIỆC không? "
              "Chỉ trả đúng một từ: CO hoặc KHONG. Không giải thích."},
             {"role": "user", "content": f"Câu 1: {a[:200]}\nCâu 2: {b[:200]}"}],
            timeout=15, max_tokens=5, no_smart_home=True,
            allowed_groups=set())
        if r.get("error"):
            return None
        noi = str((r.get("choices") or [{}])[0]
                  .get("message", {}).get("content") or "").strip().upper()
    except Exception as exc:
        logger.info({"event": "bai_hoc_ai_loi", "loi": str(exc)[:120]})
        return None
    if noi.startswith("CO"):
        return True
    if noi.startswith("KHONG"):
        return False
    return None


# ── ghi ─────────────────────────────────────────────────────────────────────
def ghi_sai(cau_hoi: str, tra_loi: str, bo_do: str = "",
            user_id: str = "") -> bool:
    """Chủ máy nói câu trả lời này SAI. Trả True nếu đã lưu."""
    ch = (cau_hoi or "").strip()
    if not ch:
        return False
    with _lock:
        d = _doc()
        ds = d.setdefault("sai", [])
        # Cùng một câu hỏi sai lại thì TĂNG ĐẾM, không nhân đôi dòng.
        for m in ds:
            if do_giong(m.get("cau_hoi") or "", ch) >= 0.9:
                m["so_lan"] = int(m.get("so_lan") or 1) + 1
                m["ts"] = time.time()
                _cham(d, bo_do, dung=False)
                return bool(_ghi(d))
        ds.append({
            "cau_hoi": ch[:300],
            "tra_loi": (tra_loi or "")[:300],
            "bo_do": bo_do or "",
            "user_id": user_id or "",
            "so_lan": 1,
            "ts": time.time(),
        })
        _cham(d, bo_do, dung=False)
        return bool(_ghi(d))


def ghi_dung(cau_hoi: str, bo_do: str = "") -> bool:
    """Chủ máy xác nhận ĐÚNG — để bộ dò tốt không bị trừ oan."""
    if not bo_do:
        return False
    with _lock:
        d = _doc()
        _cham(d, bo_do, dung=True)
        return bool(_ghi(d))


def _cham(d: dict, bo_do: str, *, dung: bool) -> None:
    """Cộng/trừ điểm cho bộ dò. Gọi trong `_lock`."""
    if not bo_do:
        return
    m = d.setdefault("bo_do", {}).setdefault(bo_do, {"dung": 0, "sai": 0})
    m["dung" if dung else "sai"] = int(m.get("dung" if dung else "sai") or 0) + 1


# ── tra ─────────────────────────────────────────────────────────────────────
def tra(cau_hoi: str, *, nguong: float | None = None) -> list[dict]:
    """Câu tương tự đã từng sai chưa. Rỗng = chưa có bài học nào.

    Trả list sắp theo độ giống giảm dần, mỗi mục thêm khoá ``giong``.
    """
    ch = (cau_hoi or "").strip()
    if not ch:
        return []
    if not is_enabled():
        return []
    han = time.time() - _so("han_ngay", _HAN_NGAY) * 86400
    ra: list[dict] = []
    da_hoi = 0          # trần số lần nhờ AI trong MỘT lượt tra
    with _lock:
        for m in (_doc().get("sai") or []):
            if float(m.get("ts") or 0) < han:
                continue
            cu = m.get("cau_hoi") or ""
            g = do_giong(cu, ch)
            ng = (nguong if nguong is not None
                  else _so("giong_toi_thieu", _GIONG_TOI_THIEU))
            if g >= ng:
                ra.append({**m, "giong": round(g, 3)})
                continue
            # Đếm từ nói "khác nhau", nhưng ở vùng KHÔNG CHẮC thì hỏi AI —
            # hai câu cùng ý mà khác hẳn từ ngữ chỉ AI mới nhận ra.
            if da_hoi < _AI_TOI_DA:
                da_hoi += 1
                if _ai_cung_y(cu, ch):
                    ra.append({**m, "giong": round(g, 3), "ai_xac_nhan": True})
    ra.sort(key=lambda x: x["giong"], reverse=True)
    return ra


def _du_mau() -> int:
    return max(1, int(_so("du_mau", _DU_MAU)))


def diem(bo_do: str) -> float:
    """Tỉ lệ đúng làm trơn Laplace — cùng công thức `skill_quality.diem`.

    Chưa có dữ liệu → 0.5 (chưa biết), không phải 0 (dở).
    """
    with _lock:
        m = (_doc().get("bo_do") or {}).get(bo_do) or {}
    dung = int(m.get("dung") or 0)
    sai = int(m.get("sai") or 0)
    return (dung + 1) / (dung + sai + 2)


def bo_do_dang_ngo(bo_do: str) -> bool:
    """Bộ dò này sai nhiều quá thì nhường cho model.

    Chỉ kết luận khi ĐỦ MẪU — chưa dùng lần nào không phải là dở, đúng như
    `skill_quality.nen_an_khoi_router` đã làm với skill.
    """
    if not bo_do:
        return False
    with _lock:
        m = (_doc().get("bo_do") or {}).get(bo_do) or {}
    dung = int(m.get("dung") or 0)
    sai = int(m.get("sai") or 0)
    if dung + sai < _du_mau():
        return False
    return diem(bo_do) < _so("diem_toi", _DIEM_TOI)


def da_tin_duoc(bo_do: str) -> bool:
    """Bộ dò đã chứng minh đúng nhiều lần thì THÔI HỎI LẠI — đừng làm phiền."""
    if not bo_do:
        return False
    with _lock:
        m = (_doc().get("bo_do") or {}).get(bo_do) or {}
    dung = int(m.get("dung") or 0)
    sai = int(m.get("sai") or 0)
    return dung + sai >= _du_mau() and diem(bo_do) >= _so("diem_tin", 0.8)


def nen_hoi_lai(bo_do: str) -> bool:
    """Có nên gắn nút «đúng ý anh chưa?» cho lượt này không."""
    return bool(bo_do) and is_enabled() and not da_tin_duoc(bo_do)


# ── báo chủ động ────────────────────────────────────────────────────────────
def _kenh_nhan() -> list[str]:
    """Các kênh nhận bản tin — khoá dạng ``plat:bot:chat`` như «Lọc thread».

    Rỗng = chưa chọn, rơi về admin mặc định của `canh_bao_nha._nguoi_nhan()`.

    Dùng ĐÚNG danh sách mà «Gửi tóm tắt tới kênh» của email/lịch đang dùng
    (`config.thread_filter` + `thread_filter_meta`), chứ không phải một ô chọn
    "telegram | zalo": nhà có nhiều tài khoản Zalo và nhiều nhóm, chọn mỗi
    "zalo" thì không biết là Zalo nào.
    """
    raw = _cfg().get("kenh_nhan")
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


def _gui(user_id: str, text: str) -> None:
    """Gửi cho một người theo kênh mặc định của họ (đường của reminders)."""
    from services.agent import reminders as rem

    channel, chat_id = rem.channel_of(user_id)
    rem._send(channel, chat_id, text, {})


def soan_bao(so_ngay: int = 7) -> str:
    """Bản tin «em học được gì» — rỗng nếu chưa có gì đáng kể.

    Chỉ kể khi CÓ THAY ĐỔI: chưa học được gì mà vẫn nhắn mỗi tuần là làm phiền.
    """
    han = time.time() - max(1, int(so_ngay)) * 86400
    with _lock:
        d = _doc()
        moi = [m for m in (d.get("sai") or []) if float(m.get("ts") or 0) >= han]
        bd = dict(d.get("bo_do") or {})
    if not moi and not bd:
        return ""

    dong = [f"🧠 Em học được gì {so_ngay} ngày qua:"]
    if moi:
        dong.append(f"\nCó {len(moi)} câu anh bảo em trả lời chưa đúng — "
                    "lần sau gặp câu tương tự em sẽ nghĩ kỹ hơn:")
        for m in sorted(moi, key=lambda x: -float(x.get("ts") or 0))[:5]:
            dong.append(f"  · {str(m.get('cau_hoi') or '')[:70]}")

    tin = [k for k in bd if da_tin_duoc(k)]
    ngo = [k for k in bd if bo_do_dang_ngo(k)]
    if tin:
        dong.append(f"\n✅ {len(tin)} loại câu em đã trả lời chắc tay, "
                    "thôi hỏi lại anh nữa.")
    if ngo:
        dong.append(f"⚠️ {len(ngo)} loại câu em hay sai — từ giờ em nghĩ kỹ "
                    "thay vì trả lời nhanh.")
    return "\n".join(dong)


def chay_mot_lan(so_ngay: int = 7) -> dict[str, Any]:
    """Heartbeat gọi. Gửi bản tin học tập nếu tới hạn và có gì để kể."""
    if not is_enabled() or not bool(_cfg().get("bao", False)):
        return {"gui": 0, "ly_do": "chưa bật báo học tập"}

    moi_ngay = max(1, int(_so("bao_moi_ngay", 7)))
    with _lock:
        d = _doc()
        lan_cuoi = float(d.get("bao_lan_cuoi") or 0)
    if time.time() - lan_cuoi < moi_ngay * 86400:
        return {"gui": 0, "ly_do": "chưa tới hạn báo"}

    tin = soan_bao(so_ngay)
    if not tin:
        return {"gui": 0, "ly_do": "chưa học được gì đáng kể"}

    # Chủ máy chọn kênh đích danh thì gửi đúng đó — dùng lại `digest.send_targets`
    # mà email/lịch đang dùng, cùng định dạng khoá `plat:bot:chat`.
    gui = 0
    kenh = _kenh_nhan()
    if kenh:
        try:
            from services import digest
            gui = digest.send_targets(kenh, tin)
        except Exception as exc:
            logger.warning({"event": "bai_hoc_gui_loi", "loi": str(exc)[:150]})
    else:
        # Chưa chọn kênh → admin mặc định, chủ máy đã khai ở tab Kênh chat.
        from services import canh_bao_nha
        nguoi = canh_bao_nha._nguoi_nhan()
        if not nguoi:
            return {"gui": 0, "ly_do": "chưa chọn kênh nhận"}
        for uid in nguoi:
            try:
                _gui(uid, tin)
                gui += 1
            except Exception as exc:
                logger.warning({"event": "bai_hoc_gui_loi", "loi": str(exc)[:150]})
    if gui:
        with _lock:
            d = _doc()
            d["bao_lan_cuoi"] = time.time()
            _ghi(d)
    return {"gui": gui, "so_bai_hoc": len(_doc().get("sai") or [])}


def thong_ke() -> dict[str, Any]:
    with _lock:
        d = _doc()
    bd = d.get("bo_do") or {}
    return {
        "so_bai_hoc": len(d.get("sai") or []),
        "bo_do": {k: {"dung": v.get("dung", 0), "sai": v.get("sai", 0),
                      "diem": round(diem(k), 3), "dang_ngo": bo_do_dang_ngo(k)}
                  for k, v in bd.items()},
    }


def _reset_for_tests() -> None:
    _ghi({})
