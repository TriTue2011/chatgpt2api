"""Bộ đề LUYỆN cho hướng dẫn `sinh_kich_ban.md` — dựng tình huống ở MỌI kiểu nơi chốn: căn hộ, nhà phố,
văn phòng, xưởng, nhà có người già, cổng ngoài trời.

Chủ máy 30/09/2026: "tham khảo cộng đồng mạng rộng hơn, không bó hẹp trong ý tưởng ngôi nhà của tôi,
ngoài trời, xưởng, cơ quan, khu công nghiệp, dự đoán hành vi, theo dõi trộm, báo hướng di chuyển, báo
con người … dùng được trong mọi tình huống". Mỗi đề cài sẵn MỘT chỗ hổng thật hay gặp (kinh nghiệm cộng
đồng: phòng kín có cửa, báo lây khu thông, cửa vào/ra, ngoài giờ, vùng nguy hiểm, vắng bất thường, báo
giả ngoài trời) — đáp án là bot phải tự thấy chỗ hổng đó (đúng thiết bị, đúng đánh giá) hoặc hỏi đúng điều.

Đáp án:
  phai_co: [{"thiet_bi", "hien_tai"?, "nen"?, "tu": [chữ]}] — phải có tình huống khớp; `tu`: tình huống /
           cảm biến thấy / vì sao chứa ÍT NHẤT một chữ (không phân biệt hoa thường); `hien_tai` / `nen` là
           một giá trị hoặc danh sách giá trị được chấp nhận.
  phai_hoi_ve: [[chữ, …], …] — mỗi nhóm: có câu hỏi chứa ít nhất một chữ của nhóm.
  khong_nen: [{"thiet_bi", "nen"}] — không tình huống nào của thiết bị đó được chọn `nen` này.
  khong_nen_tu: [{"thiet_bi", "nen", "tu"}] — như trên nhưng chỉ tình huống chứa một trong các chữ.
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
                             "tu": ["lá", "cây", "xe", "mưa", "báo giả", "gió", "côn trùng", "mèo", "chó", "nhiễu",
                                    "camera không thấy", "camera cổng không thấy"]},
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


# ── Nhà thông minh — chủ máy 30/09/2026: "bộ đề luyện này tôi cần train thật kỹ, kỹ nhất vẫn cho nhà thông
# minh". Mỗi đề một bẫy hay gặp ngoài đời mà cách cài thông thường bỏ sót.
_TAT_RADAR = "TẮT KHI VẮNG: {cb} báo vắng liền {p}–{p} phút (bot tự học theo giờ)"

DE += [
    {"ten": "thu_cung_kich_cam_bien_chuyen_dong",
     "tinh_huong": "Nhà nuôi mèo: cảm biến chuyển động (PIR) phòng khách bắt cả mèo đi đêm — đèn bật cho mèo.",
     "uv": _uv("chung cư, 1 tầng\n• Phòng khách — thông Bếp",
               {"Phòng khách": ["Chuyển động phòng khách (sóng/chuyển động)", "Camera phòng khách Person (camera)"]},
               {"light.den_pk_mc": ("Đèn trần phòng khách", "Phòng khách", [
                   "BẬT (bot học, tự làm): khi Chuyển động phòng khách có người vào, Độ sáng ≤ 20",
                   _TAT_RADAR.format(cb="Chuyển động phòng khách", p=5)])},
               ["Nhà nuôi một con mèo, đêm hay đi lại trong phòng khách."]),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_pk_mc", "hien_tai": ["sai", "khong_ro"],
                             "tu": ["mèo", "thú"]}]}},

    {"ten": "cau_thang_nha_pho_di_tu_tren_xuong",
     "tinh_huong": "Nhà phố 3 tầng: đèn cầu thang chỉ bật theo radar chân cầu thang tầng 1 — đi từ tầng 2 xuống "
                   "thì tối cho tới khi xuống tới chân cầu thang (hướng đi).",
     "uv": _uv("nhà phố, 3 tầng\n• Cầu thang — thông Phòng khách (tầng 1), Hành lang tầng 2\n"
               "• Hành lang tầng 2 — có vách với Phòng ngủ tầng 2",
               {"Cầu thang": ["Radar chân cầu thang tầng 1 (sóng/chuyển động)"],
                "Hành lang tầng 2": ["Radar hành lang tầng 2 (sóng/chuyển động)"]},
               {"light.den_cau_thang": ("Đèn cầu thang", "Cầu thang", [
                   "BẬT (bot học, tự làm): khi Radar chân cầu thang tầng 1 có người vào, từ 18:00",
                   _TAT_RADAR.format(cb="Radar chân cầu thang tầng 1", p=2)])}),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_cau_thang", "hien_tai": "sai",
                             "tu": ["tầng 2", "tầng trên", "từ trên", "đi xuống", "xuống cầu thang"]}]}},

    {"ten": "wc_rieng_trong_phong_ngu_cua_kin",
     "tinh_huong": "Ong trong hộp ở WC riêng của phòng ngủ: có cảm biến cửa WC; người tắm lâu, radar mất dấu.",
     "uv": _uv("chung cư, 1 tầng\n• Phòng ngủ master — có vách với WC master, Phòng khách\n"
               "• WC master — có vách với Phòng ngủ master",
               {"WC master": ["Radar WC master (sóng/chuyển động)", "Cửa WC master (cửa)"],
                "Phòng ngủ master": ["Radar phòng ngủ master (sóng/chuyển động)"]},
               {"light.den_wc_master": ("Đèn WC master", "WC master", [
                   "BẬT (bot học, tự làm): khi Radar WC master có người vào",
                   _TAT_RADAR.format(cb="Radar WC master", p=2)])}),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_wc_master", "hien_tai": "sai",
                             "tu": ["cửa", "tắm", "ngồi yên", "mất dấu", "đóng"]}]}},

    {"ten": "con_ngu_trua_me_vao_xem",
     "tinh_huong": "Phòng trẻ: con ngủ trưa, mẹ nhẹ nhàng vào xem con — đèn tự bật làm con thức giấc.",
     "uv": _uv("chung cư, 1 tầng\n• Phòng con — có vách với Phòng khách",
               {"Phòng con": ["Radar phòng con (sóng/chuyển động)"]},
               {"light.den_phong_con": ("Đèn phòng con", "Phòng con", [
                   "BẬT (bot học, tự làm): khi Radar phòng con có người vào, Độ sáng phòng con ≤ 60",
                   _TAT_RADAR.format(cb="Radar phòng con", p=5)])},
               ["Bé 3 tuổi ngủ trưa 12:30–14:30 trong phòng con, kéo rèm tối."]),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_phong_con", "hien_tai": ["sai", "khong_ro"],
                             "nen": ["khong_lam", "hoi", "tat", "giu"], "tu": ["ngủ trưa", "trưa", "đang ngủ", "bé ngủ"]}],
                "khong_nen_tu": [{"thiet_bi": "light.den_phong_con", "nen": "bat", "tu": ["ngủ trưa", "bé đang ngủ"]}]}},

    {"ten": "lam_ca_dem_ve_muon",
     "tinh_huong": "Chồng làm ca đêm về 23:30 lúc khung «cả nhà ngủ» chặn bật đèn — về nhà tối om; nhưng không được "
                   "đánh thức người đang ngủ.",
     "uv": _uv("chung cư, 1 tầng\n• Phòng khách — thông Bếp\n• Cửa chính mở vào Phòng khách",
               {"Phòng khách": ["Radar phòng khách (sóng/chuyển động)", "Cảm biến cửa chính (cửa)"]},
               {"light.den_hat_pk": ("Đèn hắt phòng khách", "Phòng khách", [
                   "BẬT (bot học, tự làm): khi Cảm biến cửa chính mở (chỉ khi trong 60 giây khu của thiết bị có người MỚI "
                   "vào — người đi ra thì không), từ 17:30",
                   _TAT_RADAR.format(cb="Radar phòng khách", p=5),
                   "KHUNG GIỜ «Cả nhà ngủ» 22:30–06:00: hướng bật không làm"])},
               ["Chồng làm ca đêm, thường về nhà khoảng 23:30."]),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_hat_pk", "hien_tai": ["sai", "khong_ro"],
                             "tu": ["ca đêm", "về muộn", "23", "khuya", "nửa đêm"]}]}},

    {"ten": "xem_phim_keo_rem_ban_ngay",
     "tinh_huong": "Ban ngày kéo rèm xem phim: phòng tối nhưng luật chỉ bật từ 17:00 — và thật ra người xem phim MUỐN "
                   "tối; phải hỏi chứ đừng bật.",
     "uv": _uv("chung cư, 1 tầng\n• Phòng khách — thông Bếp",
               {"Phòng khách": ["Radar phòng khách (sóng/chuyển động)", "Camera phòng khách Person (camera)"]},
               {"light.den_tran_pk2": ("Đèn trần phòng khách", "Phòng khách", [
                   "BẬT (bot học, tự làm): khi Radar phòng khách có người vào, từ 17:00, Độ sáng ≤ 50",
                   _TAT_RADAR.format(cb="Radar phòng khách hoặc Camera phòng khách Person", p=5)]),
                "media_player.tivi_pk": ("Tivi phòng khách", "Phòng khách", ["BẬT: chưa tự bật", "TẮT: không tự tắt"])}),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_tran_pk2", "nen": ["khong_lam", "hoi", "giu"],
                             "tu": ["rèm", "xem phim", "phim", "tivi"]}]}},

    {"ten": "dieu_hoa_chay_khi_cua_mo",
     "tinh_huong": "Điều hoà phòng ngủ bật theo nhiệt độ lúc có người — cửa ban công đang mở thì chạy phí điện: nên "
                   "tắt / báo.",
     "uv": _uv("nhà phố, 2 tầng\n• Phòng ngủ — có vách với Ban công tầng 2\n• Ban công tầng 2 — có vách với Phòng ngủ",
               {"Phòng ngủ": ["Radar phòng ngủ (sóng/chuyển động)", "Cửa ban công phòng ngủ (cửa)"]},
               {"climate.dieu_hoa_ngu": ("Điều hoà phòng ngủ", "Phòng ngủ", [
                   "BẬT (bot học, tự làm): khi Radar phòng ngủ có người vào, Nhiệt độ phòng ngủ > 30",
                   _TAT_RADAR.format(cb="Radar phòng ngủ", p=15)])}),
     "dap_an": {"phai_co": [{"thiet_bi": "climate.dieu_hoa_ngu", "nen": ["tat", "bao", "khong_lam", "hoi"],
                             "tu": ["cửa ban công", "cửa mở", "mở cửa", "cửa đang mở"]}]}},

    {"ten": "quan_ao_phoi_lam_nhieu_radar",
     "tinh_huong": "Ban công phơi quần áo: gió thổi quần áo làm radar ban công báo có người cả buổi — đèn ban công "
                   "sáng suốt tối. Camera ban công không thấy ai.",
     "uv": _uv("chung cư, 1 tầng\n• Ban công — có vách với Bếp",
               {"Ban công": ["Radar ban công (sóng/chuyển động)", "Camera ban công Person (camera)"]},
               {"light.den_ban_cong": ("Đèn ban công", "Ban công", [
                   "BẬT (bot học, tự làm): khi Radar ban công có người vào, Độ sáng ban công ≤ 15",
                   _TAT_RADAR.format(cb="Radar ban công", p=3)])},
               ["Ban công là chỗ phơi quần áo, máy giặt đặt ở đó."]),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_ban_cong", "hien_tai": "sai",
                             "tu": ["gió", "quần áo", "phơi", "nhiễu", "rèm"]}]}},

    {"ten": "bep_cua_kinh_radar_xuyen",
     "tinh_huong": "Bếp có cửa kính lùa: radar bếp xuyên kính bắt người ngồi sofa sát cửa kính ở phòng khách — đèn "
                   "bếp bật / không tắt dù bếp trống.",
     "uv": _uv("chung cư, 1 tầng\n• Bếp — có vách với Phòng khách (cửa kính lùa)\n• Phòng khách — có vách với Bếp",
               {"Bếp": ["Radar bếp (sóng/chuyển động)"], "Phòng khách": ["Camera phòng khách Person (camera)"]},
               {"light.den_bep": ("Đèn bếp", "Bếp", [
                   "BẬT (bot học, tự làm): khi Radar bếp có người vào, từ 17:00",
                   _TAT_RADAR.format(cb="Radar bếp", p=3)])},
               ["Sofa phòng khách kê sát cửa kính bếp."]),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_bep", "hien_tai": "sai",
                             "tu": ["kính", "xuyên", "lây", "sofa", "phòng khách"]}]}},

    {"ten": "tivi_tu_bat_khi_khong_ai",
     "tinh_huong": "Đèn hắt tivi đi theo tivi: tivi bật từ điện thoại ở phòng khác (con mở YouTube) hay tự bật cập nhật "
                   "đêm — đèn sáng trong phòng khách không người.",
     "uv": _uv("chung cư, 1 tầng\n• Phòng khách — thông Bếp",
               {"Phòng khách": ["Radar phòng khách (sóng/chuyển động)"]},
               {"light.den_hat_tivi": ("Đèn hắt tivi", "Phòng khách", [
                   "BẬT (luật anh đặt «Xem tivi»): khi «Tivi phòng khách là on/playing» có người vào",
                   "TẮT (luật anh đặt «Tivi tắt»): khi «Tivi phòng khách là on/playing» vắng"])}),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_hat_tivi", "hien_tai": ["sai", "khong_ro"],
                             "tu": ["không ai", "không có ai", "vắng", "tự bật", "phòng khác", "điện thoại", "cập nhật"]}]}},

    {"ten": "cua_chinh_mo_luc_2h_sang",
     "tinh_huong": "Cả nhà ngủ, 2 giờ sáng cửa chính mở: có thể là trộm (hoặc người nhà ra ngoài) — không chỉ lo đèn.",
     "uv": _uv("chung cư, 1 tầng\n• Phòng khách — thông Bếp\n• Cửa chính mở vào Phòng khách",
               {"Phòng khách": ["Radar phòng khách (sóng/chuyển động)", "Cảm biến cửa chính (cửa)",
                                "Camera phòng khách Person (camera)"]},
               {"light.den_tran_pk3": ("Đèn trần phòng khách", "Phòng khách", [
                   "BẬT (bot học, tự làm): khi Cảm biến cửa chính mở (chỉ khi trong 60 giây khu của thiết bị có người MỚI "
                   "vào — người đi ra thì không), từ 17:30",
                   _TAT_RADAR.format(cb="Radar phòng khách hoặc Camera phòng khách Person", p=5),
                   "KHUNG GIỜ «Cả nhà ngủ» 22:30–06:00: hướng bật luôn hỏi"])},
               nguoi=["Chồng (home)", "Vợ (home)", "Điện thoại chồng (home)", "Điện thoại vợ (home)"]),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_tran_pk3", "nen": "bao",
                             "tu": ["đêm", "2 giờ", "2h", "khuya", "rạng sáng", "trộm", "lạ"]}]}},

    {"ten": "nguoi_om_nam_ca_ngay",
     "tinh_huong": "Người ốm nằm nghỉ cả ngày trong phòng ngủ: radar mất dấu người nằm yên — đèn/quạt tắt trước mặt người.",
     "uv": _uv("chung cư, 1 tầng\n• Phòng ngủ — có vách với Phòng khách",
               {"Phòng ngủ": ["Radar phòng ngủ (sóng/chuyển động)"]},
               {"fan.quat_ngu": ("Quạt phòng ngủ", "Phòng ngủ", [
                   "BẬT: có người ở lại ≥ 3 phút (hợp các cảm biến Radar phòng ngủ) thì HỎI anh để học",
                   _TAT_RADAR.format(cb="Radar phòng ngủ", p=3)])}),
     "dap_an": {"phai_co": [{"thiet_bi": "fan.quat_ngu", "hien_tai": "sai",
                             "tu": ["nằm", "ngủ", "ngồi yên", "mất dấu", "ốm", "nằm yên"]}]}},

    {"ten": "tre_nho_vao_bep_khi_dang_nau",
     "tinh_huong": "Nhà có bé 2 tuổi: bé lẫm chẫm vào bếp lúc bếp từ đang nấu — phải BÁO; bếp không bao giờ tự bật.",
     "uv": _uv("nhà phố, 2 tầng\n• Bếp — thông Phòng khách",
               {"Bếp": ["Radar bếp (sóng/chuyển động)", "Camera bếp Person (camera)"]},
               {"switch.bep_tu": ("Bếp từ", "Bếp", ["BẬT: chưa tự bật (luật học chưa đủ tin)", "TẮT: không tự tắt"])},
               ["Nhà có bé 2 tuổi hay chạy vào bếp."]),
     "dap_an": {"phai_co": [{"thiet_bi": "switch.bep_tu", "nen": "bao", "tu": ["bé", "trẻ", "con"]}],
                "khong_nen": [{"thiet_bi": "switch.bep_tu", "nen": "bat"}]}},

    {"ten": "cua_cuon_garage_quen_dong",
     "tinh_huong": "Garage nhà phố: cửa cuốn mở rồi quên đóng tới đêm — đèn garage chỉ lo sáng/tối; phải báo cửa còn mở.",
     "uv": _uv("nhà phố, 3 tầng\n• Garage — thông Phòng khách (tầng 1)\n• Cửa cuốn mở ra đường",
               {"Garage": ["Radar garage (sóng/chuyển động)", "Cửa cuốn garage (cửa)"]},
               {"light.den_garage": ("Đèn garage", "Garage", [
                   "BẬT (bot học, tự làm): khi Cửa cuốn garage mở (chỉ khi trong 60 giây khu của thiết bị có người MỚI "
                   "vào — người đi ra thì không)",
                   _TAT_RADAR.format(cb="Radar garage", p=3)])}),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_garage", "nen": "bao",
                             "tu": ["quên", "chưa đóng", "còn mở", "mở lâu", "để mở"]}]}},

    {"ten": "day_di_ve_sinh_luc_nua_dem",
     "tinh_huong": "3 giờ sáng dậy đi vệ sinh: bật đèn trần chói làm cả phòng thức; hỏi qua Zalo lúc đó cũng vô duyên — "
                   "nên không làm (hoặc hỏi chủ nhà trước có muốn đèn ngủ mờ không).",
     "uv": _uv("chung cư, 1 tầng\n• Phòng ngủ — có vách với Nhà tắm\n• Nhà tắm — có vách với Phòng ngủ",
               {"Phòng ngủ": ["Radar phòng ngủ (sóng/chuyển động)"], "Nhà tắm": ["Radar nhà tắm (sóng/chuyển động)"]},
               {"light.den_tran_ngu": ("Đèn trần phòng ngủ", "Phòng ngủ", [
                   "BẬT (bot học, tự làm): khi Radar phòng ngủ có người vào, Độ sáng phòng ngủ ≤ 30",
                   _TAT_RADAR.format(cb="Radar phòng ngủ", p=5),
                   "KHUNG GIỜ «Ngủ» 22:00–06:00: hướng bật luôn hỏi"])}),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_tran_ngu", "nen": ["khong_lam", "hoi"],
                             "tu": ["vệ sinh", "đêm", "3 giờ", "nửa đêm", "dậy"]}]}},
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
    def khop(gia_tri: str, mong: Any) -> bool:
        return mong is None or (gia_tri in mong if isinstance(mong, (list, tuple)) else gia_tri == mong)

    for y in dap_an.get("phai_co") or []:
        if not any(x["thiet_bi"] == y["thiet_bi"] and khop(x["hien_tai"], y.get("hien_tai"))
                   and khop(x["nen"], y.get("nen")) and any(t.lower() in _chu(x) for t in y["tu"]) for x in kb):
            loi.append(f"thiếu tình huống {y}")
    hoi = [str(x.get("hoi") or "").lower() for x in kb]
    for nhom in dap_an.get("phai_hoi_ve") or []:
        if not any(t.lower() in h for h in hoi for t in nhom):
            loi.append(f"thiếu câu hỏi về {nhom}")
    for y in dap_an.get("khong_nen") or []:
        if any(x["thiet_bi"] == y["thiet_bi"] and x["nen"] == y["nen"] for x in kb):
            loi.append(f"không được chọn {y}")
    for y in dap_an.get("khong_nen_tu") or []:
        if any(x["thiet_bi"] == y["thiet_bi"] and x["nen"] == y["nen"] and any(t.lower() in _chu(x) for t in y["tu"])
               for x in kb):
            loi.append(f"không được chọn {y}")
    return loi
