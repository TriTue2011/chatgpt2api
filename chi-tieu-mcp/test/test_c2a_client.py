"""Test trực tiếp app/c2a_client.py::hoi_ai_phan_tich() -- trước đây hàm này
chỉ được test gián tiếp qua route web (monkeypatch hẳn hàm đi), nội bộ hàm
(guard key rỗng, xử lý status non-2xx, parse response, shape body gửi đi)
chưa từng được xác nhận thật. KHÔNG gọi mạng thật: dùng httpx.MockTransport
để chặn request ở tầng transport, trả response giả lập."""
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Giữ tham chiếu class AsyncClient GỐC trước khi bất kỳ test nào monkeypatch
# httpx.AsyncClient -- tránh đệ quy vô hạn khi factory bên dưới tự gọi lại
# chính nó.
_AsyncClientThat = httpx.AsyncClient


def _chan_mang(monkeypatch, handler):
    """Ép MỌI httpx.AsyncClient(...) được tạo trong lúc test chạy dùng
    httpx.MockTransport(handler) thay vì transport mạng thật -- bất kể
    app/c2a_client.py gọi AsyncClient(...) với kwargs nào (vd timeout=60.0),
    nên không phụ thuộc chi tiết implementation, chỉ chặn đúng ở biên I/O."""
    def _factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _AsyncClientThat(*args, **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", _factory)


def _response_ok(noi_dung="Phân tích giả lập từ C2A."):
    return httpx.Response(200, json={"choices": [{"message": {"content": noi_dung}}]})


@pytest.mark.asyncio
async def test_hoi_ai_phan_tich_thieu_key_raise_truoc_khi_goi_mang(monkeypatch):
    from app import c2a_client
    monkeypatch.setattr(c2a_client, "C2A_AUTH_KEY", "")

    def _khong_duoc_goi(request):
        raise AssertionError(
            "khong duoc phep goi mang khi C2A_AUTH_KEY rong -- guard phai "
            "raise TRUOC khi tao request"
        )

    _chan_mang(monkeypatch, _khong_duoc_goi)
    with pytest.raises(RuntimeError):
        await c2a_client.hoi_ai_phan_tich("prompt bat ky")


@pytest.mark.asyncio
async def test_hoi_ai_phan_tich_gui_model_auto_text_va_user_rieng(monkeypatch):
    """Thay ràng buộc cũ "không gửi model" (23/09/2026): không có model thì
    C2A coi là câu trả lời cho loa Home Assistant -> verbalize xoá | ** #, đổi
    % thành "phần trăm", câu trả lời trên /ui dính thành 1 khối. "auto:text"
    vẫn auto route y như cũ (C2A _strip_marker("auto:text") == "auto"), chỉ
    tắt verbalize. user riêng -> kho ký ức C2A riêng (admin:chi-tieu-bot-ui),
    không lẫn vào kho admin chung."""
    from app import c2a_client
    monkeypatch.setattr(c2a_client, "C2A_AUTH_KEY", "khoa-test")

    request_bat_duoc = {}

    def _bat_request(request):
        request_bat_duoc["request"] = request
        return _response_ok()

    _chan_mang(monkeypatch, _bat_request)
    await c2a_client.hoi_ai_phan_tich("nội dung prompt")

    body = json.loads(request_bat_duoc["request"].content)
    assert body["model"] == "auto:text"
    assert body["user"] == "chi-tieu-bot-ui"
    assert body["stream"] is False


@pytest.mark.asyncio
async def test_hoi_ai_phan_tich_la_luot_goi_tach_biet_khong_vao_nhanh_chuyen_biet(monkeypatch):
    """Đo thật 23/09/2026: prompt JSON có câu "CHỈ trả về 1 object JSON" -> C2A
    bỏ dấu thành "tra ve 1" khớp từ khoá "ve 1 " (vẽ 1) -> "auto" đẩy sang nhánh
    VẼ ẢNH, chạy 83s trả ảnh PNG, /ui báo lỗi. x_allowed_groups = [] là cơ chế
    "lượt gọi TÁCH BIỆT" có sẵn của C2A (openai_v1_chat_complete._tach_biet /
    _thread_denies): không nhánh chuyên biệt nào, không chèn tài liệu tra cứu."""
    from app import c2a_client
    monkeypatch.setattr(c2a_client, "C2A_AUTH_KEY", "khoa-test")
    request_bat_duoc = {}

    def _bat_request(request):
        request_bat_duoc["request"] = request
        return _response_ok()

    _chan_mang(monkeypatch, _bat_request)
    await c2a_client.hoi_ai_phan_tich("nội dung prompt")
    assert json.loads(request_bat_duoc["request"].content)["x_allowed_groups"] == []


@pytest.mark.asyncio
async def test_hoi_ai_phan_tich_ca_retry_nam_trong_han_cloudflare(monkeypatch):
    """/ui đi qua Cloudflare Tunnel, Cloudflare cắt request sau ~100s (524): lần
    thử + retry phải chung 1 ngân sách <= 95s. 502 tới muộn (còn < 30s) thì
    không retry nữa -- báo lỗi ngay còn hơn để Cloudflare cắt ngang."""
    from app import c2a_client
    monkeypatch.setattr(c2a_client, "C2A_AUTH_KEY", "khoa-test")
    dong_ho = {"t": 1000.0}
    monkeypatch.setattr(c2a_client, "_dong_ho", lambda: dong_ho["t"])
    han_doc = []

    def _502_cham(request):
        han_doc.append(request.extensions["timeout"]["read"])
        dong_ho["t"] += 70  # lượt này mất 70s rồi mới 502
        return httpx.Response(502, json={"error": "Bad Gateway"})

    _chan_mang(monkeypatch, _502_cham)
    with pytest.raises(httpx.HTTPStatusError):
        await c2a_client.hoi_ai_phan_tich("prompt bat ky")
    assert len(han_doc) == 1          # còn 25s < 30s -> không retry
    assert han_doc[0] <= 95


@pytest.mark.asyncio
async def test_hoi_ai_phan_tich_retry_dung_phan_thoi_gian_con_lai(monkeypatch):
    from app import c2a_client
    monkeypatch.setattr(c2a_client, "C2A_AUTH_KEY", "khoa-test")
    dong_ho = {"t": 1000.0}
    monkeypatch.setattr(c2a_client, "_dong_ho", lambda: dong_ho["t"])
    han_doc = []

    def _502_nhanh_roi_200(request):
        han_doc.append(request.extensions["timeout"]["read"])
        if len(han_doc) == 1:
            dong_ho["t"] += 37
            return httpx.Response(502, json={"error": "Bad Gateway"})
        return _response_ok("Lần 2.")

    _chan_mang(monkeypatch, _502_nhanh_roi_200)
    assert await c2a_client.hoi_ai_phan_tich("prompt bat ky") == "Lần 2."
    assert han_doc[0] <= 95 and abs(han_doc[1] - (han_doc[0] - 37)) < 0.5


@pytest.mark.asyncio
async def test_hoi_ai_phan_tich_gui_dung_prompt_va_auth_header(monkeypatch):
    """Xác nhận thêm shape body/header -- cùng cơ chế Bearer tĩnh với
    gui_canh_bao(), messages chứa đúng nội dung prompt truyền vào."""
    from app import c2a_client
    monkeypatch.setattr(c2a_client, "C2A_AUTH_KEY", "khoa-test")

    request_bat_duoc = {}

    def _bat_request(request):
        request_bat_duoc["request"] = request
        return _response_ok()

    _chan_mang(monkeypatch, _bat_request)
    await c2a_client.hoi_ai_phan_tich("nội dung prompt độc nhất")

    req = request_bat_duoc["request"]
    body = json.loads(req.content)
    assert body["messages"] == [{"role": "user", "content": "nội dung prompt độc nhất"}]
    assert req.headers["authorization"] == "Bearer khoa-test"


@pytest.mark.asyncio
async def test_hoi_ai_phan_tich_loi_http_non_2xx_raise(monkeypatch):
    from app import c2a_client
    monkeypatch.setattr(c2a_client, "C2A_AUTH_KEY", "khoa-test")

    def _loi_500(request):
        return httpx.Response(500, json={"error": "server error"})

    _chan_mang(monkeypatch, _loi_500)
    with pytest.raises(httpx.HTTPStatusError):
        await c2a_client.hoi_ai_phan_tich("prompt bat ky")


@pytest.mark.asyncio
async def test_hoi_ai_phan_tich_retry_1_lan_khi_5xx_roi_thanh_cong(monkeypatch):
    """Phát hiện 22/09/2026: "auto" model routing của C2A thỉnh thoảng trả 502
    chập chờn -- gọi lại NGAY với cùng prompt thường thành công (đo thật: 502
    sau 37s, gọi lại thành công sau 17s). Retry 1 lần cho hoi_ai_phan_tich()
    thay vì bắt người dùng tự bấm "thử lại" trên /ui."""
    from app import c2a_client
    monkeypatch.setattr(c2a_client, "C2A_AUTH_KEY", "khoa-test")

    so_lan_goi = {"n": 0}

    def _502_roi_200(request):
        so_lan_goi["n"] += 1
        if so_lan_goi["n"] == 1:
            return httpx.Response(502, json={"error": "Bad Gateway"})
        return _response_ok("Thành công sau khi retry.")

    _chan_mang(monkeypatch, _502_roi_200)
    ket_qua = await c2a_client.hoi_ai_phan_tich("prompt bat ky")

    assert ket_qua == "Thành công sau khi retry."
    assert so_lan_goi["n"] == 2


@pytest.mark.asyncio
async def test_hoi_ai_phan_tich_5xx_hai_lan_lien_tiep_raise_va_chi_goi_dung_2_lan(monkeypatch):
    """Retry CÓ GIỚI HẠN (1 lần) -- fail liên tục vẫn phải raise, không lặp
    vô hạn, và không gọi mạng quá 2 lần."""
    from app import c2a_client
    monkeypatch.setattr(c2a_client, "C2A_AUTH_KEY", "khoa-test")

    so_lan_goi = {"n": 0}

    def _luon_502(request):
        so_lan_goi["n"] += 1
        return httpx.Response(502, json={"error": "Bad Gateway"})

    _chan_mang(monkeypatch, _luon_502)
    with pytest.raises(httpx.HTTPStatusError):
        await c2a_client.hoi_ai_phan_tich("prompt bat ky")

    assert so_lan_goi["n"] == 2


@pytest.mark.asyncio
async def test_hoi_ai_phan_tich_khong_retry_khi_400_loi_client(monkeypatch):
    """Lỗi 4xx là lỗi CỦA REQUEST (vd body sai) -- gọi lại y hệt sẽ lại lỗi y
    hệt, retry chỉ tốn thời gian chờ vô ích. Chỉ retry 5xx (lỗi tạm thời phía
    C2A/model), không retry 4xx."""
    from app import c2a_client
    monkeypatch.setattr(c2a_client, "C2A_AUTH_KEY", "khoa-test")

    so_lan_goi = {"n": 0}

    def _400(request):
        so_lan_goi["n"] += 1
        return httpx.Response(400, json={"error": "bad request"})

    _chan_mang(monkeypatch, _400)
    with pytest.raises(httpx.HTTPStatusError):
        await c2a_client.hoi_ai_phan_tich("prompt bat ky")

    assert so_lan_goi["n"] == 1


@pytest.mark.asyncio
async def test_hoi_ai_phan_tich_200_hop_le_tra_dung_noi_dung(monkeypatch):
    from app import c2a_client
    monkeypatch.setattr(c2a_client, "C2A_AUTH_KEY", "khoa-test")

    _chan_mang(monkeypatch, lambda request: _response_ok("Nội dung AI trả lời."))
    ket_qua = await c2a_client.hoi_ai_phan_tich("prompt bat ky")
    assert ket_qua == "Nội dung AI trả lời."


# --- Fix 6: guard content không phải chuỗi/rỗng -- raise RuntimeError thay vì
# trả nguyên văn "null"/chuỗi rỗng ra /ui, đi đúng nhánh lỗi 502 sẵn có ở
# app/web.py::api_hoi_ai_phan_tich thay vì render kết quả vô nghĩa.


@pytest.mark.asyncio
async def test_hoi_ai_phan_tich_content_rong_raise(monkeypatch):
    from app import c2a_client
    monkeypatch.setattr(c2a_client, "C2A_AUTH_KEY", "khoa-test")

    _chan_mang(monkeypatch, lambda request: _response_ok(""))
    with pytest.raises(RuntimeError):
        await c2a_client.hoi_ai_phan_tich("prompt bat ky")


@pytest.mark.asyncio
async def test_hoi_ai_phan_tich_content_null_raise(monkeypatch):
    from app import c2a_client
    monkeypatch.setattr(c2a_client, "C2A_AUTH_KEY", "khoa-test")

    def _content_null(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": None}}]})

    _chan_mang(monkeypatch, _content_null)
    with pytest.raises(RuntimeError):
        await c2a_client.hoi_ai_phan_tich("prompt bat ky")


# --- gui_canh_bao(): kênh Zalo Cá Nhân, KHÔNG phải Bot API chính thức -------
#
# Phát hiện 22/09/2026: gui_canh_bao() (bản cũ) gọi /api/zalo-bot/send --
# Bot API chính thức, gửi "thành công" nhưng tới một bot khác, không phải nơi
# chủ máy chat hàng ngày. Chủ máy chat với chi-tieu-bot qua kênh **Zalo Cá
# Nhân** (zca-js) -- xác nhận qua log C2A: mcp_tool_exec ghi_chi_tieu chạy
# trong session "v1|zalop|<thread_id>||". api/zalo_bot.py tự ghi rõ "Hai kênh
# chạy song song, khác token, khác endpoint, không chia sẻ trạng thái nào" --
# nên cảnh báo gửi qua kênh Bot không bao giờ tới đúng người. Đổi sang POST
# /api/zalo-personal/test-send (JSON, có thread_id) -- endpoint DUY NHẤT của
# kênh Zalo Cá Nhân cho phép chủ động đẩy tin (tên "test-send" nhưng không
# có đường nào khác để gọi ngoài luồng webhook).


def _response_ok_zalo_personal():
    return httpx.Response(200, json={"ok": True, "kieu": "text", "chat_id": "1234567890123456789"})


@pytest.mark.asyncio
async def test_gui_canh_bao_thieu_key_raise_truoc_khi_goi_mang(monkeypatch):
    from app import c2a_client
    monkeypatch.setattr(c2a_client, "C2A_AUTH_KEY", "")
    monkeypatch.setattr(c2a_client, "C2A_ZALO_PERSONAL_THREAD_ID", "1234567890123456789")

    def _khong_duoc_goi(request):
        raise AssertionError(
            "khong duoc phep goi mang khi C2A_AUTH_KEY rong -- guard phai "
            "raise TRUOC khi tao request"
        )

    _chan_mang(monkeypatch, _khong_duoc_goi)
    with pytest.raises(RuntimeError):
        await c2a_client.gui_canh_bao("noi dung bat ky")


@pytest.mark.asyncio
async def test_gui_canh_bao_thieu_thread_id_raise_truoc_khi_goi_mang(monkeypatch):
    """Kênh Zalo Cá Nhân không có "admin mặc định" như Bot API cũ (để trống
    bot_id/chat_id trước đây tự rơi về admin của bot đầu danh sách) --
    /api/zalo-personal/test-send BẮT BUỘC thread_id, thiếu thì trả 400. Raise
    SỚM với thông báo rõ ràng thay vì để lỗi HTTP mơ hồ lộ ra tận /ui."""
    from app import c2a_client
    monkeypatch.setattr(c2a_client, "C2A_AUTH_KEY", "khoa-test")
    monkeypatch.setattr(c2a_client, "C2A_ZALO_PERSONAL_THREAD_ID", "")

    def _khong_duoc_goi(request):
        raise AssertionError(
            "khong duoc phep goi mang khi thieu C2A_ZALO_PERSONAL_THREAD_ID -- "
            "guard phai raise TRUOC khi tao request"
        )

    _chan_mang(monkeypatch, _khong_duoc_goi)
    with pytest.raises(RuntimeError):
        await c2a_client.gui_canh_bao("noi dung bat ky")


@pytest.mark.asyncio
async def test_gui_canh_bao_goi_dung_endpoint_zalo_ca_nhan_voi_thread_id(monkeypatch):
    from app import c2a_client
    monkeypatch.setattr(c2a_client, "C2A_AUTH_KEY", "khoa-test")
    monkeypatch.setattr(c2a_client, "C2A_ZALO_PERSONAL_THREAD_ID", "1234567890123456789")

    request_bat_duoc = {}

    def _bat_request(request):
        request_bat_duoc["request"] = request
        return _response_ok_zalo_personal()

    _chan_mang(monkeypatch, _bat_request)
    await c2a_client.gui_canh_bao("Cảnh báo test")

    req = request_bat_duoc["request"]
    assert req.url.path == "/api/zalo-personal/test-send"
    body = json.loads(req.content)
    assert body == {"thread_id": "1234567890123456789", "text": "Cảnh báo test", "type": 0}
    assert req.headers["authorization"] == "Bearer khoa-test"


@pytest.mark.asyncio
async def test_gui_canh_bao_loi_http_non_2xx_raise(monkeypatch):
    from app import c2a_client
    monkeypatch.setattr(c2a_client, "C2A_AUTH_KEY", "khoa-test")
    monkeypatch.setattr(c2a_client, "C2A_ZALO_PERSONAL_THREAD_ID", "1234567890123456789")

    def _loi_500(request):
        return httpx.Response(500, json={"error": "server error"})

    _chan_mang(monkeypatch, _loi_500)
    with pytest.raises(httpx.HTTPStatusError):
        await c2a_client.gui_canh_bao("noi dung bat ky")


@pytest.mark.asyncio
async def test_gui_canh_bao_tra_ve_json_response(monkeypatch):
    from app import c2a_client
    monkeypatch.setattr(c2a_client, "C2A_AUTH_KEY", "khoa-test")
    monkeypatch.setattr(c2a_client, "C2A_ZALO_PERSONAL_THREAD_ID", "1234567890123456789")

    _chan_mang(monkeypatch, lambda request: _response_ok_zalo_personal())
    ket_qua = await c2a_client.gui_canh_bao("noi dung bat ky")
    assert ket_qua["ok"] is True
