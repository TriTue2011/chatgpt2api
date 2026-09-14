"""Mã lỗi của trình phát → câu tiếng Việt. Dùng chung cho tab YouTube (web hiện
nguyên câu) và bot chat mở nhạc."""

THONG_BAO = {
    "url_lan_khong_hop_le": "Địa chỉ LAN phải dạng http://IP:cổng, không kèm đường dẫn.",
    "ha_khong_doc_duoc": "Không đọc được Home Assistant — kiểm tra kết nối HA trong Cài đặt.",
    "invalid_target_entity": "Thiết bị không hợp lệ.",
    "invalid_target_entities": "Hãy chọn từ 1 tới 16 thiết bị.",
    "invalid_search_query": "Nhập từ khoá (tối đa 120 ký tự) hoặc dán link YouTube.",
    "invalid_search_source": "Nguồn tìm kiếm không hỗ trợ.",
    "search_unavailable": "Không tìm được lúc này, thử lại sau.",
    "stream_unavailable": "Không lấy được luồng nhạc của bài này.",
    "unsupported_source": "Nguồn phát không hỗ trợ.",
    "invalid_youtube_target": "Link hoặc mã YouTube không hợp lệ.",
    "invalid_zing_target": "Link Zing MP3 không hợp lệ.",
    "unverified_zing_target": "Bài Zing này đã hết hạn tìm kiếm — tìm lại rồi phát.",
    "invalid_http_audio_target": "URL phải là file âm thanh trực tiếp (MP3, AAC, FLAC, OGG, HLS).",
    "youtube_audio_requires_video": "Loa chỉ phát được một video, không phát cả danh sách.",
    "webos_playlist_requires_video": "Tivi LG chỉ mở được một video, không mở cả danh sách.",
    "cast_playlist_requires_video": "Tivi Cast chỉ mở được một video, không mở cả danh sách.",
    "khong_co_thiet_bi_phat_duoc": "Không thiết bị nào đã chọn đang trực tuyến và nhận phát nhạc.",
    "ha_tu_choi": "Home Assistant không nhận lệnh — thiết bị có thể đang tắt.",
    "lenh_khong_ho_tro": "Lệnh điều khiển không hỗ trợ.",
    "invalid_volume_level": "Âm lượng phải từ 0 tới 100%.",
    "phien_da_ket_thuc": "Nhóm loa đó đã dừng phát.",
    "het_hang_doi": "Hết bài trong hàng đợi.",
    "buoc_khong_hop_le": "Chỉ chuyển được bài kế hoặc bài trước.",
    "invalid_seek_position": "Vị trí tua không hợp lệ.",
    "invalid_request": "Yêu cầu không hợp lệ.",
    "public_base_url_required": "Chưa có địa chỉ LAN cho loa tải nhạc.",
    "playlist_not_found": "Playlist không còn — tải lại danh sách.",
    "playlist_name_required": "Đặt tên cho playlist.",
    "too_many_playlists": "Đã đủ 100 playlist — xoá bớt rồi tạo mới.",
    "playlist_full": "Playlist đã đủ 500 bài.",
    "invalid_playlist_index": "Vị trí bài trong playlist không hợp lệ.",
    "invalid_playlist_action": "Lệnh playlist không hỗ trợ.",
    "invalid_playlist_link": "Dán link playlist YouTube, link album/playlist Zing MP3 hoặc mã chia sẻ (TTPL1.…).",
    "invalid_share_code": "Mã chia sẻ không đúng hoặc bị cắt mất một phần.",
    "playlist_unavailable": "Không đọc được playlist này — link sai, playlist riêng tư, hoặc YouTube/Zing đang lỗi; thử lại sau.",
    "playlist_empty": "Playlist này không có bài nào nghe được (riêng tư, VIP hoặc đã xoá).",
}


def cau_loi(ma: str) -> str:
    return THONG_BAO.get(ma, THONG_BAO["invalid_request"])
