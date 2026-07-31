"""Chạy thử code Python do model sinh, NGAY TRONG container, có giới hạn.

Vì sao có file này: tầng kiểm duyệt của pipeline code hiện chỉ ĐỌC code rồi
phán. Bằng chứng ngoài ngành cho thấy thứ tạo ra chênh lệch là CHẠY code rồi
đưa lỗi thật về cho người viết sửa — SAFEdit (arXiv 2604.25737) đạt 68,6% so
với 60,0% của một agent kiểu ReAct và 64,8% của model đơn tốt nhất, nhờ đúng
vòng "thực thi rồi tinh chỉnh". Đọc code không phát hiện được NameError,
TypeError hay assert sai; chạy một lần thì thấy ngay.

GIỚI HẠN — nói rõ để không ai tưởng đây là sandbox thật:

- CÓ bảo đảm: chạy ở tiến trình con nên treo/chết không kéo bot theo; có hạn
  thời gian, hết hạn thì diệt cả nhóm tiến trình; thư mục làm việc riêng, xoá
  sau khi chạy; môi trường bị LỌC SẠCH — code sinh ra KHÔNG thấy API key,
  mật khẩu hay DATABASE_URL của bot.
- KHÔNG bảo đảm: không cách ly mạng thật (chỉ trỏ biến proxy vào địa chỉ chết,
  chặn được thư viện đọc biến môi trường chứ không chặn socket thô); không
  giới hạn RAM/CPU (cần cgroup và quyền root).

Vì vậy chỉ chạy code TỰ ĐỦ (self-contained). Hàm `co_the_chay` từ chối code
có dấu hiệu chạm vào dự án, vào mạng, vào file hệ thống hay chờ người gõ.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

from utils.log import logger

# Trần thời gian cho một lượt chạy thử. Code sinh ra chỉ để kiểm tính đúng nên
# không cần lâu; treo quá lâu là dấu hiệu vòng lặp vô hạn — cũng là một lỗi.
HAN_GIAY = 20.0
# Cắt đầu ra để không nhồi hàng nghìn dòng vào ngữ cảnh model.
TRAN_KY_TU_RA = 4000
TRAN_KY_TU_CODE = 40000

_KHOI_CODE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)

# Dấu hiệu code KHÔNG tự đủ → không chạy thử (chạy chỉ tạo lỗi giả, làm con
# sửa sai hướng). Ví dụ thật: bot sửa một hàm trong services/ thì đoạn code
# trả về `from services.config import config`, chạy riêng lẻ sẽ ImportError
# dù code hoàn toàn đúng.
_KHONG_TU_DU = (
    "from services", "import services", "from api", "import api",
    "from utils", "import utils", "from captcha", "import chromadb",
    "import fastapi", "from fastapi", "import curl_cffi", "import httpx",
    "import requests", "import torch", "import numpy", "import pandas",
    "import playwright", "from playwright",
)
# Chờ người gõ hoặc chạy vô hạn → luôn hết hạn, không phải lỗi của code.
_CHO_NGUOI = ("input(", "sys.stdin", "while true:", "while 1:")
# Chạm hệ thống → tuyệt đối không chạy thử.
_NGUY_HIEM = (
    "os.system", "subprocess", "shutil.rmtree", "os.remove", "os.unlink",
    "socket.", "os.fork", "eval(", "exec(", "__import__",
    "open(\"/", "open('/",
)


def boc_code_python(text: str) -> str:
    """Lấy code Python từ câu trả lời của model.

    Nhiều khối thì NỐI lại theo thứ tự — model hay tách phần import và phần
    hàm thành hai khối, lấy một khối là mất nửa.
    """
    khoi = _KHOI_CODE_RE.findall(text or "")
    if khoi:
        return "\n\n".join(k.strip() for k in khoi if k.strip())
    # Không có dấu ``` — coi cả câu trả lời là code nếu nó trông như code.
    t = (text or "").strip()
    if re.search(r"(?m)^\s*(def |class |import |from \w+ import )", t):
        return t
    return ""


def co_the_chay(code: str) -> tuple[bool, str]:
    """Code này có đáng chạy thử không. Trả (được/không, lý do nếu không)."""
    c = (code or "").strip()
    if not c:
        return False, "không bóc được khối code Python nào"
    if len(c) > TRAN_KY_TU_CODE:
        return False, f"code dài {len(c)} ký tự, vượt trần {TRAN_KY_TU_CODE}"
    low = c.lower()
    for dau in _NGUY_HIEM:
        if dau in low:
            return False, f"code có {dau!r} — chạm hệ thống, không chạy thử"
    for dau in _CHO_NGUOI:
        if dau in low:
            return False, f"code có {dau!r} — chờ người gõ hoặc chạy vô hạn"
    for dau in _KHONG_TU_DU:
        if dau in low:
            return False, f"code cần {dau!r} — không tự đủ để chạy riêng"
    return True, ""


def _moi_truong_sach() -> dict[str, str]:
    """Môi trường TỐI THIỂU cho tiến trình con.

    Cố ý KHÔNG kế thừa os.environ: môi trường của bot có API key của Gemini,
    Agnes, NVIDIA, TokenRouter, mật khẩu Postgres… Code do model sinh không có
    lý do gì được thấy chúng, và một dòng `print(os.environ)` là đủ để rò hết
    vào log rồi vào ngữ cảnh model.
    """
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        # Chặn thư viện HTTP đọc biến proxy: trỏ vào địa chỉ chết. KHÔNG phải
        # cách ly mạng thật — socket thô vẫn ra được.
        "http_proxy": "http://127.0.0.1:9",
        "https_proxy": "http://127.0.0.1:9",
        "no_proxy": "",
    }


def chan_doan_loi(stderr: str, code: str) -> str:
    """Biến traceback thô thành chẩn đoán ngắn, có chỉ đúng dòng code sai.

    Đưa nguyên traceback vào ngữ cảnh model là tốn token và loãng: phần lớn là
    đường dẫn file tạm vô nghĩa. Chỉ giữ loại lỗi, thông báo, số dòng và CHÍNH
    dòng code gây lỗi — đó là thứ người sửa cần.
    """
    err = (stderr or "").strip()
    if not err:
        return ""
    dong = err.splitlines()
    # Dòng cuối cùng có dạng "TypeError: ..." là loại lỗi + thông báo.
    loai = ""
    for d in reversed(dong):
        if re.match(r"^\w+(Error|Exception|Warning)\b", d.strip()):
            loai = d.strip()
            break
    if not loai:
        loai = dong[-1].strip()
    # Số dòng cuối cùng trong traceback thuộc file code của ta.
    so_dong = 0
    for d in dong:
        m = re.search(r'File "[^"]*", line (\d+)', d)
        if m:
            so_dong = int(m.group(1))
    ra = [f"Lỗi khi chạy: {loai}"]
    if so_dong:
        cac_dong = (code or "").splitlines()
        if 1 <= so_dong <= len(cac_dong):
            ra.append(f"Tại dòng {so_dong}: {cac_dong[so_dong - 1].strip()}")
        else:
            ra.append(f"Tại dòng {so_dong}")
    # Giữ thêm dòng assert nếu là AssertionError có thông báo riêng.
    if "AssertionError" in loai and len(loai) < 20:
        for d in reversed(dong):
            if "assert" in d:
                ra.append(f"Câu assert thất bại: {d.strip()}")
                break
    return "\n".join(ra)


def chay(code: str, han_giay: float = HAN_GIAY) -> dict[str, object]:
    """Chạy thử code. Trả dict:

    {"da_chay": bool, "ok": bool, "ma_thoat": int, "stdout": str,
     "stderr": str, "chan_doan": str, "ly_do_bo_qua": str}

    `da_chay=False` nghĩa là ĐÃ BỎ QUA (code không tự đủ) — KHÁC với chạy mà
    thất bại. Bên gọi phải phân biệt: bỏ qua thì đừng bắt con sửa gì.
    """
    duoc, ly_do = co_the_chay(code)
    if not duoc:
        logger.info({"event": "code_run_skip", "reason": ly_do})
        return {"da_chay": False, "ok": False, "ma_thoat": -1, "stdout": "",
                "stderr": "", "chan_doan": "", "ly_do_bo_qua": ly_do}

    thu_muc = tempfile.mkdtemp(prefix=f"c2a_thu_{uuid.uuid4().hex[:8]}_", dir="/tmp")
    duong_dan = os.path.join(thu_muc, "thu.py")
    try:
        with open(duong_dan, "w", encoding="utf-8") as f:
            f.write(code)
        try:
            p = subprocess.run(
                [sys.executable, "-I", duong_dan],   # -I: bỏ qua site-packages người dùng + biến PYTHON*
                cwd=thu_muc,
                env=_moi_truong_sach(),
                capture_output=True, text=True, timeout=han_giay,
                start_new_session=True,             # nhóm tiến trình riêng để diệt được cả con cháu
            )
        except subprocess.TimeoutExpired:
            logger.warning({"event": "code_run_timeout", "han_giay": han_giay})
            return {"da_chay": True, "ok": False, "ma_thoat": -9, "stdout": "",
                    "stderr": f"hết hạn {han_giay:.0f}s",
                    "chan_doan": (f"Code chạy quá {han_giay:.0f} giây chưa xong — "
                                  "nghi vòng lặp không có điều kiện dừng."),
                    "ly_do_bo_qua": ""}
        out = (p.stdout or "")[:TRAN_KY_TU_RA]
        err = (p.stderr or "")[:TRAN_KY_TU_RA]
        ok = p.returncode == 0
        logger.info({"event": "code_run_done", "ok": ok, "ma_thoat": p.returncode,
                     "stdout_len": len(out), "stderr_len": len(err)})
        return {"da_chay": True, "ok": ok, "ma_thoat": p.returncode,
                "stdout": out, "stderr": err,
                "chan_doan": "" if ok else chan_doan_loi(err, code),
                "ly_do_bo_qua": ""}
    finally:
        shutil.rmtree(thu_muc, ignore_errors=True)
