"""Bộ đề LUYỆN cho hướng dẫn `sinh_kich_ban.md` — dựng tình huống ở MỌI kiểu nơi chốn: căn hộ, nhà phố,
văn phòng, xưởng, nhà có người già, cổng ngoài trời.

Chủ máy 30/09/2026: "tham khảo cộng đồng mạng rộng hơn, không bó hẹp trong ý tưởng ngôi nhà của tôi,
ngoài trời, xưởng, cơ quan, khu công nghiệp, dự đoán hành vi, theo dõi trộm, báo hướng di chuyển, báo
con người … dùng được trong mọi tình huống". Mỗi đề cài sẵn MỘT chỗ hổng thật hay gặp (kinh nghiệm cộng
đồng: phòng kín có cửa, báo lây khu thông, cửa vào/ra, ngoài giờ, vùng nguy hiểm, vắng bất thường, báo
giả ngoài trời) — đáp án là bot phải tự thấy chỗ hổng đó (đúng thiết bị, đúng đánh giá) hoặc hỏi đúng điều.

Đáp án:
  phai_co: [{"thiet_bi", "hien_tai"?, "nen"?, "tu": [chữ]}] — phải có tình huống khớp; `tu`: tình huống /
           cảm biến thấy / vì sao chứa ÍT NHẤT một chữ (không phân biệt hoa thường).
  phai_hoi_ve: [[chữ, …], …] — mỗi nhóm: có câu hỏi chứa ít nhất một chữ của nhóm.
  khong_nen: [{"thiet_bi", "nen"}] — không tình huống nào của thiết bị đó được chọn `nen` này.
"""

from __future__ import annotations

from typing import Any

TANG = "services.kich_ban_nha"


def _uv(so_do: str, phong: dict[str, list[str]], thiet_bi: dict[str, tuple[str, str, list[str]]],
        mo_ta: list[str] | None = None, chac: bool = True, nguoi: list[str] | None = None) -> dict[str, Any]:
    return {"so_do": so_do, "so_do_chac": chac, "phong": phong, "mo_ta": mo_ta or [], "nguoi": nguoi or [],
            "thiet_bi": {tb: {"ten": t, "khu": k, "viec": v} for tb, (t, k, v) in thiet_bi.items()}}


DE: list[dict[str, Any]] = [
    {"ten": "nha_tam_cua_kin_ngoi_yen",
     "tinh_huong": "Ong trong hộp: nhà tắm có cửa và cảm biến cửa; người tắm/ngồi yên, radar mất dấu — đang cài tắt "
                   "khi radar vắng 3 phút nên tắt đèn trước mặt người.",
     "uv": _uv("chung cư, 1 tầng\n• Nhà tắm — có vách với Phòng ngủ, Hành lang\n• Hành lang — thông Phòng khách",
               {"Nhà tắm": ["Radar nhà tắm (sóng/chuyển động)", "Cửa nhà tắm (cửa)"],
                "Hành lang": ["Radar hành lang (sóng/chuyển động)"]},
               {"light.den_nha_tam": ("Đèn nhà tắm", "Nhà tắm", [
                   "BẬT (bot học, tự làm): khi Radar nhà tắm có người vào",
                   "TẮT KHI VẮNG: Radar nhà tắm báo vắng liền 3–3 phút (bot tự học theo giờ)"])}),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_nha_tam", "hien_tai": "sai",
                             "tu": ["cửa", "ngồi yên", "tắm", "mất dấu"]}]}},

    {"ten": "van_phong_ngoai_gio",
     "tinh_huong": "Văn phòng: đèn khu làm việc bật theo radar; 23h có người trong văn phòng lúc không ai có lịch — "
                   "phải BÁO chứ không chỉ bật đèn.",
     "uv": _uv("văn phòng, 1 tầng\n• Khu làm việc — thông Sảnh\n• Sảnh — có vách với Hành lang tòa nhà\n"
               "• Cửa chính mở vào Sảnh",
               {"Khu làm việc": ["Radar khu làm việc (sóng/chuyển động)", "Camera văn phòng Person (camera)"],
                "Sảnh": ["Cửa kính sảnh (cửa)"]},
               {"light.den_khu_lam_viec": ("Đèn khu làm việc", "Khu làm việc", [
                   "BẬT (bot học, tự làm): khi Radar khu làm việc có người vào",
                   "TẮT KHI VẮNG: Radar khu làm việc hoặc Camera văn phòng Person báo vắng liền 10–10 phút"])},
               ["Giờ làm việc 8:00–17:30 thứ 2–thứ 6. Ngoài giờ văn phòng khoá cửa."]),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_khu_lam_viec", "nen": "bao",
                             "tu": ["ngoài giờ", "đêm", "khuya", "23", "cuối tuần"]}]}},

    {"ten": "xuong_vung_may_nguy_hiem",
     "tinh_huong": "Xưởng: đèn cảnh báo vùng máy ép chỉ bật theo công tắc; người bước vào vùng máy đang chạy — phải "
                   "bật cảnh báo / báo ngay.",
     "uv": _uv("xưởng, 1 tầng\n• Vùng máy ép — thông Lối đi\n• Lối đi — thông Kho",
               {"Vùng máy ép": ["Camera xưởng Person (camera)", "Máy ép đang chạy (sóng/chuyển động)"],
                "Lối đi": ["Radar lối đi (sóng/chuyển động)"]},
               {"switch.den_canh_bao_may_ep": ("Đèn cảnh báo máy ép", "Vùng máy ép", [
                   "BẬT: chưa tự bật (luật học chưa đủ tin)", "TẮT: không tự tắt"])},
               ["Máy ép nguy hiểm: không ai được vào vùng máy khi máy đang chạy."]),
     "dap_an": {"phai_co": [{"thiet_bi": "switch.den_canh_bao_may_ep", "hien_tai": "sai",
                             "tu": ["máy", "vùng", "đang chạy"]}]}},

    {"ten": "nguoi_gia_o_mot_minh",
     "tinh_huong": "Bà ở một mình: sáng quá giờ quen mà phòng ngủ vẫn không ai ra, hoặc vào nhà tắm quá lâu — bot phải "
                   "nghĩ tới việc BÁO con cháu, và hỏi giờ quen thuộc nếu đề chưa có.",
     "uv": _uv("nhà phố, 1 tầng\n• Phòng ngủ bà — có vách với Phòng khách\n• Nhà tắm — có vách với Phòng ngủ bà",
               {"Phòng ngủ bà": ["Radar phòng ngủ bà (sóng/chuyển động)"],
                "Nhà tắm": ["Radar nhà tắm (sóng/chuyển động)", "Cửa nhà tắm (cửa)"],
                "Phòng khách": ["Radar phòng khách (sóng/chuyển động)"]},
               {"light.den_phong_ngu_ba": ("Đèn phòng ngủ bà", "Phòng ngủ bà", [
                   "BẬT (bot học, tự làm): khi Radar phòng ngủ bà có người vào",
                   "TẮT KHI VẮNG: Radar phòng ngủ bà báo vắng liền 5–5 phút"])},
               ["Bà 82 tuổi ở một mình, con cháu ở xa."]),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_phong_ngu_ba", "nen": "bao",
                             "tu": ["không thấy", "không cử động", "quá giờ", "lâu", "không dậy", "bất thường"]}]}},

    {"ten": "cong_ngoai_troi_bao_gia",
     "tinh_huong": "Cổng ngoài trời: đèn cổng bật theo cảm biến chuyển động — lá cây, đèn xe, mưa bật đèn cả đêm; "
                   "người lạ đứng lâu trước cổng thì phải báo.",
     "uv": _uv("nhà vườn\n• Sân trước — có vách với Phòng khách\n• Cổng mở ra Sân trước",
               {"Sân trước": ["Cảm biến chuyển động cổng (sóng/chuyển động)", "Camera cổng Person (camera)"]},
               {"light.den_cong": ("Đèn cổng", "Sân trước", [
                   "BẬT (bot học, tự làm): khi Cảm biến chuyển động cổng có người vào, Độ sáng sân ≤ 10",
                   "TẮT KHI VẮNG: Cảm biến chuyển động cổng báo vắng liền 2–2 phút"])}),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_cong", "hien_tai": "sai",
                             "tu": ["lá", "cây", "xe", "mưa", "báo giả", "gió", "côn trùng", "mèo", "chó"]},
                            {"thiet_bi": "light.den_cong", "nen": "bao",
                             "tu": ["lạ", "đứng lâu", "lảng vảng"]}]}},

    {"ten": "ca_nha_vang_ma_co_nguoi",
     "tinh_huong": "Cả nhà đi vắng (hai điện thoại không ở nhà) mà radar phòng khách báo có người, cửa chính vừa mở — "
                   "bật đèn thôi là thiếu: phải báo; nhưng có thể là người giúp việc → hỏi.",
     "uv": _uv("chung cư, 1 tầng\n• Phòng khách — thông Bếp\n• Cửa chính mở vào Phòng khách",
               {"Phòng khách": ["Radar phòng khách (sóng/chuyển động)", "Cảm biến cửa chính (cửa)",
                                "Camera phòng khách Person (camera)"]},
               {"light.den_tran_pk": ("Đèn trần phòng khách", "Phòng khách", [
                   "BẬT (bot học, tự làm): khi Cảm biến cửa chính mở (chỉ khi trong 60 giây khu của thiết bị có người MỚI "
                   "vào — người đi ra thì không), từ 17:30",
                   "TẮT KHI VẮNG: Radar phòng khách hoặc Camera phòng khách Person báo vắng liền 3–5 phút"])},
               nguoi=["Chồng (home)", "Vợ (home)", "Điện thoại chồng (home)", "Điện thoại vợ (home)"]),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_tran_pk", "nen": "bao",
                             "tu": ["vắng", "đi vắng", "không ở nhà", "lạ", "trộm"]}],
                "phai_hoi_ve": [["giúp việc", "người thân", "ai khác", "chìa khoá", "có ai", "người nào"]]}},

    {"ten": "bep_thong_phong_khach_bao_lay",
     "tinh_huong": "Căn hộ bếp thông phòng khách, radar phòng khách nhìn thẳng ra bếp: người nấu ăn làm quạt phòng "
                   "khách bật / không tắt.",
     "uv": _uv("chung cư, 1 tầng\n• Bếp — thông Phòng khách\n• Phòng khách — thông Bếp",
               {"Phòng khách": ["Radar phòng khách (sóng/chuyển động)"],
                "Bếp": ["Radar bếp (sóng/chuyển động)"]},
               {"fan.quat_pk": ("Quạt phòng khách", "Phòng khách", [
                   "BẬT: có người ở lại ≥ 3 phút (hợp các cảm biến Radar phòng khách) thì HỎI anh để học",
                   "TẮT KHI VẮNG: Radar phòng khách báo vắng liền 3–4 phút"])},
               ["Radar phòng khách đặt dưới tivi, nhìn thẳng ra bếp."]),
     "dap_an": {"phai_co": [{"thiet_bi": "fan.quat_pk", "hien_tai": "sai", "tu": ["bếp", "nấu", "lây"]}]}},

    {"ten": "ten_thiet_bi_khong_ro_cong_dung",
     "tinh_huong": "Tên «Đèn tủ lạnh» không nói là đèn trong tủ hay đèn cạnh tủ — không được đoán, phải hỏi.",
     "uv": _uv("chung cư, 1 tầng\n• Phòng khách — thông Bếp",
               {"Phòng khách": ["Radar phòng khách (sóng/chuyển động)"]},
               {"light.den_tu_lanh": ("Đèn tủ lạnh", "Phòng khách", [
                   "BẬT (luật anh đặt «Xem tivi»): khi «Ti vi phòng khách là on» có người vào",
                   "TẮT (luật anh đặt «Tivi tắt»): khi «Ti vi phòng khách là on» vắng"])}),
     "dap_an": {"phai_hoi_ve": [["đèn tủ lạnh", "tủ lạnh"]]}},
]


def de_cho(d: dict[str, Any]) -> str:
    from services import kich_ban_nha
    return kich_ban_nha.de(d["uv"], [])


def _chu(x: dict[str, Any]) -> str:
    return " ".join(str(x.get(k) or "") for k in ("tinh_huong", "cam_bien_thay", "vi_sao", "hoi")).lower()


def cham_cho(bai: dict[str, Any] | str, dap_an: dict[str, Any]) -> list[str]:
    if isinstance(bai, str):
        return [f"bài bị loại: {bai}"]
    kb = bai.get("kich_ban") or []
    loi: list[str] = []
    for y in dap_an.get("phai_co") or []:
        if not any(x["thiet_bi"] == y["thiet_bi"] and x["hien_tai"] == y.get("hien_tai", x["hien_tai"])
                   and x["nen"] == y.get("nen", x["nen"]) and any(t.lower() in _chu(x) for t in y["tu"]) for x in kb):
            loi.append(f"thiếu tình huống {y}")
    hoi = [str(x.get("hoi") or "").lower() for x in kb]
    for nhom in dap_an.get("phai_hoi_ve") or []:
        if not any(t.lower() in h for h in hoi for t in nhom):
            loi.append(f"thiếu câu hỏi về {nhom}")
    for y in dap_an.get("khong_nen") or []:
        if any(x["thiet_bi"] == y["thiet_bi"] and x["nen"] == y["nen"] for x in kb):
            loi.append(f"không được chọn {y}")
    return loi
