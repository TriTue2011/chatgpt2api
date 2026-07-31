"""Chia việc cho nhiều con + vai con tra cứu, cho pipeline code.

Vì sao tách file: `openai_v1_chat_complete.py` đã quá lớn, và hai việc dưới đây
thuần logic (không cần gọi model) nên test được riêng.

Hai thứ ở đây:

1. `tach_phan` — cắt kế hoạch của bố thành các phần ĐỘC LẬP để giao cho nhiều
   con làm song song, rồi `gop_code` ghép lại.

   Cảnh báo từ tài liệu (blog.appxlab.io về git worktree, và tổng quan
   arXiv 2604.16321): chia SAI thì phần lợi bị ăn hết ở bước gộp — "trông như
   song song" rồi vỡ khi ghép. Nên cửa vào ở đây RẤT hẹp: chỉ chia khi CHÍNH BỐ
   đánh dấu phần và tự khai `ĐỘC LẬP: có`. Không tự suy diễn từ gạch đầu dòng.

   Bảo hiểm cuối: code sau khi ghép vẫn đi qua bộ chạy thử (`code_runner`), nên
   ghép sai kiểu trùng tên hàm hay thiếu import sẽ bị bắt ngay chứ không lọt ra
   ngoài.

2. `tra_cuu_ke_hoach` — con tra cứu: khi bố tự khai là KHÔNG CHẮC về một thư
   viện/API, đi tìm rồi trả ghi chú cho con viết, đồng thời LƯU vào wiki để lần
   sau bố đọc lại (chủ máy: "tìm kiếm thêm thông tin về để sau này thêm dữ liệu").
"""

from __future__ import annotations

import re

from utils.log import logger

# Bố đánh dấu phần bằng dòng "### PHẦN n: tên". Chỉ nhận đúng khuôn này —
# gạch đầu dòng thường KHÔNG được coi là một phần chia được.
_PHAN_RE = re.compile(r"(?mi)^\s*#{0,3}\s*PHẦN\s+(\d+)\s*:\s*(.+?)\s*$")
# Bố tự khai các phần có độc lập với nhau không.
_DOC_LAP_RE = re.compile(r"(?mi)^\s*ĐỘC\s*LẬP\s*:\s*(có|co|yes|true)\b")
# Bố tự khai chỗ mình không chắc, cần tra cứu.
_CAN_TRA_RE = re.compile(r"(?mi)^\s*CẦN\s*TRA\s*CỨU\s*:\s*(.+?)\s*$")

# Chia việc chỉ đáng làm khi có đủ nhiều phần: 2 phần thì gọi song song 2 model
# tốn gần bằng 1 model làm cả, mà thêm rủi ro ghép.
TOI_THIEU_PHAN = 3
# Trần số con chạy song song — mỗi con là một lượt gọi model.
TRAN_PHAN = 5


def tach_phan(plan: str) -> list[dict[str, str]]:
    """Cắt kế hoạch thành các phần độc lập. Trả [] nếu KHÔNG nên chia.

    Trả [] khi: bố không đánh dấu phần, bố khai không độc lập, hoặc số phần
    dưới ngưỡng. Bên gọi thấy [] thì chạy đường một con như cũ.
    """
    p = plan or ""
    moc = list(_PHAN_RE.finditer(p))
    if len(moc) < TOI_THIEU_PHAN:
        return []
    if not _DOC_LAP_RE.search(p):
        logger.info({"event": "code_split_bo_qua", "ly_do": "bố không khai ĐỘC LẬP: có",
                     "so_moc": len(moc)})
        return []
    cac_phan: list[dict[str, str]] = []
    for i, m in enumerate(moc[:TRAN_PHAN]):
        dau = m.end()
        cuoi = moc[i + 1].start() if i + 1 < len(moc) else len(p)
        noi_dung = p[dau:cuoi].strip()
        if not noi_dung:
            continue
        cac_phan.append({"so": m.group(1), "ten": m.group(2).strip(), "viec": noi_dung})
    if len(cac_phan) < TOI_THIEU_PHAN:
        return []
    logger.info({"event": "code_split_chia", "so_phan": len(cac_phan),
                 "ten": [c["ten"][:40] for c in cac_phan]})
    return cac_phan


def gop_code(cac_khoi: list[str]) -> str:
    """Ghép code của các con lại, bỏ dòng import trùng.

    Mỗi con đều tự viết import của phần mình nên ghép thô sẽ có `import re` ba
    lần. Trùng import không làm code sai nhưng khiến bố soi mất tập trung vào
    thứ vụn. Gom import lên đầu, giữ nguyên thứ tự phần thân.
    """
    imports: list[str] = []
    da_co: set[str] = set()
    than: list[str] = []
    for khoi in cac_khoi:
        if not (khoi or "").strip():
            continue
        dong_than: list[str] = []
        for dong in khoi.splitlines():
            s = dong.strip()
            if re.match(r"^(import\s+\w|from\s+[\w.]+\s+import\s)", s):
                if s not in da_co:
                    da_co.add(s)
                    imports.append(s)
                continue
            dong_than.append(dong)
        con_lai = "\n".join(dong_than).strip("\n")
        if con_lai.strip():
            than.append(con_lai)
    ra = []
    if imports:
        ra.append("\n".join(imports))
    ra.extend(than)
    return "\n\n\n".join(ra).strip() + "\n"


def can_tra_cuu(plan: str) -> str:
    """Bố khai cần tra cứu gì. Trả chuỗi truy vấn hoặc "" nếu không cần.

    Cố ý dựa vào bố TỰ KHAI chứ không đoán: tra cho mọi lượt là đốt thời gian
    và kéo kết quả web nhiễu vào ngữ cảnh code.
    """
    m = _CAN_TRA_RE.search(plan or "")
    if not m:
        return ""
    q = m.group(1).strip()
    # Bố có thể viết "không", "không cần", hoặc chỉ một dấu gạch khi chắc rồi.
    # KHÔNG dùng \b sau '-': '-' là ký tự không phải chữ nên \b không khớp khi
    # nó đứng cuối chuỗi — đúng lỗi test bắt được ngày 31/07.
    if q.strip("-—–. ") == "":
        return ""
    if re.match(r"(?i)^(không|khong|no|none|n/?a)\b", q):
        return ""
    return q[:200]


def tra_cuu_ke_hoach(plan: str, request: str, luu_wiki: bool = True) -> str:
    """Vai con TRA CỨU: tìm thông tin bố khai là chưa chắc, trả ghi chú ngắn.

    Trả "" khi không cần tra hoặc không tìm được gì — bên gọi không chèn gì.
    Ghi chú cũng được lưu vào wiki để lần sau dùng lại (nếu wiki đang bật).
    """
    q = can_tra_cuu(plan)
    if not q:
        return ""
    try:
        from services.search_service import search_service
        kq = search_service.search_all(q) or []
    except Exception as exc:
        logger.warning({"event": "code_tracuu_err", "error": str(exc)[:150]})
        return ""
    if not kq:
        logger.info({"event": "code_tracuu_rong", "query": q[:80]})
        return ""
    dong: list[str] = []
    for x in kq[:4]:
        tieu_de = str(x.get("title") or "").strip()
        mo_ta = " ".join(str(x.get("snippet") or "").split())[:400]
        url = str(x.get("url") or "").strip()
        if not (tieu_de or mo_ta):
            continue
        dong.append(f"- {tieu_de}: {mo_ta}" + (f" ({url})" if url else ""))
    if not dong:
        return ""
    ghi_chu = f"Tra cứu cho: {q}\n" + "\n".join(dong)
    logger.info({"event": "code_tracuu_ok", "query": q[:80], "so_nguon": len(dong)})
    if luu_wiki:
        _luu_wiki(q, request, ghi_chu)
    return ghi_chu


def _luu_wiki(q: str, request: str, ghi_chu: str) -> None:
    """Lưu ghi chú tra cứu vào wiki — nguồn dữ liệu cho các lượt code sau."""
    try:
        from services.agent import wiki as w
        if not w.is_enabled():
            return
        out = w.ingest(
            f"{ghi_chu}\n\nYêu cầu code gốc: {request[:300]}",
            title=f"Tra cứu code: {q[:80]}",
            who="pipeline-code",
            source="pipeline_code_tracuu",
        )
        logger.info({"event": "code_tracuu_luu_wiki", "slug": str(out.get("slug"))[:60]})
    except Exception as exc:
        logger.warning({"event": "code_tracuu_luu_err", "error": str(exc)[:150]})


def loi_nhac_phan(phan: dict[str, str], tong: int) -> str:
    """Câu nhắc cho con: chỉ làm PHẦN của mình, đừng viết phần của người khác."""
    return (
        f"Bạn CHỈ làm PHẦN {phan['so']}/{tong}: {phan['ten']}\n"
        f"Nội dung phần này:\n{phan['viec']}\n\n"
        "Các phần khác do người khác viết và sẽ được GHÉP với phần của bạn. Vì vậy:\n"
        "- CHỈ xuất code của phần này, TUYỆT ĐỐI không viết lại phần khác.\n"
        "- Không viết hàm main/demo/test tổng — sẽ trùng với người khác.\n"
        "- Tự khai import cần cho phần này (trùng thì hệ thống tự gộp)."
    )
