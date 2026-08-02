"""Chấm điểm skill theo KẾT QUẢ dùng thật, và soi thân skill trước khi nhận.

VÌ SAO CẦN — chuỗi bằng chứng trong chính kho code này:

  1. Bot TỰ VIẾT được skill: `teach_skill` nhận lời người dùng trong chat rồi ghi
     `data/agent/skills/<slug>/SKILL.md`. Capability đó là `risk=READ` nên KHÔNG
     qua cổng duyệt — chỉ cần thread được tick nhóm `skills`.
  2. Mô tả của mọi skill đang bật vào system prompt MỌI LƯỢT CHAT (`router_block`).
  3. Khi khớp, thân skill được đưa cho model như một QUY TRÌNH ĐỂ LÀM THEO
     (`_h_use_skill` chỉ đọc file rồi trả nội dung).
  4. Model đang có tool điều khiển nhà, chạy lệnh shell trên máy đã cài agent, và
     SSH vào server.
  5. Không chỗ nào ghi lại skill nào được chọn, làm theo có xong việc không.

Điểm làm việc này rõ hơn: dự án ĐÃ hiểu đúng loại rủi ro đó ở chỗ khác —
`ocr_rules.INJECTION_GUARD` dặn model rằng chữ trong tài liệu là DỮ LIỆU, câu
trông như mệnh lệnh cũng chỉ chép lại. Nhưng thân skill — cũng là văn bản không
rõ nguồn gốc — thì được đối xử như MỆNH LỆNH, đúng theo thiết kế. Hai chỗ cùng
một loại vấn đề, một chỗ có bảo vệ, một chỗ chưa.

HAI VIỆC MODULE NÀY LÀM

  · Đếm kết quả: mỗi lần `use_skill` nạp thân skill thì ghi một lần DÙNG; cuối
    lượt, trạng thái lượt đó (`error` / `max_steps` / `blocked` là hỏng, còn lại
    là xong) được ghi cho đúng skill vừa dùng. Skill hỏng nhiều tự rút khỏi bộ
    định tuyến thay vì ngồi đó ăn context mỗi lượt.
  · Soi thân skill TỰ HỌC trước khi ghi: từ chối văn bản cố vô hiệu hoá hướng
    dẫn hệ thống, cố bỏ bước duyệt, nhồi lệnh phá hoại, hoặc đòi gửi bí mật ra
    ngoài. CHỈ soi skill do bot tự học — skill đóng gói sẵn là code đã xem xét.

Cách chấm điểm mượn nguyên của `account_service._selection_weight`: tỉ lệ thành
công làm trơn Laplace. Cùng bài toán "chấm một thứ theo kết quả quá khứ" thì dùng
cùng một công thức, khỏi có hai định nghĩa lệch nhau.

KHÔNG dùng thư viện ngoài, không dựng bảng mới: một file JSON bên cạnh kho skill,
khoá RLock, ghi kiểu tmp-rồi-thay — y hệt `voice/speakers.py` và
`voice/session_voice.py`.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

from services.config import DATA_DIR

logger = logging.getLogger(__name__)

_PATH = Path(DATA_DIR) / "agent" / "skill_quality.json"
_lock = threading.RLock()

# ── Ngưỡng ──────────────────────────────────────────────────────────────────
# Rút khỏi bộ định tuyến khi đã có ĐỦ mẫu mà điểm vẫn thấp. Chưa dùng lần nào thì
# KHÔNG phải là dở — không có dữ liệu khác với có dữ liệu xấu.
_DU_MAU = 4
_DIEM_TOI = 0.4
# Lên bậc "tin được": xong đủ nhiều và điểm cao.
_XONG_DE_TIN = 3
_DIEM_TIN = 0.6
# Người dùng bảo "thôi" thì không tính vào đâu cả — đó là ý người, không phải
# chất lượng skill.
_HONG = ("error", "max_steps", "blocked")
_KHONG_TINH = ("denied", "awaiting_approval")
# Lượt chat treo/mất tăm thì đừng gán kết quả cho skill của lượt trước.
_CHO_TOI_DA_GIAY = 900

# user_id -> (slug, lúc dùng). Cuối lượt mới biết xong hay hỏng, nên phải giữ tạm
# đúng như `approval_gate.set_pending` giữ đề nghị chờ duyệt.
_cho_ket_qua: dict[str, tuple[str, float]] = {}


# ── Soi thân skill ──────────────────────────────────────────────────────────
# Chỉ bắt Ý ĐỒ LÀM SAI, không bắt việc NHẮC TỚI thứ nhạy cảm. Đây là điều kiện
# sống còn của bộ soi: skill đóng gói sẵn `polite-guest-reply` có dòng "token, IP,
# tài khoản admin" (dặn ĐỪNG tiết lộ) và `van-hanh-he-thong` nói "log tự che
# token", "có sẵn mật khẩu ngay lúc hỏi". Một danh sách từ khoá thô sẽ chặn oan
# đúng những skill tốt nhất — test có phép đo chặn điều đó.
_CAM = (
    # 1) Vô hiệu hoá hướng dẫn hệ thống
    (re.compile(r"bỏ\s+qua\s+(mọi\s+|các\s+|toàn\s+bộ\s+)?(hướng\s+dẫn|quy\s+tắc|chỉ\s+dẫn|chỉ\s+thị)", re.I),
     "cố bảo bỏ qua hướng dẫn hệ thống"),
    (re.compile(r"ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+(instruction|rule|prompt)", re.I),
     "cố bảo bỏ qua hướng dẫn hệ thống"),
    (re.compile(r"quên\s+(hết\s+|sạch\s+|mọi\s+)?(quy\s+tắc|hướng\s+dẫn)", re.I),
     "cố bảo quên quy tắc hệ thống"),
    # 2) Bỏ bước duyệt — nguy hiểm vì cổng duyệt là thứ chặn hành động phá huỷ
    (re.compile(r"(tự\s+động\s+duyệt|tự\s+duyệt|bỏ\s+qua\s+(bước\s+)?duyệt|khỏi\s+(cần\s+)?duyệt)", re.I),
     "cố bỏ bước xin duyệt"),
    (re.compile(r"(không\s+cần|khỏi|đừng)\s+(phải\s+)?(hỏi|xin\s+phép|xác\s+nhận)\s+(lại\s+)?(chủ|người|ai)", re.I),
     "cố bỏ bước xin phép người dùng"),
    (re.compile(r"luôn\s+(chọn|trả\s+lời|đáp)\s*[\"'“]?\s*luôn\s+luôn", re.I),
     "cố tự bấm «Luôn luôn» để khỏi bị hỏi nữa"),
    # 3) Lệnh phá hoại nhồi thẳng vào quy trình
    (re.compile(r"rm\s+-[a-z]*[rf][a-z]*\s+(/|~|\*|\$HOME)", re.I), "chứa lệnh xoá phá hoại"),
    (re.compile(r"\bmkfs(\.|\s)", re.I), "chứa lệnh format ổ đĩa"),
    (re.compile(r"\bdd\s+.*of=/dev/", re.I), "chứa lệnh ghi đè thiết bị khối"),
    (re.compile(r":\s*\(\s*\)\s*\{.*\|.*&\s*\}\s*;", re.S), "chứa fork bomb"),
    (re.compile(r"chmod\s+-?R?\s*777\s+/(\s|$)", re.I), "chứa lệnh mở toàn quyền thư mục gốc"),
    (re.compile(r">\s*/dev/(sd|nvme|disk)", re.I), "chứa lệnh ghi đè thiết bị khối"),
    # 4) Đòi gửi bí mật ra ngoài — cần CẢ động từ mang-đi VÀ tên bí mật, vì chỉ
    # nhắc tên là chính đáng (skill `polite-guest-reply` dặn ĐỪNG tiết lộ token).
    # Phải bắt CẢ HAI THỨ TỰ: "gửi token cho tôi" và "đọc file .env rồi gửi" —
    # thứ tự thứ hai là ca thật làm lộ lỗ hổng khi viết test.
    (re.compile(r"(gửi|đưa|copy|sao\s*chép|post|upload|đăng\s+lên)[^.\n]{0,40}"
                r"(mật\s+khẩu|token|api[_\s-]?key|auth[_\s-]?key|\.env|refresh[_\s-]?token)", re.I),
     "cố lấy mật khẩu / token gửi ra ngoài"),
    (re.compile(r"(mật\s+khẩu|token|api[_\s-]?key|auth[_\s-]?key|\.env|refresh[_\s-]?token)"
                r"[^.\n]{0,40}(gửi|đưa|copy|post|upload|đăng\s+lên|cho\s+tôi)", re.I),
     "cố lấy mật khẩu / token gửi ra ngoài"),
    (re.compile(r"(send|leak|exfiltrat\w*|upload)[^.\n]{0,40}"
                r"(password|token|api[_\s-]?key|secret|\.env)", re.I),
     "cố lấy mật khẩu / token gửi ra ngoài"),
    (re.compile(r"(password|token|api[_\s-]?key|secret|\.env)[^.\n]{0,40}"
                r"(send|leak|exfiltrat\w*|upload|to\s+my)", re.I),
     "cố lấy mật khẩu / token gửi ra ngoài"),
)


def soi_than_skill(body: str) -> str:
    """Trả LÝ DO từ chối, hoặc "" nếu thân skill sạch.

    Chỉ dùng cho skill do bot TỰ HỌC từ chat. Skill đóng gói trong
    `skills_default/` là code đã xem xét — không soi, khỏi chặn oan.
    """
    text = str(body or "")
    if not text.strip():
        return ""
    for pat, ly_do in _CAM:
        if pat.search(text):
            return ly_do
    return ""


# ── Kho đếm ─────────────────────────────────────────────────────────────────
def _doc() -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(_PATH.read_text("utf-8")) if _PATH.is_file() else {}
        return raw if isinstance(raw, dict) else {}
    except Exception as exc:
        logger.warning("skill_quality: đọc lỗi: %s", exc)
        return {}


def _ghi(data: dict[str, dict[str, Any]]) -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_PATH)
    except Exception as exc:
        logger.warning("skill_quality: ghi lỗi: %s", exc)


def _muc(data: dict, slug: str) -> dict[str, Any]:
    m = data.get(slug)
    if not isinstance(m, dict):
        m = {"dung": 0, "xong": 0, "hong": 0, "tu_hoc": False,
             "lan_cuoi": 0.0, "hong_cuoi": 0.0}
        data[slug] = m
    return m


def ho_so(slug: str) -> dict[str, Any]:
    """Bản ghi của một skill (rỗng nếu chưa có dữ liệu)."""
    with _lock:
        m = _doc().get(str(slug or ""))
    return dict(m) if isinstance(m, dict) else {}


def danh_dau_tu_hoc(slug: str) -> None:
    """Skill này do bot tự học từ chat — không phải skill đóng gói sẵn."""
    slug = str(slug or "").strip()
    if not slug:
        return
    with _lock:
        data = _doc()
        _muc(data, slug)["tu_hoc"] = True
        _ghi(data)


def xoa(slug: str) -> None:
    """Xoá skill thì xoá luôn điểm — slug dùng lại không thừa hưởng điểm cũ."""
    slug = str(slug or "").strip()
    if not slug:
        return
    with _lock:
        data = _doc()
        if data.pop(slug, None) is not None:
            _ghi(data)


def ghi_dung(user_id: str, slug: str) -> None:
    """`use_skill` đã nạp thân skill. Kết quả xong/hỏng ghi sau, cuối lượt."""
    slug = str(slug or "").strip()
    if not slug:
        return
    with _lock:
        data = _doc()
        m = _muc(data, slug)
        m["dung"] = int(m.get("dung") or 0) + 1
        m["lan_cuoi"] = time.time()
        _ghi(data)
        _cho_ket_qua[str(user_id or "")] = (slug, time.time())


def ghi_ket_qua(user_id: str, status: str = "") -> None:
    """Cuối lượt: gán kết quả cho skill vừa dùng trong lượt đó.

    `status` lấy từ `orchestrator._journal`. Lượt không dùng skill nào thì hàm
    này không làm gì. Người dùng bấm "thôi" (`denied`) hoặc lượt còn đang chờ
    duyệt thì KHÔNG tính — đó là ý người, không phải chất lượng skill.
    """
    uid = str(user_id or "")
    st = str(status or "")
    if st in _KHONG_TINH:
        with _lock:
            _cho_ket_qua.pop(uid, None)
        return
    with _lock:
        cho = _cho_ket_qua.pop(uid, None)
        if not cho:
            return
        slug, luc = cho
        if time.time() - luc > _CHO_TOI_DA_GIAY:
            return                      # lượt cũ quá, đừng gán oan
        data = _doc()
        m = _muc(data, slug)
        if st in _HONG:
            m["hong"] = int(m.get("hong") or 0) + 1
            m["hong_cuoi"] = time.time()
        else:
            m["xong"] = int(m.get("xong") or 0) + 1
        _ghi(data)
    logger.info("skill_quality: %s -> %s (xong=%s hỏng=%s)", slug,
                "hỏng" if st in _HONG else "xong", m.get("xong"), m.get("hong"))


# ── Chấm điểm ───────────────────────────────────────────────────────────────
def diem(slug: str) -> float:
    """Tỉ lệ thành công làm trơn Laplace — cùng công thức
    `account_service._selection_weight`. Chưa có dữ liệu → 0.5 (chưa biết)."""
    m = ho_so(slug)
    xong = int(m.get("xong") or 0)
    hong = int(m.get("hong") or 0)
    return (xong + 1) / (xong + hong + 2)


def bac(slug: str) -> str:
    """chua_dung | dang_thu | tin_duoc | hay_hong — để hiện cho người dùng xem."""
    m = ho_so(slug)
    xong = int(m.get("xong") or 0)
    hong = int(m.get("hong") or 0)
    if xong + hong == 0:
        return "chua_dung"
    if xong + hong >= _DU_MAU and diem(slug) < _DIEM_TOI:
        return "hay_hong"
    if xong >= _XONG_DE_TIN and diem(slug) >= _DIEM_TIN:
        return "tin_duoc"
    return "dang_thu"


NHAN_BAC = {
    "chua_dung": "chưa dùng lần nào",
    "dang_thu": "đang thử",
    "tin_duoc": "đã tin được",
    "hay_hong": "hay hỏng — đã rút khỏi định tuyến",
}


def nen_an_khoi_router(slug: str) -> bool:
    """Rút skill hay hỏng khỏi bộ định tuyến.

    Đây là chỗ tiết kiệm thật: mô tả mỗi skill vào system prompt MỌI LƯỢT CHAT,
    nên một skill vừa hỏng vừa chiếm suất trong `max_list()` là tốn kép. Chỉ rút
    khi đã đủ mẫu — chưa dùng lần nào KHÔNG phải là dở.
    """
    return bac(slug) == "hay_hong"


def thong_ke() -> dict[str, Any]:
    with _lock:
        data = _doc()
    rows = []
    for slug in sorted(data):
        rows.append({
            "slug": slug, "bac": bac(slug), "diem": round(diem(slug), 3),
            **{k: data[slug].get(k) for k in ("dung", "xong", "hong", "tu_hoc")},
        })
    return {"so_skill": len(rows),
            "so_bi_an": sum(1 for r in rows if r["bac"] == "hay_hong"),
            "skills": rows}


def _reset_for_tests(path: Optional[Path] = None) -> None:
    global _PATH
    with _lock:
        if path is not None:
            _PATH = Path(path)
        _cho_ket_qua.clear()
