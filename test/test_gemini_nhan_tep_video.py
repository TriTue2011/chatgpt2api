"""Tệp không phải ảnh phải đi lọt tới Gemini.

Home Assistant gửi video camera theo dạng {"type":"file","file":{"file_data":...,
"filename":...}} — base64 thuần, không kèm mime type. Không nhận dạng này thì
video từ Home Assistant không bao giờ tới được Gemini.
"""

from services.providers.gemini_free import _convert_request


def _phan_media(contents):
    return [p for c in contents for p in c["parts"] if "inlineData" in p]


def test_video_mp4_thanh_inline_data():
    contents, _si, _tools = _convert_request([{"role": "user", "content": [
        {"type": "text", "text": "Mô tả video"},
        {"type": "file", "file": {"file_data": "AAAA", "filename": "cua.mp4"}},
    ]}], None)
    media = _phan_media(contents)
    assert len(media) == 1
    assert media[0]["inlineData"]["mimeType"] == "video/mp4"
    assert media[0]["inlineData"]["data"] == "AAAA"


def test_ten_tep_la_thi_van_gui_di():
    # Không đoán được mime thì vẫn gửi, để Gemini tự quyết — thà thử còn hơn
    # nuốt mất tệp mà không báo gì.
    contents, _si, _tools = _convert_request([{"role": "user", "content": [
        {"type": "file", "file": {"file_data": "BBBB", "filename": "khong_duoi"}},
    ]}], None)
    assert len(_phan_media(contents)) == 1


def test_file_data_dang_data_uri_van_doc_duoc():
    contents, _si, _tools = _convert_request([{"role": "user", "content": [
        {"type": "file", "file": {"file_data": "data:video/mp4;base64,CCCC", "filename": "x.mp4"}},
    ]}], None)
    media = _phan_media(contents)
    assert media[0]["inlineData"]["mimeType"] == "video/mp4"
    assert media[0]["inlineData"]["data"] == "CCCC"


def test_file_rong_thi_bo_qua():
    contents, _si, _tools = _convert_request([{"role": "user", "content": [
        {"type": "text", "text": "chỉ có chữ"},
        {"type": "file", "file": {"file_data": "", "filename": "rong.mp4"}},
    ]}], None)
    assert _phan_media(contents) == []
