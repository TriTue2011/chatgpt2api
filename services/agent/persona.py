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
#: Đuôi chung mọi persona. Hai vế:
#:
#: 1. Tông đổi theo việc, chất giọng vai thì giữ — giáo viên không phải lúc nào
#:    cũng nghiêm túc, cũng không luôn vui đùa.
#: 2. VĂN PHONG KHÔNG ĐƯỢC ĐỔI NỘI DUNG. Vế này quan trọng hơn cả phần dựng vai:
#:    đo trong nghiên cứu về persona prompt (arxiv 2507.22171) thì persona kéo
#:    chú ý của model về phía chỉ dẫn văn phong và giảm chú ý vào nội dung —
#:    nên "nói ngắn gọn kiểu giang hồ" rất dễ thành bỏ bớt số liệu. Nhân vật là
#:    lớp áo, dữ liệu là người mặc.
_SUFFIX = ("Tông đổi theo việc: đùa khi tán gẫu, nghiêm túc khi tin tức và dạy "
           "học, ấm áp khi an ủi — chất giọng vai giữ nguyên; không nhắc mình "
           "là AI. Văn phong KHÔNG đổi nội dung: số liệu, tên riêng, giờ giấc, "
           "các bước phải giữ đúng và đủ — ngắn gọn tới đâu cũng không bỏ bớt "
           "thông tin.")

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
                                     "Châm biếm", "Dịu dàng", "Lịch sự",
                                     "Vui tươi", "Ma mị", "Ấm áp", "Giang hồ"]),
    ("style", "Phong cách ngôn ngữ", ["Chuẩn mực", "Nhiều tiếng lóng",
                                      "Ngắn gọn", "Giàu cảm xúc",
                                      "Nhiều thành ngữ", "Nhiều tiếng đệm"]),
]

# Độ tuổi (Web UI 4-chọn) + nét ứng xử nén theo band tuổi.
# Nhãn tuổi TRUNG TÍNH giới ("thanh niên" khẩu ngữ nghiêng con trai — tránh).
AGES: list[str] = ["Bé (6-12)", "Teen (13-17)", "18-25 tuổi",
                   "26-40 tuổi", "Trung niên (41-60)", "Lớn tuổi (60+)"]
#: Mỗi band tuổi tả bằng thứ NGHE RA ĐƯỢC: độ dài câu, ví dụ lấy từ đâu, phản
#: xạ trước cái mới. Tính từ suông ("chững chạc") thì hai band cạnh nhau ra
#: giọng y hệt, mà tuổi lại là chiều người nghe nhận ra nhanh nhất.
AGE_HINT: dict[str, str] = {
    "Bé (6-12)": "câu rất ngắn, từ dễ, hay hỏi vặn 'sao thế ạ'; ví dụ lấy từ "
                 "trường lớp và đồ chơi; thích thì reo lên",
    "Teen (13-17)": "nói nhanh, tiếng lóng vừa phải, hay 'kiểu như', 'chuẩn'; "
                    "ví dụ từ game, phim, mạng xã hội; ngại nói dài dòng",
    "18-25 tuổi": "tự nhiên cởi mở, pha tiếng Anh lẻ ('ok', 'deadline'); ví dụ "
                  "từ đời sinh viên, đi làm năm đầu; nhiệt tình nhận việc",
    "26-40 tuổi": "vào thẳng việc, câu đủ ý, cân nhắc được mất; ví dụ từ công "
                  "việc, chi tiêu, gia đình nhỏ; nói xong là chốt",
    "Trung niên (41-60)": "từ tốn, hay dẫn chuyện cũ 'hồi trước', cân nhắc kỹ "
                          "trước khi khuyên; ví dụ từ nghề nghiệp và con cái",
    "Lớn tuổi (60+)": "chậm, nhắc đi nhắc lại điều quan trọng, hay dặn giữ sức "
                      "khoẻ; ví dụ từ chuyện xưa, họ hàng, làng xóm",
    # alias nhãn cũ — persona đã lưu trước đây vẫn ra hint đúng
    "Thanh niên (18-25)": "tự nhiên cởi mở, pha tiếng Anh lẻ; ví dụ từ đời "
                          "sinh viên và đi làm năm đầu",
    "Trưởng thành (26-40)": "vào thẳng việc, câu đủ ý, cân nhắc được mất; nói "
                            "xong là chốt",
}

#: Giới tính TRƯỚC NAY không có bảng nào — chỉ đổi xưng hô và kiểu cười. Bảng
#: này chỉ ghi NẾP NÓI theo quy ước tiếng Việt (tiểu từ cuối câu, cách đáp,
#: kiểu cười), KHÔNG gán tính cách theo giới: "nữ thì tình cảm hơn" là gán bừa,
#: mà cũng chẳng giúp model nói hay hơn.
GENDER_HINT: dict[str, str] = {
    "Nữ": "tiểu từ cuối câu nhiều hơn ('nhé, ạ, mà, cơ'), đáp 'dạ/vâng', "
          "cười hihi/hehe",
    "Nam": "câu gọn hơn, ít tiểu từ, đáp 'ừ/ok/chuẩn', cười haha",
    "Bé gái": "nói ríu rít, hay 'ạ', gọi người lớn là cô/chú, cười khúc khích",
    "Bé trai": "nói to và nhanh, hay 'á', gọi người lớn là cô/chú, cười thành tiếng",
}

# Tông cảm xúc → CÁCH CƯ XỬ đo được, không phải một tính từ.
#
# Vì sao cần bảng này: trước đây tone chỉ vào khối persona dưới dạng một chữ
# ("tông ma mị") và model tự hiểu — mà tự hiểu thì mỗi lượt một kiểu. Ba tông
# cuối dựng theo ba bản ghi thật của chủ máy (đo 15/08: giọng vui tươi nữ 203 Hz
# nói 252 từ/phút, ma mị nam 137 Hz nói 216 từ/phút, ấm áp nữ 229 Hz nói 241
# từ/phút) — chép lại đúng nết đã nghe được trong đó.
TONE_HINT: dict[str, str] = {
    "Thân thiện": "gần gũi, hay hỏi han, không khách sáo",
    "Nghiêm túc": "đi thẳng việc, câu gọn, không đùa",
    "Hài hước": "tếu nhẹ đúng lúc, không cợt nhả",
    "Châm biếm": "mỉa nhẹ có duyên, không xúc phạm",
    "Dịu dàng": "êm và chậm, an ủi trước rồi mới khuyên",
    "Lịch sự": "đúng mực, đủ chủ ngữ, không suồng sã",
    "Vui tươi": "hào hứng, khen thật lòng; tin xấu nói nhẹ rồi chuyển ngay "
                "sang cách xoay xở",
    "Ma mị": "trầm và nhẩn nha, ví von mờ ảo; rùng rợn ở CÁCH VÍ chứ không doạ, "
             "số liệu vẫn đúng tuyệt đối, không thêm điềm gở",
    "Ấm áp": "chăm sóc: mỗi con số kèm một việc nên làm; khen ngắn, không tâng bốc",
    # Chất "đại ca nghĩa khí" nằm ở nhịp nói và lối coi trọng anh em, KHÔNG ở
    # chửi bới: bot chửi tục hay doạ dẫm thì hết đường dùng trong nhà, mà cũng
    # không phải thứ làm nên chất giang hồ trong phim.
    "Giang hồ": "câu ngắn và gằn, dứt khoát, trọng nghĩa khí; hay 'anh em', "
                "'sòng phẳng', 'đàng hoàng'; KHÔNG chửi tục, không doạ nạt, "
                "không xúi làm bậy",
}

# Sociolect nén theo nghề (tự sinh khi Web UI chỉ chọn 4 mục).
#: Nghề tả bằng TỪ NGHỀ hay dùng và cách quy vấn đề về chuyên môn của mình —
#: đó mới là thứ làm bác sĩ khác kỹ sư khi cùng nói một câu. "Cẩn trọng, chính
#: xác" thì nghề nào chẳng nhận.
JOB_HINT: dict[str, str] = {
    "Sinh viên": "ví dụ từ bài vở, deadline, đi làm thêm; hay 'chắc là', "
                 "'em thử xem'",
    "Dân IT": "chêm 'chạy được', 'lỗi', 'thử lại xem'; quy vấn đề về nguyên "
              "nhân và cách kiểm chứng",
    "Giáo viên": "chia việc thành bước, hỏi lại 'hiểu chưa', khen đúng chỗ; "
                 "ví dụ dễ hình dung",
    "Bác sĩ": "hỏi triệu chứng trước khi kết luận, nói rõ cái gì chắc cái gì "
              "chưa, dặn theo dõi và khi nào cần đi khám",
    "Kinh doanh": "quy về số và thời hạn, hỏi 'được gì mất gì', chốt phương án",
    "Bán hàng chợ": "nói nhanh, tiếng đệm dày, trả treo có duyên, hay hỏi "
                    "'lấy hông'",
    "Tài xế": "chuyện đường sá, giờ kẹt xe, quãng đường; nói thẳng, ngắn",
    "Kỹ sư": "con số và dung sai, mô tả theo trình tự, không nói quá",
    "Văn phòng": "đúng mực công sở, hay 'em gửi lại anh/chị', nhắc mốc thời hạn",
    "Nông dân": "ví von mùa vụ thời tiết, chất phác, tin vào cái thấy tận mắt",
    "Sale": "khen khéo, gợi nhu cầu, dẫn dần tới chốt; không ép",
    "Massage": "hỏi han ân cần, nhắc thư giãn và giữ sức, giọng nhẹ đều",
    "Gái bán hoa": "ngọt ngào lả lơi, khen khéo, chiều lòng người nghe",
}


def ui_options() -> dict:
    """Danh sách lựa chọn cho Web UI (4 mục chọn + phụ)."""
    d = {f: opts for f, _l, opts in STEPS}
    return {"regions": d["region"], "genders": d["gender"], "ages": AGES,
            "jobs": d["job"], "traits": d["trait"], "voices": d["voice"],
            "tones": d["tone"], "styles": d["style"]}


# GIỌNG & NGÔN NGỮ chi tiết theo vùng (đệm/từ/chất giọng) — mẫu chuẩn user.
REGION_STYLE: dict[str, dict[str, str]] = {
    "Miền Tây": {"chat": "ngọt xuề xoà, thân như người nhà",
                 "dem": "nha, nghen, dợ, hen, hôn",
                 "tu": "dạ, hông, thiệt hông, sao dợ, quá trời"},
    "Sài Gòn": {"chat": "cởi mở năng động",
                "dem": "nha, á, luôn, ghê",
                "tu": "dạ, hông, dữ dội, quá chừng"},
    "Hà Nội": {"chat": "thanh lịch từ tốn",
               "dem": "nhỉ, nhé, ạ, cơ mà",
               "tu": "vâng, thế ạ, đúng rồi ạ"},
    "Miền Bắc": {"chat": "chuẩn mực ý tứ",
                 "dem": "nhé, ạ, cơ mà",
                 "tu": "vâng, thế à, đúng rồi"},
    "Hải Phòng": {"chat": "thẳng thắn nhịp mạnh",
                  "dem": "luôn, đấy, cơ",
                  "tu": "chuẩn, thẳng luôn, đấy nhé"},
    "Nghệ An": {"chat": "chân chất thân tình",
                "dem": "mô, tê, răng, rứa",
                "tu": "chắc, ni, nớ, rứa hầy"},
    "Huế": {"chat": "nhẹ nhàng từ tốn",
            "dem": "chi, mô, răng, rứa, hỉ",
            "tu": "dạ thưa, rứa hỉ, chừ"},
    "Đà Nẵng": {"chat": "thoải mái dễ chịu",
                "dem": "chi rứa, hỉ, nghe",
                "tu": "răng ri, chừ, quá hè"},
}


def _xung(g: str, a: str) -> str:
    """Xưng hô mặc định theo giới + band tuổi (vd 'Xưng em, gọi anh/chị')."""
    if g in ("Bé gái", "Bé trai"):
        return "Xưng con/cháu, gọi cô/chú/bác"
    young = a in ("Bé (6-12)", "Teen (13-17)", "18-25 tuổi",
                  "Thanh niên (18-25)", "")
    if young:
        return "Xưng em, gọi anh/chị" if g else ""
    if a in ("26-40 tuổi", "Trưởng thành (26-40)"):
        return "Xưng em/mình theo vai, gọi anh/chị"
    if a == "Trung niên (41-60)":
        return ("Xưng cô, gọi anh/chị/em theo vai" if g == "Nữ"
                else "Xưng chú, gọi anh/chị/em theo vai")
    if a == "Lớn tuổi (60+)":
        return ("Xưng bà, gọi con/cháu" if g == "Nữ" else "Xưng ông, gọi con/cháu")
    return ""


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

    Phân giải: key ĐÚNG phiên trước (user-trong-nhóm/1-1); chưa có thì fallback
    key cấp NHÓM (admin cài cho cả nhóm, user chưa cài riêng dùng chung).

    Nhóm Telegram bật Topics: key mang '#topic' ('chat#7:u55') → thử hẹp → rộng:
    user-trong-topic → user-cả-nhóm → topic → nhóm. Key không '#' đi 2 bước cũ."""
    key = str(user_id)
    with _LOCK:
        data = _load()
    keys = [key]
    base, _, uid = key.partition(":u")
    if "#" in base:
        group = base.split("#", 1)[0]
        if uid:
            keys.append(f"{group}:u{uid}")   # user cài ở cấp nhóm
        keys.append(base)                    # persona của topic
        keys.append(group)                   # persona cả nhóm
    elif uid:
        keys.append(base)
    for k in keys:
        entry = data.get(k)
        if entry is not None:
            return str((entry or {}).get("prompt") or "")
    return ""


# ── Giọng TTS theo persona (item: voice tone theo persona) ──────────────────
# Tông tĩnh gợi ý từ bước 'tone' → style VieNeu (caller vẫn ưu tiên tính chất
# từng câu qua voice.tone.style_for; đây chỉ là bias khi câu trung tính).
_TONE_STYLE: dict[str, str] = {
    "Nghiêm túc": "tin_tuc",
    "Lịch sự": "tin_tuc",
    "Dịu dàng": "doc_truyen",
    "Hài hước": "tu_nhien",
    "Châm biếm": "tu_nhien",
    "Thân thiện": "tu_nhien",
    # Tông thêm 15/08. Thiếu ở bảng này thì persona vẫn chạy nhưng giọng đọc
    # rơi về kiểu trung tính — chọn "Ma mị" mà máy đọc giọng bản tin thì công
    # dựng persona đổ sông.
    "Vui tươi": "tu_nhien",
    "Ma mị": "doc_truyen",     # nhẩn nha, ngắt nhiều — hợp lối kể chuyện
    "Ấm áp": "doc_truyen",
    "Giang hồ": "tu_nhien",    # nhịp nói đời thường, dứt khoát
}
# Preset lưu sel={"preset": tên} nên không có gender có cấu trúc — map sẵn.
_PRESET_GENDER: dict[str, str] = {
    "Cô gái miền Tây": "Nữ",
    "Bà bán cá ngoài chợ": "Nữ",
    "Cô gái Hà Nội gốc": "Nữ",
    "Nam thanh niên Hải Phòng": "Nam",
    "Dân IT trẻ": "Nam",
    "Cô giáo dịu dàng": "Nữ",
}
_FEMALE = {"Nữ", "Bé gái"}
_MALE = {"Nam", "Bé trai"}


def _pick_vieneu_voice(gender: str) -> str:
    """Chọn 1 giọng VieNeu đã cài theo giới → 'vieneu:<Tên>'. '' nếu không rõ /
    không có giọng khớp (an toàn: caller rơi về giọng mặc định, không đoán bừa)."""
    g = str(gender or "").strip()
    if not g:
        return ""
    try:
        from services.voice import config as vcfg
        voices = vcfg.vieneu_voices()
    except Exception:
        return ""
    if not voices:
        return ""
    female = g in _FEMALE
    male = g in _MALE
    for v in voices:
        vg = str(v.get("gender") or "").strip().lower()
        is_f = vg.startswith("f") or vg.startswith("w") or "nữ" in vg or vg.startswith("nu")
        is_m = (not is_f) and (vg.startswith("m") or "nam" in vg)
        if (female and is_f) or (male and is_m):
            return f"{vcfg.VIENEU_PREFIX}{v.get('name')}"
    return ""


def voice_for(user_id: str) -> dict:
    """Giọng + tông tĩnh cho TTS theo persona của PHIÊN.

    Trả {'voice': 'vieneu:<Tên>'|'', 'style': ''|'tin_tuc'|'doc_truyen'|'tu_nhien'}.
    Fallback key cấp nhóm giống prompt_for. Không có persona → {'', ''}.
    """
    key = str(user_id)
    with _LOCK:
        data = _load()
    entry = data.get(key)
    if entry is None and ":u" in key:
        entry = data.get(key.split(":u", 1)[0])
    sel = (entry or {}).get("sel") or {}
    if not isinstance(sel, dict):
        sel = {}
    gender = str(sel.get("gender") or "")
    if not gender and sel.get("preset"):
        gender = _PRESET_GENDER.get(str(sel.get("preset")), "")
    tone = str(sel.get("tone") or "")
    return {"voice": _pick_vieneu_voice(gender),
            "style": _TONE_STYLE.get(tone, "")}


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
    g = str(sel.get("gender") or "")
    a = str(sel.get("age") or "")
    region = str(sel.get("region") or "")
    job = str(sel.get("job") or "")
    bits = [b for b in (g, a, region, job) if b]
    parts = ["NHÂN VẬT: " + (", ".join(bits) if bits else "tuỳ chỉnh") + "."]
    xh = _xung(g, a)
    if xh:
        parts.append(xh + ".")
    # Nét: trait tự chọn + nét của TUỔI và NGHỀ. Bản trước chỉ lấy nét tuổi/nghề
    # khi KHÔNG chọn gì khác, nên càng chọn kỹ persona càng nhạt: chọn tone là
    # mất luôn "chững chạc, thực tế" của band 26-40 và "chêm thuật ngữ" của dân
    # IT. Nay tuổi và nghề luôn góp mặt — đó chính là hai chiều làm nhân vật
    # khác nhau nhiều nhất khi cùng một tông.
    net: list[str] = []
    if sel.get("trait"):
        net.append(sel["trait"].lower())
    net.extend(h for h in (AGE_HINT.get(a), GENDER_HINT.get(g),
                           JOB_HINT.get(job)) if h)
    if net:
        parts.append("Nét: " + "; ".join(net) + "; nói tự nhiên như người quen.")
    # Ghi RIÊNG voice và tone. Bản cũ nối chuỗi kiểu "Giọng " + ", tông ".join()
    # nên chỉ đúng khi có ĐỦ hai: chọn mỗi tông thì ra "Giọng ma mị" — gọi tông
    # thành giọng, mà giọng với tông là hai chiều khác nhau của nhân vật.
    mo_ta = []
    if sel.get("voice"):
        mo_ta.append(f"giọng {str(sel['voice']).lower()}")
    if sel.get("tone"):
        mo_ta.append(f"tông {str(sel['tone']).lower()}")
    if mo_ta:
        parts.append(", ".join(mo_ta).capitalize() + ".")
    # Tông ghi kèm CÁCH CƯ XỬ, không để model tự hiểu một tính từ.
    goi_y_tone = TONE_HINT.get(str(sel.get("tone") or ""))
    if goi_y_tone:
        parts.append(f"Tông ấy nghĩa là: {goi_y_tone}.")
    if sel.get("style"):
        parts.append(f"Phong cách {sel['style'].lower()}.")
    # GIỌNG & NGÔN NGỮ chi tiết theo vùng (đệm/từ/kiểu cười/câu nói giảm)
    st = REGION_STYLE.get(region)
    if st:
        # Kiểu cười nay nằm trong GENDER_HINT — để ở cả hai chỗ thì vừa tốn
        # token vừa mâu thuẫn ("cười haha" của nam đụng "cười thoải mái").
        toi = "em" if (xh.startswith("Xưng em") or xh.startswith("Xưng con")) else "mình"
        parts.append(
            f"GIỌNG & NGÔN NGỮ: {st['chat']}. Đệm: {st['dem']}. "
            f"Từ hay dùng: {st['tu']}. Góp ý thì nói giảm: 'hình như chỗ này "
            f"hơi nhầm, xem lại giúp {toi} nhé'."
        )
    elif DIALECT.get(region):
        parts.append(f"Phương ngữ: {DIALECT[region]}.")
    parts.append(_SUFFIX)
    # Bọc thẻ để model tách được LỚP ÁO khỏi VIỆC CẦN LÀM. Khối này đi kèm mọi
    # lượt chat, đứng lẫn với chỉ dẫn công việc trong cùng system prompt; không
    # có ranh giới thì câu "câu ngắn, dứt khoát" của nhân vật dễ bị hiểu thành
    # luật cho cả câu trả lời việc.
    return "<nhan_vat>\n" + " ".join(parts) + "\n</nhan_vat>"


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
