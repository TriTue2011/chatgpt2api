"""Ra bài tập BA MỨC từ BÀI MẪU trong kho, không sinh từ hư không.

Vì sao cần module riêng thay vì dùng `teacher_assess.make_quiz`: cái đó có tham
số `difficulty` nhưng sinh câu bằng `random` trong `_math_item` — số ngẫu nhiên
theo khoảng đã lập trình cứng, KHÔNG đọc bài mẫu nào. Hệ quả: câu ra đúng phép
tính nhưng sai KIỂU ra đề của sách (sách lớp 4 hỏi "điền dấu >, <, =", nó ra
"tính 234 + 567"), và với môn không phải Toán/Anh/Văn thì không có gì để sinh.

Ở đây gốc là BÀI MẪU thật trong `kb_giao_duc_vbt` (vở/sách bài tập). Ba mức:

  · sát        — CÙNG kĩ năng, CÙNG cấu trúc câu hỏi, chỉ đổi số/tên. Học sinh
                 vừa xem bài mẫu phải làm được ngay. Không thêm bước nào.
  · trung bình — thêm ĐÚNG MỘT bước, hoặc đảo chiều ẩn số, hoặc số lớn hơn.
  · khó        — nhiều bước / ghép hai kĩ năng / đặt vào tình huống thực tế.

Giới hạn quan trọng: "nâng tầm độ khó" KHÔNG được vượt chương trình của lớp.
Nâng khó bằng cách dùng kiến thức lớp trên là ra đề học sinh không thể làm, mà
nhìn vào đề thì không thấy sai ở đâu. Nên mức khó lấy thêm gợi ý phân hoá từ SGV
(`ask_sgv` — "gợi ý cho học sinh khá", "lỗi thường gặp") chứ không tự nghĩ ra
cách làm khó.

KHÔNG CÓ BÀI MẪU THÌ NÓI KHÔNG CÓ. Kho VBT phần lớn là bài mẫu vài trang
(135/145 quyển), nhiều lớp–môn chưa có gì. Sinh bừa khi kho rỗng là thứ tệ nhất:
đề trông y như đề có căn cứ, giáo viên không phân biệt được. `grounded=False`
được trả về và câu nào cũng mang `nguon="tự soạn"`.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

from services.config import DATA_DIR

logger = logging.getLogger(__name__)

_ROOT = Path(DATA_DIR) / "agent" / "teacher" / "bai_tap"

# Ba mức, theo THỨ TỰ tăng dần. Mã dùng trong JSON/API là chữ không dấu để không
# phụ thuộc encoding của phía gọi; nhãn tiếng Việt để hiện cho giáo viên.
MUC = ("sat", "trung_binh", "kho")
MUC_LABEL = {
    "sat": "Sát bài mẫu",
    "trung_binh": "Trung bình",
    "kho": "Khó",
}

# Mô tả từng mức đi THẲNG vào prompt. Đây là chỗ duy nhất định nghĩa "khó" nghĩa
# là gì — để rải mô tả ở nhiều nơi thì mỗi lần sửa một chỗ, ba mức lệch nhau.
MUC_YEU_CAU = {
    "sat": (
        "CÙNG kĩ năng và CÙNG cấu trúc câu hỏi với bài mẫu, chỉ thay số liệu, "
        "tên riêng, đồ vật. Số phải cùng độ lớn với bài mẫu. TUYỆT ĐỐI không "
        "thêm bước tính, không đổi dạng hỏi. Học sinh vừa đọc bài mẫu phải làm "
        "được ngay."
    ),
    "trung_binh": (
        "Nâng lên ĐÚNG MỘT bậc so với bài mẫu, chọn MỘT trong ba cách: thêm "
        "đúng một bước tính; đảo chiều ẩn số (cho kết quả, tìm số ban đầu); "
        "hoặc tăng độ lớn số liệu sang mốc kế tiếp. Vẫn đúng một dạng bài đó."
    ),
    "kho": (
        "Nhiều bước, hoặc ghép hai kĩ năng đã học, hoặc đặt vào tình huống thực "
        "tế phải tự rút ra dữ kiện. Được thêm dữ kiện gây nhiễu nhưng phải giải "
        "được. CHỈ dùng kiến thức trong chương trình của lớp này — khó vì nhiều "
        "bước, KHÔNG vì dùng kiến thức lớp trên."
    ),
}

_SCHEMA = (
    '{"items":[{"muc":"sat|trung_binh|kho","de":"đề bài cho học sinh",'
    '"dap_an":"đáp án","loi_giai":"các bước giải ngắn",'
    '"ki_nang":"kĩ năng bài này luyện","tu_bai_mau":"câu mẫu đã dựa vào"}]}'
)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-") or "x"


# ── Lấy bài mẫu từ kho ─────────────────────────────────────────────────────

# Mốc nhận dạng đoạn TỪ KHO trong câu trả lời của hub. `format_hybrid_results`
# mở đầu phần kho bằng "## Kho tri thức", và mỗi đoạn ghi `nguồn: ...`.
_MOC_KHO = "## Kho tri thức"
_MOC_NGUON = "nguồn:"
# Mốc mở đầu phần TÌM WEB mà `kb_ask` NỐI THÊM khi `_needs_live(question)` đúng.
_MOC_WEB = ("## Tìm kiếm quốc tế", "### CrossRef", "## Kết quả tìm kiếm",
            "💡 *Dữ liệu từ kho tri thức")


def _kb(tool: str, args: dict[str, Any]) -> str:
    """Hỏi một tool của MCP kb_giao_vien. Dùng lại đúng đường của bài giảng —
    không mở kết nối Chroma thứ hai từ tiến trình app (hub đang giữ sqlite)."""
    from services.agent import teacher_lecture as tl
    return tl._kb(tool, args)


def _chi_phan_kho(tra_loi: str) -> str:
    """Giữ đúng phần TỪ KHO, cắt bỏ phần hub tìm thêm trên web.

    Vì sao BẮT BUỘC: `kb_ask` của hub trả `kb_text + live_text` — hỏi kho xong
    nếu `_needs_live()` đúng thì nó NỐI THÊM kết quả tìm web. Kho miss thì
    `kb_text` rỗng và câu trả lời chỉ còn phần web.

    Đo thật 2026-07-30, gọi `ask_bai_tap(lớp 4 Toán phép cộng bài tập)`:

        ## Tìm kiếm quốc tế (12 kết quả từ 4 nguồn)
        ### CrossRef (3)
        1. **SỬ DỤNG MÔ HÌNH LSTM NHIỀU TẦNG VÀO BÀI TOÁN TÌM KIẾM CÂU HỎI**
           https://doi.org/10.34238/tnu-jst.5799

    Đó là danh mục bài báo khoa học, không phải bài mẫu của vở bài tập. Coi chuỗi
    không rỗng là "có bài mẫu" thì module này ra đề "sát bài mẫu" dựa trên tiêu đề
    luận văn về LSTM, và vẫn báo `grounded.bai_mau=True` — giáo viên không có cách
    nào biết. Nên chỉ nhận phần có mốc kho, và phải có ít nhất một dòng `nguồn:`.
    """
    t = (tra_loi or "").strip()
    if not t or _MOC_KHO not in t:
        return ""
    t = t[t.index(_MOC_KHO):]
    for moc in _MOC_WEB:
        if moc in t:
            t = t[:t.index(moc)]
    t = t.strip().rstrip("-").strip()
    # Có tiêu đề kho mà không đoạn nào ghi nguồn ⇒ không phải nội dung sách.
    return t if _MOC_NGUON in t else ""


def bai_mau(grade: int, subject: str, *, bai: str = "", topic: str = "",
            top_k: int = 4) -> dict[str, Any]:
    """Bài mẫu + gợi ý phân hoá cho một lớp–môn–bài.

    Trả cả `co_mau` để phía trên biết đề sắp ra có căn cứ hay không. Đây không
    phải chi tiết nội bộ: đề "tự soạn" và đề "dựa bài mẫu của sách" khác nhau về
    độ tin cậy, mà nhìn vào đề thì không phân biệt được.
    """
    from services.agent import teacher_workspace as tw

    g = int(grade or 0)
    sub = tw._normalize_subject(subject) or ""
    mon = tw.SUBJECT_LABEL.get(sub, sub or subject)
    hoi = (bai or topic or "").strip()
    # LUÔN lọc lop+mon: kho gộp cả 12 lớp và embedding không mang thông tin lớp
    # (đo thật trên kb_giao_duc: 4/12 khi tìm theo ngữ nghĩa, 12/12 khi lọc).
    loc = {"lop": g, "mon": sub} if sub else {"lop": g}
    k = max(1, min(int(top_k or 4), 8))

    cau_hoi = f"lớp {g} {mon} {hoi} bài tập dạng gì, mẫu câu hỏi".strip()
    # `_chi_phan_kho` ở MỌI lời gọi: cả ba tool đều đi qua `kb_ask`, nên cả ba
    # đều có thể trả về kết quả tìm web khi kho miss.
    mau = _chi_phan_kho(_kb("ask_bai_tap", {"question": cau_hoi, "top_k": k, **loc}))
    # SGV cho MỨC KHÓ: cách làm khó phải theo gợi ý phân hoá của sách, không tự
    # nghĩ. Cũng là nguồn "lỗi thường gặp" để đề chạm đúng chỗ học sinh hay sai.
    phan_hoa = _chi_phan_kho(_kb("ask_sgv", {
        "question": f"lớp {g} {mon} {hoi}: gợi ý cho học sinh khá, bài tập nâng "
                    f"cao, lỗi học sinh thường gặp",
        "top_k": 3, **loc}))
    # SGK để neo phạm vi kiến thức đã học tới bài này.
    noi_dung = _chi_phan_kho(_kb("ask_sgk", {
        "question": f"lớp {g} {mon} {hoi}: nội dung bài, kiến thức cần đạt",
        "top_k": 3, **loc}))
    return {
        "grade": g, "subject": sub, "mon": mon, "bai": hoi,
        "mau": mau, "phan_hoa": phan_hoa, "noi_dung": noi_dung,
        "co_mau": bool(mau.strip()),
    }


# ── Ra đề ──────────────────────────────────────────────────────────────────

def _prompt(ng: dict[str, Any], so_cau: dict[str, int]) -> tuple[str, str]:
    g, mon, hoi = ng["grade"], ng["mon"], ng["bai"]
    dong_muc = "\n".join(
        f"- {MUC_LABEL[m]} (`{m}`), {so_cau.get(m, 0)} câu: {MUC_YEU_CAU[m]}"
        for m in MUC if so_cau.get(m, 0) > 0
    )
    sys_p = (
        f"Bạn là giáo viên Việt Nam ra bài tập cho học sinh lớp {g}, môn {mon}. "
        f"Trả JSON thuần đúng schema:\n{_SCHEMA}\n\n"
        f"BA MỨC ĐỘ — làm đúng yêu cầu từng mức:\n{dong_muc}\n\n"
        "Quy tắc bắt buộc:\n"
        "1. Mức `sat` phải soi theo BÀI MẪU: cùng dạng hỏi, cùng độ lớn số. "
        "Ghi câu mẫu đã dựa vào ở `tu_bai_mau`.\n"
        "2. Chỉ dùng kiến thức trong chương trình lớp "
        f"{g} và đã học tới bài này. Nâng khó bằng số bước, KHÔNG bằng kiến thức "
        "lớp trên.\n"
        "3. Mỗi câu PHẢI có `dap_an` đúng và `loi_giai` các bước — đề không có "
        "đáp án thì giáo viên không dùng được.\n"
        "4. Tiếng Việt tự nhiên, đúng cách gọi của sách. Không chép nguyên văn "
        "bài mẫu làm đề — đổi số liệu và tên.\n"
        "5. Không dùng dữ kiện ngoài đề; số liệu phải chia hết/ra kết quả đẹp "
        "đúng mức của lớp."
    )
    if not ng["co_mau"]:
        sys_p += (
            "\n\nLƯU Ý: kho KHÔNG có bài mẫu cho bài này. Hãy ra đề theo chuẩn "
            f"chương trình lớp {g}, và mọi câu ghi `tu_bai_mau` là "
            '"không có bài mẫu trong kho".'
        )
    ten_bai = hoi or "(chưa nêu — theo chương trình lớp)"
    user_p = (
        f"Lớp {g} · môn {mon} · bài/chủ đề: {ten_bai}\n\n"
        f"BÀI MẪU TỪ VỞ/SÁCH BÀI TẬP (gốc để ra mức sát):\n"
        f"{(ng['mau'] or '(kho chưa có bài mẫu cho bài này)')[:2600]}\n\n"
        f"NỘI DUNG SGK (phạm vi kiến thức được dùng):\n"
        f"{(ng['noi_dung'] or '(kho chưa có)')[:1600]}\n\n"
        f"GỢI Ý PHÂN HOÁ TỪ SGV (dùng cho mức khó):\n"
        f"{(ng['phan_hoa'] or '(kho chưa có)')[:1600]}"
    )
    return sys_p, user_p


def _chuan_de_so(s: str) -> str:
    """Bỏ dấu, bỏ khoảng trắng, hạ chữ thường — để đối chiếu trích dẫn."""
    import unicodedata
    t = unicodedata.normalize("NFD", str(s or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", t.replace("đ", "d"))


def _doi_chieu_dan_mau(items: list[dict[str, Any]], mau: str) -> None:
    """Đánh dấu câu nào có `tu_bai_mau` ĐỐI CHIẾU ĐƯỢC trong bài mẫu đã lấy.

    Vì sao cần: `tu_bai_mau` là do MODEL tự khai. Đo thật 2026-07-30 (lớp 4 Toán,
    kho chỉ có 4 trang đầu của vở bài tập = bìa + lời nói đầu + mục lục): model
    ghi «Dựa bài mẫu: Đặt tính rồi tính: 23 456 + 12 341» — một câu KHÔNG có
    trong phần kho đã lấy. Đề vẫn đúng chương trình, nhưng dòng "dựa bài mẫu" là
    lời khai không kiểm chứng, mà nó chính là thứ giáo viên tin để khỏi đọc lại.

    Cách đối chiếu: so trên chuỗi đã bỏ dấu/khoảng trắng, cắt cụm 12 ký tự —
    model đổi số liệu và cách viết dấu cộng, nên so nguyên văn sẽ luôn "không
    khớp" và cảnh báo mất giá trị.
    """
    goc = _chuan_de_so(mau)
    for r in items:
        dan = _chuan_de_so(r.get("tu_bai_mau") or "")
        if not dan or not goc:
            r["dan_mau_kiem_chung"] = False
            continue
        # Cụm 12 ký tự liên tiếp nào của trích dẫn cũng nằm trong bài mẫu → coi
        # như có căn cứ. Ngắn hơn thì "tinh" hay "bai" cũng khớp, dài hơn thì đổi
        # một số liệu là trượt.
        n = 12
        r["dan_mau_kiem_chung"] = any(
            dan[i:i + n] in goc for i in range(max(1, len(dan) - n + 1)))


def _lam_sach(items: Any, so_cau: dict[str, int]) -> list[dict[str, Any]]:
    """Giữ đúng câu dùng được, gắn lại `muc` theo hạn ngạch đã xin.

    Vì sao phải tự gắn lại: model hay trả `muc` sai chính tả ("trung bình",
    "medium", "khó") hoặc dồn hết vào một mức. Nếu tin nguyên `muc` của model thì
    đề "ba mức" có thể ra ba câu cùng mức mà không ai thấy — đúng lỗi khó phát
    hiện nhất, vì mỗi câu riêng lẻ đều hợp lệ.
    """
    _MAP = {
        "sat": "sat", "sát": "sat", "closest": "sat", "de": "sat", "dễ": "sat",
        "easy": "sat", "co_ban": "sat", "cơ bản": "sat",
        "trung_binh": "trung_binh", "trung binh": "trung_binh",
        "trung bình": "trung_binh", "medium": "trung_binh", "tb": "trung_binh",
        "kho": "kho", "khó": "kho", "hard": "kho", "nang_cao": "kho",
        "nâng cao": "kho",
    }
    con: dict[str, int] = {m: int(so_cau.get(m, 0) or 0) for m in MUC}
    ra: list[dict[str, Any]] = []
    cho_sau: list[dict[str, Any]] = []

    for raw in (items if isinstance(items, list) else []):
        if not isinstance(raw, dict):
            continue
        de = str(raw.get("de") or raw.get("question") or "").strip()
        if not de:
            continue
        row = {
            "de": de[:1200],
            "dap_an": str(raw.get("dap_an") or raw.get("answer") or "").strip()[:600],
            "loi_giai": str(raw.get("loi_giai") or raw.get("solution") or "").strip()[:1200],
            "ki_nang": str(raw.get("ki_nang") or "").strip()[:200],
            "tu_bai_mau": str(raw.get("tu_bai_mau") or "").strip()[:400],
        }
        m = _MAP.get(str(raw.get("muc") or "").strip().lower())
        if m and con.get(m, 0) > 0:
            con[m] -= 1
            ra.append({**row, "muc": m})
        else:
            cho_sau.append(row)

    # Câu không rõ mức (hoặc mức đã đủ) đổ vào mức còn thiếu, theo thứ tự dễ →
    # khó: thiếu câu ở một mức còn tệ hơn là gán mức chưa chắc chắn.
    for row in cho_sau:
        m = next((x for x in MUC if con.get(x, 0) > 0), None)
        if m is None:
            break
        con[m] -= 1
        ra.append({**row, "muc": m, "muc_do_suy": True})

    ra.sort(key=lambda r: MUC.index(r["muc"]))
    for i, r in enumerate(ra, 1):
        r["id"] = f"c{i}"
    return ra


def tao(
    *,
    grade: int,
    subject: str,
    bai: str = "",
    topic: str = "",
    so_moi_muc: int = 2,
    muc: tuple[str, ...] | list[str] = MUC,
    student_key: str = "",
) -> dict[str, Any]:
    """Ra bài tập ba mức cho một lớp–môn–bài. Lưu lại để chấm sau.

    `so_moi_muc` là số câu MỖI mức (1–6). Xin nhiều hơn thì model bắt đầu lặp
    lại chính nó — đo trên bài Toán 4: quá 6 câu một mức là các câu chỉ khác số.
    """
    from services.agent import teacher_workspace as tw

    g = int(grade or 0)
    if g not in tw.GRADES:
        return {"ok": False, "error": f"lớp phải 1–12, nhận {grade}"}
    sub = tw._normalize_subject(subject)
    if not sub:
        return {"ok": False, "error": f"không nhận ra môn: {subject}"}
    n = max(1, min(int(so_moi_muc or 2), 6))
    xin = tuple(m for m in MUC if m in set(muc or MUC)) or MUC
    so_cau = {m: n for m in xin}

    ng = bai_mau(g, sub, bai=bai, topic=topic)
    sys_p, user_p = _prompt(ng, so_cau)

    from services.agent.runtime import call_model, content_of
    from services.agent.teacher_classroom import _parse_json_obj, _teacher_model

    resp = call_model(
        _teacher_model("write"),
        [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}],
        timeout=180, max_tokens=2600, no_smart_home=True,
        # BẮT BUỘC: nói rõ đây là request JSON. Không có nó thì bước đổi sang văn
        # xuôi (cho TTS) xoá { } " : và cả dấu +, JSON về tới đây không parse được
        # — model trả đúng nội dung mà module báo "không trả đúng dạng".
        response_format={"type": "json_object"},
    )
    if resp.get("error"):
        return {"ok": False, "error": f"model lỗi: {str(resp.get('error'))[:160]}"}
    data = _parse_json_obj(content_of(resp)) or {}
    items = _lam_sach(data.get("items"), so_cau)
    if not items:
        return {"ok": False, "error": "model không trả đúng dạng bài tập — thử lại"}
    _doi_chieu_dan_mau(items, ng["mau"])

    thieu = {m: so_cau[m] - sum(1 for r in items if r["muc"] == m)
             for m in xin}
    bo = {
        "id": f"{_slug(f'lop{g}-{sub}-{bai or topic}')}-{int(time.time())}",
        "grade": g, "subject": sub, "mon": ng["mon"],
        "bai": ng["bai"], "student_key": student_key,
        "so_moi_muc": n, "muc": list(xin),
        "items": items,
        # Đây là thứ giáo viên cần thấy TRƯỚC khi dùng đề: có dựa bài mẫu của
        # sách hay không, và mức nào bị thiếu câu.
        "grounded": {"bai_mau": ng["co_mau"], "sgk": bool(ng["noi_dung"]),
                     "sgv": bool(ng["phan_hoa"])},
        "thieu_cau": {k: v for k, v in thieu.items() if v > 0},
        "created": time.strftime("%Y-%m-%d %H:%M"),
        "model_used": _teacher_model("write"),
    }
    _luu(bo)
    logger.info({"event": "teacher_bai_tap", "grade": g, "subject": sub,
                 "bai": ng["bai"], "so_cau": len(items),
                 "co_bai_mau": ng["co_mau"], "thieu": bo["thieu_cau"]})
    return {"ok": True, "bo_de": bo}


# ── Lưu / đọc lại ──────────────────────────────────────────────────────────

def _luu(bo: dict[str, Any]) -> None:
    try:
        _ROOT.mkdir(parents=True, exist_ok=True)
        p = _ROOT / f"{bo['id']}.json"
        p.write_text(json.dumps(bo, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    except Exception as exc:
        logger.warning("teacher_bai_tap: ghi %s lỗi %s", bo.get("id"), exc)


def doc(bo_id: str) -> Optional[dict[str, Any]]:
    try:
        p = _ROOT / f"{_slug(bo_id)}.json"
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    # Không tìm được theo slug thì quét — id có dấu thời gian nên slug có thể
    # lệch nếu phía gọi tự dựng lại.
    try:
        for p in _ROOT.glob("*.json"):
            if p.stem == bo_id:
                return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def liet_ke(*, grade: int = 0, subject: str = "", limit: int = 30) -> list[dict[str, Any]]:
    """Bộ đề đã ra, mới nhất trước. Chỉ trả phần đầu — không kéo cả câu hỏi."""
    ra: list[dict[str, Any]] = []
    try:
        for p in sorted(_ROOT.glob("*.json"), key=lambda x: x.stat().st_mtime,
                        reverse=True):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if grade and int(d.get("grade") or 0) != int(grade):
                continue
            if subject and str(d.get("subject") or "") != subject:
                continue
            ra.append({
                "id": d.get("id"), "grade": d.get("grade"),
                "subject": d.get("subject"), "mon": d.get("mon"),
                "bai": d.get("bai"), "created": d.get("created"),
                "so_cau": len(d.get("items") or []),
                "grounded": d.get("grounded") or {},
            })
            if len(ra) >= max(1, min(int(limit or 30), 200)):
                break
    except Exception as exc:
        logger.warning("teacher_bai_tap.liet_ke lỗi %s", exc)
    return ra


# ── Hiện ra cho người đọc ──────────────────────────────────────────────────

def format_cho_hoc_sinh(bo: dict[str, Any]) -> str:
    """Đề cho học sinh — KHÔNG kèm đáp án."""
    g, mon = bo.get("grade"), bo.get("mon") or bo.get("subject")
    dong = [f"**Bài tập lớp {g} · {mon}"
            + (f" · {bo.get('bai')}" if bo.get("bai") else "") + "**", ""]
    for m in MUC:
        cau = [r for r in (bo.get("items") or []) if r.get("muc") == m]
        if not cau:
            continue
        dong.append(f"### {MUC_LABEL[m]}")
        for i, r in enumerate(cau, 1):
            dong.append(f"{i}. {r.get('de')}")
        dong.append("")
    return "\n".join(dong).strip()


def format_cho_giao_vien(bo: dict[str, Any]) -> str:
    """Đề + đáp án + căn cứ. Nói thẳng chỗ chưa có căn cứ."""
    g, mon = bo.get("grade"), bo.get("mon") or bo.get("subject")
    gr = bo.get("grounded") or {}
    dong = [f"**Bài tập ba mức · lớp {g} · {mon}"
            + (f" · {bo.get('bai')}" if bo.get("bai") else "") + "**",
            f"_Mã bộ đề: `{bo.get('id')}` · {bo.get('created')}_", ""]
    if not gr.get("bai_mau"):
        dong += ["> ⚠️ Kho **chưa có bài mẫu** cho bài này — đề soạn theo chuẩn "
                 "chương trình, mức «sát bài mẫu» không có mẫu để soi. Hãy đọc "
                 "lại trước khi giao.", ""]
    if bo.get("thieu_cau"):
        thieu = ", ".join(f"{MUC_LABEL[k]} thiếu {v}"
                          for k, v in (bo.get("thieu_cau") or {}).items())
        dong += [f"> ⚠️ Chưa đủ số câu đã xin: {thieu}.", ""]
    for m in MUC:
        cau = [r for r in (bo.get("items") or []) if r.get("muc") == m]
        if not cau:
            continue
        dong.append(f"### {MUC_LABEL[m]} — {MUC_YEU_CAU[m][:80]}…")
        for i, r in enumerate(cau, 1):
            dong.append(f"**{i}. {r.get('de')}**")
            dong.append(f"- Đáp án: {r.get('dap_an') or '_(model không trả)_'}")
            if r.get("loi_giai"):
                dong.append(f"- Cách giải: {r['loi_giai']}")
            if r.get("ki_nang"):
                dong.append(f"- Kĩ năng: {r['ki_nang']}")
            if r.get("tu_bai_mau"):
                # Nói rõ trích dẫn có đối chiếu được hay không: dòng "dựa bài
                # mẫu" là thứ giáo viên tin để khỏi đọc lại, nên lời khai không
                # kiểm chứng được phải hiện ra là không kiểm chứng được.
                dau = "" if r.get("dan_mau_kiem_chung") else \
                    " _(⚠️ không đối chiếu được trong phần kho đã lấy — model tự nêu)_"
                dong.append(f"- Dựa bài mẫu: {r['tu_bai_mau']}{dau}")
            if r.get("muc_do_suy"):
                dong.append("- _Mức do hệ thống gán (model không ghi rõ mức)_")
            dong.append("")
    return "\n".join(dong).strip()
