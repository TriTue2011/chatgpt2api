"""split_for_ai — chia tài liệu dài thành nhiều lượt gọi AI, KHÔNG mất chữ.

Lý do có bộ test này: bản cũ của `analyze_source` cắt `raw_text[:30000]` rồi
gọi AI một lượt. Một quyết định 60 trang trích ra ~100k ký tự nên mất ~70% tài
liệu, im lặng, và mất đúng phần cuối (các Phụ lục chứa toàn bộ giải pháp kỹ
thuật). Bất biến quan trọng nhất ở đây: **ghép các đoạn lại phải ra đủ chữ**.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# vn-mcp-hub là package riêng (`src.*`), không nằm trên sys.path của gateway.
_HUB = Path(__file__).resolve().parents[1] / "vn-mcp-hub"
if str(_HUB) not in sys.path:
    sys.path.insert(0, str(_HUB))

from src.rag.ingest import AI_BATCH, split_for_ai  # noqa: E402

pytestmark = pytest.mark.pure


def _doc(paragraphs: int, para_len: int = 400) -> str:
    """Văn bản có ranh giới đoạn rõ ràng, mỗi đoạn đánh số để truy được."""
    return "\n\n".join(f"[{i}] " + ("x" * para_len) for i in range(paragraphs))


class TestKhongMatChu:
    def test_ngan_thi_mot_doan(self):
        t = _doc(3)
        assert split_for_ai(t) == [t]

    def test_rong_thi_khong_co_doan_nao(self):
        assert split_for_ai("") == []
        assert split_for_ai("   \n\n  \n") == []

    def test_ghep_lai_du_chu_khi_cat_o_ranh_gioi_doan(self):
        """Cắt ở ranh giới đoạn ⇒ ghép lại phải BẰNG CHÍNH bản gốc."""
        t = _doc(200)  # ~80k ký tự
        segs = split_for_ai(t)
        assert len(segs) > 1
        assert "".join(segs) == t

    def test_moi_so_doan_deu_con_mat(self):
        t = _doc(200)
        joined = "".join(split_for_ai(t))
        for i in range(200):
            assert f"[{i}] " in joined, f"mất đoạn {i}"

    def test_khong_doan_nao_vuot_tran_dang_ke(self):
        t = _doc(200)
        for s in split_for_ai(t):
            assert len(s) <= AI_BATCH, f"đoạn dài {len(s)} > trần {AI_BATCH}"

    def test_khong_co_ranh_gioi_van_khong_mat_chu(self):
        """Bảng bị trích thành khối chữ liền — không có \\n nào để cắt.

        Khi đó buộc phải cắt cứng và chồng lấn, nên ghép lại sẽ DÀI HƠN bản gốc
        (chữ bị lặp), nhưng tuyệt đối không được NGẮN hơn.
        """
        t = "y" * 50_000
        segs = split_for_ai(t)
        assert len(segs) > 1
        assert len("".join(segs)) >= len(t)

    def test_chong_lap_giu_tron_cau_bi_cat_ngang(self):
        head = "a" * (AI_BATCH - 10)
        needle = "DIEU_KHOAN_QUAN_TRONG_KHONG_DUOC_MAT"
        t = head + needle + "b" * AI_BATCH
        segs = split_for_ai(t)
        # Câu nằm vắt qua ranh giới phải xuất hiện TRỌN ở ít nhất một đoạn,
        # nếu không lượt AI nào cũng chỉ thấy một nửa và bỏ qua nó.
        assert any(needle in s for s in segs), "câu vắt ranh giới bị xé đôi ở mọi đoạn"

    def test_tien_do_luon_duong(self):
        """Overlap gần bằng size phải bị kẹp, không thì 1 vòng tiến 1 ký tự.

        Không kẹp thì 5k ký tự ra ~4000 đoạn ⇒ 4000 lượt gọi AI ⇒ treo hub.
        """
        segs = split_for_ai("z" * 5_000, size=1_000, overlap=999)
        assert 1 < len(segs) < 20, f"chia thành {len(segs)} đoạn — overlap chưa bị kẹp"


class TestVanBanPhapLuatThat:
    """Mẫu cắt từ chính tài liệu PCCC (QĐ 1074/QĐ-BXD) đã gây ra lỗi."""

    SAMPLE = (
        "4.4 Các yêu cầu an toàn cháy tối thiểu phải được bảo đảm đồng thời khi "
        "áp dụng các giải pháp kỹ thuật nâng cao an toàn PCCC là:\n\n"
        "a) Phải có các giải pháp kết cấu, bố trí mặt bằng - không gian và kỹ "
        "thuật công trình để khi xảy ra cháy thì các điều kiện sau đây đồng "
        "thời được bảo đảm:\n\n"
        "A.1.1 Bảo đảm đồng thời các điều kiện sau: (1) Tăng giới hạn chịu lửa "
        "của các bộ phận chịu lực theo phương đứng đến giới hạn chịu lửa yêu "
        "cầu (xác định theo bảng 4 của [1]);\n\n"
        "(4) Kết cấu chịu lực của mái bảo đảm giới hạn chịu lửa tối thiểu R 15. "
        "Có thể sử dụng các kết cấu thép không bọc bảo vệ nếu giới hạn chịu lửa "
        "của chúng từ R 8 trở lên, hoặc hệ số tiết diện Am/V nhỏ hơn hoặc bằng "
        "250 m-1;\n\n"
        "F.3.1.1 Trang bị tăng cường 10 % số lượng bình chữa cháy xách tay tại "
        "từng khu vực theo quy định thì thời gian chữa cháy của các hệ thống "
        "chữa cháy bằng nước được tính toán như sau: tối thiểu là 30 phút.\n\n"
    )

    def test_giu_nguyen_moi_so_hieu_va_nguong_so(self):
        # Nhân bản cho đủ dài để buộc phải chia lượt.
        doc = self.SAMPLE * 40
        segs = split_for_ai(doc)
        assert len(segs) > 1
        joined = "".join(segs)
        for token in ("R 15", "R 8", "Am/V", "250 m-1", "EI", "A.1.1",
                      "F.3.1.1", "10 %", "30 phút", "bảng 4"):
            if token in doc:
                assert token in joined, f"mất '{token}' sau khi chia lượt"

    def test_so_lan_xuat_hien_khong_giam(self):
        doc = self.SAMPLE * 40
        joined = "".join(split_for_ai(doc))
        # Cắt ở ranh giới đoạn nên không lặp; số lần phải khớp CHÍNH XÁC.
        assert joined.count("F.3.1.1") == doc.count("F.3.1.1")
        assert joined.count("R 15") == doc.count("R 15")

    def test_tai_lieu_60_trang_khong_con_bi_cat_con_30k(self):
        """Chính ca lỗi: ~100k ký tự trước đây chỉ còn 30k đi vào AI."""
        doc = self.SAMPLE * 120  # ~106k ký tự, cỡ tài liệu 60 trang thật
        assert len(doc) > 100_000, "mẫu phải đủ lớn để tái hiện ca lỗi"
        segs = split_for_ai(doc)
        processed = sum(len(s) for s in segs)
        assert processed >= len(doc), "vẫn còn mất chữ"
        # Bản cũ chỉ đưa 30k vào AI — giờ phải nhiều hơn hẳn.
        assert processed > 30_000 * 2
