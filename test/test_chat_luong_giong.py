"""Bảng chất lượng phát âm đo được, và đường nối nó ra danh mục giọng.

Test ở đây canh hai thứ dễ hỏng lặng lẽ: id giọng trong bảng phải TRÙNG id thật
trong danh mục (gõ lệch một chữ thì nhãn không hiện mà cũng không ai báo lỗi), và
nhãn phải nói đúng cái đã đo.
"""

from __future__ import annotations

import os

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.voice import chat_luong_giong as clg  # noqa: E402
from services.voice import nghitts_voices as nv  # noqa: E402


def test_id_nghitts_trong_bang_deu_co_that():
    that = {f"nghi:{v.id}" for v in nv.VOICES}
    trong_bang = {k for k in clg.DO_DUOC if k.startswith("nghi:")}
    assert trong_bang <= that, f"id lạ: {sorted(trong_bang - that)}"
    assert trong_bang == that, f"chưa đo: {sorted(that - trong_bang)}"


def test_id_vieneu_trong_bang_deu_co_that():
    """Tên giọng VieNeu là tên tiếng Việt có dấu ("vieneu:Thái Sơn") nên gõ
    lệch một dấu là nhãn im lặng biến mất. So với danh sách của chính model —
    chỉ so được khi máy có gói `vieneu`, còn máy chạy test thì bỏ qua."""
    from services.voice import config as vcfg

    trong_bang = {k for k in clg.DO_DUOC if k.startswith(vcfg.VIENEU_PREFIX)}
    assert trong_bang, "chưa đo giọng VieNeu nào"
    assert all(k[len(vcfg.VIENEU_PREFIX):].strip() for k in trong_bang)
    try:
        that = {f"{vcfg.VIENEU_PREFIX}{v['name']}" for v in vcfg.vieneu_voices()}
    except Exception:
        that = set()
    if that:
        assert trong_bang == that, (
            f"lệch: thừa {sorted(trong_bang - that)}, "
            f"chưa đo {sorted(that - trong_bang)}")


def test_so_do_nam_trong_khoang_hop_ly():
    for vid, (diem, am_xat, rung) in clg.DO_DUOC.items():
        assert 0 <= diem <= clg.TONG_AM, vid
        assert am_xat >= 0.0, vid
        # Rụng bao nhiêu âm thì điểm phải hụt ÍT NHẤT bấy nhiêu.
        assert diem <= clg.TONG_AM - len(rung), vid


def test_nhan_noi_dung_cai_da_do():
    # Giọng người dùng báo "xin" nghe thành "chin": rụng âm VÀ âm xát yếu.
    nx = clg.nhan_xet("nghi:ngoc-huyen-moi")
    assert nx is not None
    assert "gi" in nx["rung"] and "k" in nx["rung"]
    assert "âm xát yếu" in nx["nhan"]
    assert nx["dat"] is False

    # Giọng đo đạt: nhãn gọn, không kể lể.
    tot = clg.nhan_xet("nghi:viet-thao")
    assert tot is not None
    assert tot["nhan"] == "đọc rõ" and tot["dat"] is True

    # Đạt phụ âm nhưng âm xát yếu thì vẫn phải cảnh báo, không gộp vào "đọc rõ".
    assert clg.XAT_YEU > 0


def test_giong_chua_do_khong_bi_gan_nhan():
    assert clg.nhan_xet("kokoro:af") is None
    assert clg.nhan_xet("") is None
    assert clg.nhan_xet("giong-la-hoac-moi-them") is None


def test_danh_muc_mang_theo_ket_qua_do():
    from services.voice import config as vcfg

    danh_muc = {v["id"]: v for v in vcfg.voice_catalog()}
    assert danh_muc, "danh mục rỗng — không kiểm được đường nối"
    co_nhan = [v for v in danh_muc.values() if "phat_am" in v]
    assert co_nhan, "không giọng nào mang kết quả đo ra danh mục"
    for v in co_nhan:
        assert v["phat_am"]["tong"] == clg.TONG_AM
        assert isinstance(v["phat_am"]["nhan"], str) and v["phat_am"]["nhan"]
    # Giọng tiếng Anh chưa đo bằng thước này thì không được gắn nhãn bừa.
    for vid, v in danh_muc.items():
        if vid.startswith("kokoro:"):
            assert "phat_am" not in v
