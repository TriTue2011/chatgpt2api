"""Tool ``chi_tieu`` của bot — một tool, nhiều việc (``viec``), để bộ định tuyến chỉ tốn một mục.

Người nhắn chỉ chạm được sổ ĐÃ LIÊN KẾT với chính kênh chat của họ (``ctx["user_id"]``); chưa liên kết thì chỉ
có việc ``lien_ket``. Docstring / workflow viết cho model theo kinh nghiệm bản gốc (chi-tieu-mcp/app/main.py):
luôn gọi tool lấy số mới, mỗi tin báo chi là một khoản mới, hỏi lại khi mô tả chung chung, không tự xác nhận
khoản làm vượt tổng thay người dùng.
"""

from __future__ import annotations

from typing import Any

from services.chi_tieu import nghiep_vu as nv

VIEC = ("ghi_chi", "xem", "lich_su", "sua_chi", "xoa_chi", "tach", "de_xuat", "thu_nhap_them", "chi_phi_dac_biet",
        "cong_ty_tam_ung", "cong_ty_chi", "cong_ty_xem", "giai_chi", "lien_ket")

MO_TA = ("Sổ chi tiêu theo hũ (JARS) của CHÍNH người đang nhắn: ghi khoản chi, xem còn bao nhiêu, lịch sử, sửa/xoá/"
         "tách khoản, thu nhập thêm, chi phí đặc biệt, tạm ứng công ty. viec='lien_ket' + ma để nối sổ trên web.")

THAM_SO = {"type": "object", "properties": {
    "viec": {"type": "string", "enum": list(VIEC)},
    "hu": {"type": "string", "description": "Tên hũ (vd 'Thiết Yếu', 'Hưởng Thụ') — gọi viec='xem' để biết các hũ"},
    "so_tien": {"type": "integer", "description": "VNĐ, số nguyên dương (50k = 50000)"},
    "ghi_chu": {"type": "string"},
    "mo_ta": {"type": "string", "description": "Cho thu nhập thêm / chi phí đặc biệt / công ty"},
    "id": {"type": "integer", "description": "id khoản chi (lấy từ viec='lich_su')"},
    "danh_sach": {"type": "array", "items": {"type": "object"},
                  "description": "viec='tach': [{hu, so_tien, ghi_chu}], tổng bằng khoản gốc"},
    "thang": {"type": "string", "description": "Kỳ YYYY-MM, bỏ trống = kỳ hiện tại"},
    "xac_nhan_vuot_tong": {"type": "boolean",
                           "description": "CHỈ true khi người dùng vừa đồng ý rõ ràng ghi khoản làm vượt tổng"},
    "ma": {"type": "string", "description": "viec='lien_ket': mã 6 số lấy trên web"}},
    "required": ["viec"]}

QUY_TRINH = ("Luôn lấy số từ kết quả tool, không trả lời bằng số nhớ được. Mỗi tin «vừa chi …» là MỘT khoản mới — "
             "đừng gộp với khoản trước. Mô tả chung chung không rõ hũ nào thì HỎI lại trước khi ghi. Kết quả "
             "can_xac_nhan=true nghĩa là CHƯA GHI: đọc canh_bao cho người dùng và chỉ gọi lại với "
             "xac_nhan_vuot_tong=true khi họ đồng ý ở tin sau — tuyệt đối không tự xác nhận. Trả lời ngắn: đã ghi "
             "bao nhiêu vào hũ nào, hũ còn bao nhiêu, cảnh báo nếu có. Chưa có sổ → hướng dẫn liên kết trên web.")

_CHUA_CO_SO = ("Bạn chưa có sổ chi tiêu. Mở web c2a › Chi tiêu › Liên kết, lấy mã 6 số rồi nhắn «liên kết chi tiêu "
               "<mã>»; hoặc nhờ quản trị gán Zalo/Telegram của bạn vào sổ.")


def _meta_gui(user_id: str) -> dict[str, Any]:
    """Đúng bot / tài khoản Zalo đang nhận tin — để cảnh báo gửi lại đúng đường."""
    try:
        from services.agent import reminders
        return reminders._capture_delivery_ctx(reminders.channel_of(user_id)[0])
    except Exception:
        return {}


def xu_ly(args: dict, ctx: dict) -> dict:
    user_id = str(ctx.get("user_id") or "")
    viec = str(args.get("viec") or "")
    try:
        if viec == "lien_ket":
            return nv.lien_ket_bang_ma(user_id, str(args.get("ma") or ""), str(ctx.get("user_name") or ""),
                                       _meta_gui(user_id))
        so_id = nv.so_cua_chat(user_id)
        if so_id is None and user_id.startswith("web_") and len(user_id) > 4:
            # Chat ngay trên web c2a: user_id = "web_" + id tài khoản đăng nhập → đúng sổ của tài khoản đó.
            so_id = nv.so_cua_tai_khoan({"id": user_id[4:], "name": str(ctx.get("user_name") or "")})["id"]
        if so_id is None:
            return {"loi": _CHUA_CO_SO}
        a = args
        if viec == "ghi_chi":
            return nv.ghi_chi(so_id, a.get("hu"), a.get("so_tien"), a.get("ghi_chu") or "",
                              bool(a.get("xac_nhan_vuot_tong")), nguon="chat")
        if viec == "xem":
            return nv.xem_ngan_sach(so_id, str(a.get("thang") or ""))
        if viec == "lich_su":
            return nv.xem_lich_su(so_id, str(a.get("thang") or ""))
        if viec == "sua_chi":
            return nv.sua_chi(so_id, int(a.get("id") or 0), hu=a.get("hu"), so_tien=a.get("so_tien"),
                              ghi_chu=a.get("ghi_chu"), xac_nhan_vuot_tong=bool(a.get("xac_nhan_vuot_tong")))
        if viec == "xoa_chi":
            return nv.xoa_chi(so_id, int(a.get("id") or 0))
        if viec == "tach":
            return nv.tach_chi(so_id, int(a.get("id") or 0), a.get("danh_sach") or [])
        if viec == "de_xuat":
            return nv.de_xuat(so_id)
        if viec in ("thu_nhap_them", "chi_phi_dac_biet"):
            return nv.ghi_ky(viec, so_id, a.get("mo_ta"), a.get("so_tien"))
        if viec in ("cong_ty_tam_ung", "cong_ty_chi"):
            return nv.ghi_cong_ty(so_id, "tam_ung" if viec == "cong_ty_tam_ung" else "chi", a.get("so_tien"),
                                  a.get("mo_ta"))
        if viec == "cong_ty_xem":
            return nv.xem_cong_ty(so_id)
        if viec == "giai_chi":
            return nv.giai_chi(so_id)
        return {"loi": f"viec phải là một trong {', '.join(VIEC)}"}
    except nv.LoiChiTieu as exc:
        return {"loi": str(exc)}
