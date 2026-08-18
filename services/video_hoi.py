"""Bốn ô LLM của menu video — chạy trên PHỤ ĐỀ đã có, không nghe lại video.

Chủ máy chốt 18/08: "chuyển thành phụ đề rồi mới qua llm để làm 12345". Nghĩa
là mọi video — link YouTube hay tệp gửi lên — đều đi qua bước tạo phụ đề trước;
phụ đề đó là ĐẦU VÀO cho cả bốn ô đọc-hiểu (tóm tắt · ý chính · phân tích đoạn ·
ghi chú) lẫn hai ô ra video (phụ đề · lồng tiếng).

Nhờ vậy TỆP gửi lên cũng tóm tắt được — trước đây chỉ link mới làm được, vì
đường link có sẵn transcript của YouTube còn tệp thì không.

Tách khỏi ``video_dich`` có chủ ý: module đó là đường ống thuần (nghe → dịch →
đóng .srt), không gọi model nào. Trộn một lời gọi LLM vào giữa thì mọi test của
nó phải dựng thêm gateway.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Cắt bớt phụ đề dài trước khi đưa vào model. Một video 2 giờ ra quãng 60-80
#: nghìn ký tự; giữ nguyên là vượt cửa sổ ngữ cảnh của phần lớn model rồi bị
#: gateway cắt ở chỗ không ai chọn. Cắt ở đây thì ít nhất người dùng ĐƯỢC BÁO.
TOI_DA_CHU = 60_000

#: Mã việc → (câu dặn hệ thống, câu hỏi). Câu hỏi nhận ``{noi_dung}`` và
#: ``{them}`` (phần riêng của ô phân tích đoạn).
_NHIEM_VU: dict[str, tuple[str, str]] = {
    "tom-tat": (
        "Bạn tóm tắt video bằng tiếng Việt, đúng nội dung, không thêm thông tin "
        "ngoài phụ đề. Xưng em, gọi người nghe là anh.",
        "Đây là phụ đề của một video. Tóm tắt lại: video nói về gì, các phần "
        "chính theo thứ tự, và kết luận nếu có.\n\n{noi_dung}",
    ),
    "y-chinh": (
        "Bạn rút ý chính từ phụ đề video, bằng tiếng Việt, bám sát nội dung.",
        "Đây là phụ đề của một video. Liệt kê các ý chính thành gạch đầu dòng, "
        "mỗi ý một dòng ngắn gọn, giữ đúng thứ tự trong video.\n\n{noi_dung}",
    ),
    "phan-tich": (
        "Bạn phân tích nội dung video bằng tiếng Việt, dựa hoàn toàn vào phụ đề "
        "kèm mốc thời gian. Không bịa phần video không nói tới.",
        "Đây là phụ đề có mốc thời gian của một video. Anh muốn phân tích kỹ "
        "đoạn: «{them}».\nTìm đúng đoạn đó, thuật lại nội dung, rồi phân tích: "
        "người nói đang lập luận gì, dẫn chứng ra sao, có chỗ nào đáng chú ý. "
        "Nếu phụ đề không có đoạn này thì nói thẳng là không tìm thấy.\n\n"
        "{noi_dung}",
    ),
    "ghi-chu": (
        "Bạn soạn ghi chú học tập bằng tiếng Việt từ phụ đề video, dễ ôn lại.",
        "Đây là phụ đề của một video. Soạn thành ghi chú học tập: chia mục theo "
        "chủ đề, mỗi mục có định nghĩa/ý chính và ví dụ nếu video có nêu. Cuối "
        "cùng thêm vài câu tự kiểm tra.\n\n{noi_dung}",
    ),
}

#: Ô nào cần phụ đề CÓ MỐC THỜI GIAN (bản .srt) thay vì lời thoại trơn.
CAN_MOC_GIO = ("phan-tich",)


class LoiHoiVideo(RuntimeError):
    """Model không trả lời được — người gọi báo nguyên văn cho người dùng."""


def la_viec_llm(viec: str) -> bool:
    return str(viec or "") in _NHIEM_VU


def hoi(viec: str, noi_dung: str, *, them: str = "") -> str:
    """Phụ đề + mã việc → câu trả lời của model.

    ``noi_dung``: lời thoại (hoặc nguyên .srt với ô phân tích đoạn).
    ``them``: đoạn người dùng muốn phân tích — chỉ ô "phan-tich" dùng tới.
    """
    nv = _NHIEM_VU.get(str(viec or ""))
    if nv is None:
        raise LoiHoiVideo(f"không có việc {viec!r} trong menu")
    chu = str(noi_dung or "").strip()
    if not chu:
        raise LoiHoiVideo("phụ đề rỗng nên chưa có gì để đọc")
    cat = len(chu) > TOI_DA_CHU
    if cat:
        chu = chu[:TOI_DA_CHU]

    from services.agent.orchestrator import _main_model
    from services.agent.runtime import call_model

    model = _main_model("chat")
    if not model:
        raise LoiHoiVideo("chưa cấu hình model nào cho phần đọc hiểu")
    dan, hoi_gi = nv
    out: dict[str, Any] = call_model(
        model,
        [{"role": "system", "content": dan},
         {"role": "user", "content": hoi_gi.format(noi_dung=chu, them=them)}],
        max_tokens=2000, timeout=300,
        # Đọc thứ ĐÃ CÓ trong tay — không được đi tra web. Bỏ trống thì gateway
        # bật web search tự động và lấy nguyên prompt làm câu truy vấn (đúng lỗi
        # đã đo ở services/digest.py).
        allowed_groups={"summary"},
    )
    if out.get("error"):
        raise LoiHoiVideo(str(out["error"])[:200])
    msg = ((out.get("choices") or [{}])[0] or {}).get("message") or {}
    tra_loi = str(msg.get("content") or "").strip()
    if not tra_loi:
        raise LoiHoiVideo("model trả lời rỗng")
    if cat:
        tra_loi += ("\n\n⚠️ Phụ đề dài quá nên em chỉ đọc được phần đầu "
                    f"(~{TOI_DA_CHU // 1000} nghìn ký tự).")
    return tra_loi
