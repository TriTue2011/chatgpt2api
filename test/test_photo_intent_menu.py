"""Photo menu: RAG knowledge/teacher, analyze, generate + prompt stages."""
from __future__ import annotations

import services.photo_intent as phi


def test_allowed_intents_full():
    assert phi.allowed_intents(None) == phi.ALL_INTENTS


def test_allowed_intents_filter():
    a = phi.allowed_intents({"rag", "teacher"})
    assert phi.RAG_KNOWLEDGE in a
    assert phi.RAG_TEACHER in a
    assert phi.ANALYZE in a  # always
    assert phi.GENERATE not in a


def test_allowed_intents_image():
    a = phi.allowed_intents({"image"})
    assert phi.GENERATE in a
    assert phi.ANALYZE in a
    assert phi.RAG_KNOWLEDGE not in a


def test_parse_intent_numbers():
    allowed = set(phi.INTENT_ORDER)
    assert phi.parse_intent("1", allowed) == phi.RAG_KNOWLEDGE
    assert phi.parse_intent("2", allowed) == phi.RAG_TEACHER
    assert phi.parse_intent("3", allowed) == phi.ANALYZE
    assert phi.parse_intent("4", allowed) == phi.GENERATE


def test_parse_intent_keywords():
    assert phi.parse_intent("nạp wiki") == phi.RAG_KNOWLEDGE
    assert phi.parse_intent("sgk") == phi.RAG_TEACHER
    assert phi.parse_intent("phân tích") == phi.ANALYZE
    assert phi.parse_intent("vẽ lại anime") == phi.GENERATE


def test_la_anh_nhan_dung_duoi():
    for ok in ("Concor-5mg-10.jpg", "a.PNG", "x.jpeg", "s.webp",
               "p.HEIC", "q.heif", "r.jxl", "t.tiff", "u.bmp", "g.gif"):
        assert phi.la_anh(ok), ok
    for no in ("doc.pdf", "s.docx", "v.mp4", "a.srt", "note.txt", "", "noext"):
        assert not phi.la_anh(no), no


def test_parse_intent_6_la_luu_online_7_facebook():
    # Menu đầy đủ 7 mục (bật kho + facebook + dịch): "6"=Lưu kho, "7"=Facebook.
    full = set(phi.INTENT_ORDER)
    assert phi.parse_intent("6", full) == phi.LUU_ONLINE
    assert phi.parse_intent("7", full) == phi.FACEBOOK


def test_y_dinh_da_moi_giu_bo_da_hien():
    shown = {phi.RAG_KNOWLEDGE, phi.ANALYZE, phi.LUU_ONLINE}
    # Bản chờ có lưu bộ đã hiện → dùng đúng nó, không phải mặc định tính lại.
    assert phi.y_dinh_da_moi({"intents": shown}, set(phi.INTENT_ORDER)) == shown
    # Không lưu (bản chờ cũ) → về mặc định.
    assert phi.y_dinh_da_moi({}, {phi.ANALYZE}) == {phi.ANALYZE}


def test_giai_so_theo_bo_da_hien_khong_lech():
    # Lỗi thật (Zalo cá nhân 05/09): menu hiện 6 mục có ☁️ Lưu kho ở số 6; bấm
    # "6" phải ra LUU_ONLINE dù bộ mặc định tính lại có khác (mất kho → số lệch,
    # "6" rơi xuống model). Giải số PHẢI theo bộ ĐÃ HIỆN lưu ở bản chờ.
    shown = {phi.RAG_KNOWLEDGE, phi.RAG_TEACHER, phi.ANALYZE, phi.GENERATE,
             phi.DICH, phi.LUU_ONLINE}
    bo = phi.y_dinh_da_moi({"intents": shown}, {phi.ANALYZE})  # mặc định co lại
    assert phi.parse_intent("6", bo) == phi.LUU_ONLINE


def test_needs_prompt_analyze_generate():
    assert phi.needs_prompt(phi.GENERATE, "4") is True
    assert phi.needs_prompt(phi.GENERATE, "vẽ") is True
    assert phi.needs_prompt(phi.GENERATE, "vẽ lại phong cách anime chi tiết") is False
    assert phi.needs_prompt(phi.ANALYZE, "3") is True
    assert phi.needs_prompt(phi.ANALYZE, "phân tích") is True
    assert phi.needs_prompt(phi.ANALYZE, "đọc chữ trong ảnh giúp em") is False
    assert phi.needs_prompt(phi.RAG_KNOWLEDGE, "") is False


def test_ask_text_respects_filter():
    t = phi.ask_text({phi.ANALYZE, phi.GENERATE})
    assert "Phân tích" in t
    assert "Tạo ảnh" in t
    assert "kiến thức" not in t.lower() or "RAG kiến thức" not in t
    # numbered 1,2 only — kiểu "1." (keycap "1️⃣" vỡ phông Zalo, ảnh 05/08 10:48)
    assert "1. " in t
    assert "2. " in t
    assert "3. " not in t


def test_pending_stages(tmp_path=None):
    key = "test:photo:1"
    # clean
    while phi.has_pending(key):
        phi.pop_pending(key)
    phi.set_pending(key, b"fakejpgdata", stage="choose")
    assert phi.has_pending(key)
    p = phi.get_pending(key)
    assert p and p["stage"] == "choose"
    assert phi.update_pending(key, stage="need_prompt", intent=phi.GENERATE)
    p2 = phi.get_pending(key)
    assert p2["stage"] == "need_prompt"
    assert p2["intent"] == phi.GENERATE
    full = phi.pop_pending_full(key)
    assert full and full["data"] == b"fakejpgdata"
    assert not phi.has_pending(key)


def test_first_image_bytes_mime_tuple():
    from services.image_providers._base import first_image_bytes_mime

    raw = b"\xff\xd8\xff"
    out, mime = first_image_bytes_mime([(raw, "a.jpg", "image/jpeg")])
    assert out == raw
    assert mime == "image/jpeg"
    out2, _ = first_image_bytes_mime([raw])
    assert out2 == raw
    import base64
    b64 = base64.b64encode(raw).decode()
    out3, m3 = first_image_bytes_mime([f"data:image/png;base64,{b64}"])
    assert out3 == raw
    assert m3 == "image/png"


def test_gemini_build_body_accepts_tuple():
    from services.image_providers.gemini_image import GeminiImageAdapter

    ad = GeminiImageAdapter()
    body = ad.build_body(
        "gemini-2.0-flash-exp-image-generation",
        {
            "prompt": "make it anime",
            "images": [(b"\x89PNG\r\n", "x.png", "image/png")],
        },
    )
    parts = body["contents"][0]["parts"]
    assert parts[0]["text"] == "make it anime"
    assert any("inlineData" in p for p in parts)
    assert parts[1]["inlineData"]["mimeType"] == "image/png"


def test_sdwebui_img2img_flag():
    from services.image_providers.sdwebui import SDWebUIAdapter

    ad = SDWebUIAdapter("http://localhost:7860")
    ad.build_body("sd", {"prompt": "x", "images": [(b"abc", "a.jpg", "image/jpeg")]})
    assert ad._use_img2img is True
    assert "img2img" in ad.build_url("sd", None)
    ad.build_body("sd", {"prompt": "x"})
    assert ad._use_img2img is False
    assert "txt2img" in ad.build_url("sd", None)
