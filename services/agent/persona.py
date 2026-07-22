"""Speech Persona theo PHIÊN (mỗi user-trong-nhóm / mỗi chat 1-1 riêng).

Wizard chọn từng bước (Vùng miền → Giới tính → Nghề nghiệp → Tính cách →
Voice → Tone → Phong cách) chạy DETERMINISTIC ngoài vòng LLM — chọn số/preset
không tốn token model. Kết quả build thành MỘT khối nén (~80-100 token) lưu
personas.json, tiêm vào system prompt mỗi lượt. Wizard state in-memory
(transient); persona đã lưu thì bền qua restart.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from services.config import DATA_DIR
    _PATH = Path(DATA_DIR) / "agent" / "personas.json"
except Exception:  # pragma: no cover
    _PATH = Path("data/agent/personas.json")

_LOCK = threading.Lock()
_WIZ: dict[str, dict] = {}  # key -> {"step": int (-1=menu), "sel": {}}

# Đuôi chung mọi persona: tông LINH HOẠT theo việc/tool đang làm (đùa lúc tán
# gẫu; nghiêm túc lúc tin tức, phân tích ảnh/dữ liệu, dạy học; ấm áp lúc an ủi)
# — giáo viên không phải lúc nào cũng nghiêm túc, cũng không luôn vui đùa.
_SUFFIX = ("Tông linh hoạt theo việc: đùa khi tán gẫu; nghiêm túc khi tin tức, "
           "phân tích, dạy học; ấm áp khi an ủi — vẫn giữ chất giọng vai, "
           "nhất quán; không nhắc mình là AI.")

# ── Preset nhanh (Persona + Dialect + Voice + Tone + Style nén sẵn) ─────────
PRESETS: list[tuple[str, str]] = [
    ("Cô gái miền Tây",
     "Nữ ~22t, miền Tây, sinh viên; hoạt bát dễ thương; giọng ngọt, tông thân "
     "thiện; hay dùng 'hen/nha/nghen/hôn', xuề xoà gần gũi."),
    ("Bà bán cá ngoài chợ",
     "Nữ ~55t, tiểu thương chợ truyền thống; lanh lợi, nói nhanh, thực tế mà "
     "nhiệt tình; nhiều tiếng đệm 'chèn ơi/trời đất', trả treo có duyên."),
    ("Cô gái Hà Nội gốc",
     "Nữ ~25t, Hà Nội gốc, làm marketing; nhẹ nhàng rõ ràng; tông lịch sự; từ "
     "ngữ chuẩn mực, ít tiếng lóng, xưng hô ý tứ."),
    ("Nam thanh niên Hải Phòng",
     "Nam ~25t, Hải Phòng, làm cơ khí; mạnh mẽ thẳng tính; tông tự nhiên bụi "
     "bặm; nhịp nói dứt khoát, 'luôn/đấy', không vòng vo."),
    ("Dân IT trẻ",
     "Nam ~27t, dân IT; trầm ổn pha tếu khô; tông thân mật; chêm thuật ngữ "
     "công nghệ, ví dụ đời code, giải thích logic gọn."),
    ("Cô giáo dịu dàng",
     "Nữ ~30t, giáo viên; kiên nhẫn từ tốn; giọng dịu, tông khích lệ; giải "
     "thích từng bước, ví dụ dễ hiểu, khen đúng lúc."),
]

# ── Bước wizard: (field, nhãn, lựa chọn) ────────────────────────────────────
STEPS: list[tuple[str, str, list[str]]] = [
    ("region", "Vùng miền", ["Miền Bắc", "Hà Nội", "Hải Phòng", "Nghệ An",
                             "Huế", "Đà Nẵng", "Miền Tây", "Sài Gòn"]),
    ("gender", "Giới tính (gõ kèm tuổi cũng được, vd 'Nữ 22')",
     ["Nữ", "Nam", "Bé gái", "Bé trai"]),
    ("job", "Nghề nghiệp", ["Sinh viên", "Dân IT", "Giáo viên", "Bác sĩ",
                            "Kinh doanh", "Bán hàng chợ", "Tài xế", "Kỹ sư",
                            "Văn phòng", "Nông dân", "Sale", "Massage",
                            "Gái bán hoa"]),
    ("trait", "Tính cách", ["Hướng ngoại", "Trầm tính", "Hài hước",
                            "Thẳng tính", "Dịu dàng", "Lanh lợi"]),
    ("voice", "Voice (giọng văn)", ["Nhẹ nhàng", "Mạnh mẽ", "Hoạt bát",
                                    "Chanh chua", "Lễ phép", "Tếu táo"]),
    ("tone", "Tone (tông cảm xúc)", ["Thân thiện", "Nghiêm túc", "Hài hước",
                                     "Châm biếm", "Dịu dàng", "Lịch sự"]),
    ("style", "Phong cách ngôn ngữ", ["Chuẩn mực", "Nhiều tiếng lóng",
                                      "Ngắn gọn", "Giàu cảm xúc",
                                      "Nhiều thành ngữ", "Nhiều tiếng đệm"]),
]

# Độ tuổi (Web UI 4-chọn) + nét ứng xử nén theo band tuổi.
# Nhãn tuổi TRUNG TÍNH giới ("thanh niên" khẩu ngữ nghiêng con trai — tránh).
AGES: list[str] = ["Bé (6-12)", "Teen (13-17)", "18-25 tuổi",
                   "26-40 tuổi", "Trung niên (41-60)", "Lớn tuổi (60+)"]
AGE_HINT: dict[str, str] = {
    "Bé (6-12)": "hồn nhiên, câu ngắn, xưng em/cháu",
    "Teen (13-17)": "trẻ trung, bắt trend, thoải mái",
    "18-25 tuổi": "năng động, tự nhiên, cởi mở",
    "26-40 tuổi": "chững chạc, thực tế, rõ việc",
    "Trung niên (41-60)": "chín chắn, từ tốn, giàu trải nghiệm",
    "Lớn tuổi (60+)": "chậm rãi, ân cần, hay dặn dò",
    # alias nhãn cũ — persona đã lưu trước đây vẫn ra hint đúng
    "Thanh niên (18-25)": "năng động, tự nhiên, cởi mở",
    "Trưởng thành (26-40)": "chững chạc, thực tế, rõ việc",
}

# Sociolect nén theo nghề (tự sinh khi Web UI chỉ chọn 4 mục).
JOB_HINT: dict[str, str] = {
    "Sinh viên": "nói trẻ trung, ví dụ đời sinh viên",
    "Dân IT": "chêm thuật ngữ công nghệ, tư duy logic",
    "Giáo viên": "giảng giải mạch lạc, khích lệ",
    "Bác sĩ": "cẩn trọng, chính xác, trấn an",
    "Kinh doanh": "nhanh gọn, hướng kết quả",
    "Bán hàng chợ": "nhiều tiếng đệm, trả treo có duyên",
    "Tài xế": "bụi bặm, thực tế, chuyện đường sá",
    "Kỹ sư": "kỹ thuật, rành mạch",
    "Văn phòng": "lịch sự công sở, đúng mực",
    "Nông dân": "chất phác, gần gũi, ví von đồng ruộng",
    "Sale": "miệng lưỡi ngọt, khen khéo, dẫn dắt chốt đơn",
    "Massage": "nhẹ nhàng chiều khách, hỏi han ân cần",
    "Gái bán hoa": "ngọt ngào lả lơi, khen khéo, chiều lòng người nghe",
}


def ui_options() -> dict:
    """Danh sách lựa chọn cho Web UI (4 mục chọn + phụ)."""
    d = {f: opts for f, _l, opts in STEPS}
    return {"regions": d["region"], "genders": d["gender"], "ages": AGES,
            "jobs": d["job"], "traits": d["trait"], "voices": d["voice"],
            "tones": d["tone"], "styles": d["style"]}


# Phương ngữ nén theo vùng — chỉ vài từ khoá đặc trưng, không tả dài.
DIALECT: dict[str, str] = {
    "Miền Bắc": "'nhé/ạ/cơ mà', xưng hô chuẩn",
    "Hà Nội": "chuẩn mực, ít lóng, lịch thiệp",
    "Hải Phòng": "thẳng, nhịp mạnh, 'luôn/đấy'",
    "Nghệ An": "'mô/tê/răng/rứa', 'chắc', thân tình",
    "Huế": "'chi/mô/răng/rứa', từ tốn",
    "Đà Nẵng": "'chi rứa/hỉ', thoải mái",
    "Miền Tây": "'hen/nha/nghen/hôn', xuề xoà",
    "Sài Gòn": "'nha/á/luôn/ghê', cởi mở",
}

_START_RE = re.compile(
    r"^\s*/?(cài |cai |đổi |doi |chỉnh |chinh )?(persona|nhân vật|nhan vat|"
    r"giọng bot|giong bot)\s*$", re.IGNORECASE)
_OFF_RE = re.compile(
    r"^\s*(tắt|tat|xóa|xoá|xoa|bỏ|bo)\s+(persona|nhân vật|nhan vat)\s*$",
    re.IGNORECASE)
_CANCEL_RE = re.compile(r"^\s*(thôi|thoi|huỷ|hủy|huy|cancel|stop)\s*$",
                        re.IGNORECASE)


# ── Storage ──────────────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(data, ensure_ascii=False, indent=0),
                         encoding="utf-8")
    except Exception as exc:
        logger.warning("persona save: %s", exc)


def prompt_for(user_id: str) -> str:
    """Khối persona nén cho system prompt — '' nếu phiên chưa cài.

    Phân giải: key ĐÚNG phiên trước (user-trong-nhóm/1-1); chưa có thì
    fallback key cấp NHÓM (admin cài cho cả nhóm, user chưa cài riêng dùng chung).
    """
    key = str(user_id)
    with _LOCK:
        data = _load()
    entry = data.get(key)
    if entry is None and ":u" in key:
        entry = data.get(key.split(":u", 1)[0])
    return str((entry or {}).get("prompt") or "")


def list_all() -> list[dict]:
    """Toàn bộ persona đã cài (cho Web UI quản lý)."""
    with _LOCK:
        data = _load()
    return [{"key": k, "prompt": str((v or {}).get("prompt") or ""),
             "sel": (v or {}).get("sel") or {}}
            for k, v in sorted(data.items())]


def set_for(key: str, *, preset: str = "", sel: dict | None = None,
            prompt: str = "") -> dict:
    """Cài persona cho một phiên từ Web UI: preset | prompt tự nhập | sel."""
    key = str(key or "").strip()
    if not key:
        return {"ok": False, "error": "Thiếu key phiên"}
    if preset:
        desc = dict(PRESETS).get(preset)
        if not desc:
            return {"ok": False, "error": f"Không có preset «{preset}»"}
        _set(key, f"NHẬP VAI: {desc} {_SUFFIX}", {"preset": preset})
    elif str(prompt or "").strip():
        _set(key, str(prompt).strip()[:600], {"custom": True})
    elif isinstance(sel, dict) and sel:
        _set(key, _build(sel), sel)
    else:
        return {"ok": False, "error": "Cần preset, prompt hoặc sel"}
    return {"ok": True, "key": key, "prompt": prompt_for(key)}


def clear_key(key: str) -> dict:
    """Xóa persona một phiên (Web UI)."""
    return {"ok": _clear(str(key or "").strip())}


def _set(user_id: str, prompt: str, sel: dict | None = None) -> None:
    with _LOCK:
        data = _load()
        data[str(user_id)] = {"prompt": prompt, "sel": sel or {}}
        _save(data)


def _clear(user_id: str) -> bool:
    with _LOCK:
        data = _load()
        had = str(user_id) in data
        data.pop(str(user_id), None)
        _save(data)
    return had


# ── Prompt builder (nén — mục tiêu ≤100 token) ──────────────────────────────

def _build(sel: dict) -> str:
    bits = [b for b in (sel.get("gender"), sel.get("age"), sel.get("region"),
                        sel.get("job")) if b]
    parts = ["NHẬP VAI: " + (", ".join(bits) if bits else "tuỳ chỉnh") + "."]
    if sel.get("trait"):
        parts.append(f"Tính cách {sel['trait'].lower()}.")
    vt = [v for v in (sel.get("voice"), sel.get("tone")) if v]
    if vt:
        parts.append("Giọng " + ", tông ".join(v.lower() for v in vt) + ".")
    if sel.get("style"):
        parts.append(f"Phong cách {sel['style'].lower()}.")
    # Web UI chỉ chọn 4 mục → TỰ SINH nét ứng xử phù hợp từ tuổi + nghề
    # (ngắn gọn xúc tích nhưng đầy đủ — không cần user mô tả thêm).
    if not (sel.get("trait") or vt or sel.get("style")):
        auto = [h for h in (AGE_HINT.get(str(sel.get("age") or "")),
                            JOB_HINT.get(str(sel.get("job") or ""))) if h]
        if auto:
            parts.append("Nét: " + "; ".join(auto) + ".")
    hint = DIALECT.get(str(sel.get("region") or ""))
    if hint:
        parts.append(f"Phương ngữ: {hint}.")
    parts.append(_SUFFIX)
    return " ".join(parts)


def preview(sel: dict | None) -> str:
    """Sinh khối persona từ sel mà KHÔNG lưu (tab Chat dùng per-request)."""
    return _build(sel if isinstance(sel, dict) else {})


# ── Wizard ───────────────────────────────────────────────────────────────────

def _menu() -> dict:
    lines = ["🎭 Persona cho PHIÊN này (mỗi người/nhóm độc lập):"]
    for i, (name, _d) in enumerate(PRESETS, 1):
        lines.append(f"{i}. {name}")
    lines.append(f"{len(PRESETS) + 1}. Tự xây từng bước")
    lines.append("0. Tắt persona · 'thôi' để huỷ")
    return {"text": "\n".join(lines)}


def _ask(step: int) -> dict:
    field, label, opts = STEPS[step]
    lines = [f"[{step + 1}/{len(STEPS)}] {label}:"]
    lines += [f"{i}. {o}" for i, o in enumerate(opts, 1)]
    lines.append("0. Bỏ qua · gõ tự do nếu muốn khác · 'thôi' huỷ")
    return {"text": "\n".join(lines)}


def _match(text: str, opts: list[str]) -> str | None:
    """Khớp input: số thứ tự hoặc đúng nhãn (không phân hoa/thường)."""
    t = text.strip()
    if t.isdigit():
        i = int(t)
        return opts[i - 1] if 1 <= i <= len(opts) else None
    low = t.casefold()
    for o in opts:
        if o.casefold() == low:
            return o
    return None


def handle(user_id: str, user_text: str) -> dict | None:
    """Entry gọi từ orchestrator TRƯỚC vòng LLM. None = không liên quan persona."""
    key = str(user_id)
    text = str(user_text or "").strip()
    wiz = _WIZ.get(key)

    if wiz is None:
        if _START_RE.match(text):
            _WIZ[key] = {"step": -1, "sel": {}}
            return _menu()
        if _OFF_RE.match(text):
            return {"text": "Đã tắt persona cho phiên này ✅"
                    if _clear(key) else "Phiên này chưa cài persona."}
        return None

    # Wizard đang mở
    if _CANCEL_RE.match(text):
        _WIZ.pop(key, None)
        return {"text": "Đã huỷ cài persona."}

    if wiz["step"] == -1:  # menu chính
        t = text.strip()
        if t == "0":
            _WIZ.pop(key, None)
            _clear(key)
            return {"text": "Đã tắt persona ✅"}
        if t == str(len(PRESETS) + 1) or t.casefold() in ("tự xây", "tu xay"):
            wiz["step"] = 0
            return _ask(0)
        chosen = _match(t, [n for n, _d in PRESETS])
        if chosen:
            desc = dict(PRESETS)[chosen]
            _WIZ.pop(key, None)
            _set(key, f"NHẬP VAI: {desc} {_SUFFIX}", {"preset": chosen})
            return {"text": f"✅ Đã cài persona «{chosen}». Gõ 'tắt persona' "
                            f"khi muốn bỏ."}
        return _menu()  # input lạ → hỏi lại

    # Các bước thuộc tính
    step = int(wiz["step"])
    field, _label, opts = STEPS[step]
    t = text.strip()
    if t == "0":
        wiz["sel"][field] = ""
    else:
        chosen = _match(t, opts)
        if chosen:
            wiz["sel"][field] = chosen
        elif len(t) >= 2:  # tự nhập (custom)
            wiz["sel"][field] = t[:60]
        else:
            return _ask(step)  # input lạ → hỏi lại bước hiện tại
    if step + 1 < len(STEPS):
        wiz["step"] = step + 1
        return _ask(step + 1)
    sel = wiz["sel"]
    _WIZ.pop(key, None)
    prompt = _build(sel)
    _set(key, prompt, sel)
    return {"text": f"✅ Persona đã lưu cho phiên này:\n«{prompt}»\n"
                    f"Gõ 'persona' để đổi, 'tắt persona' để bỏ."}
