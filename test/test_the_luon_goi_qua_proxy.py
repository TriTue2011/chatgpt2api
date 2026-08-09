"""Thẻ trong trình duyệt phải LUÔN gọi solver qua proxy cùng gốc `/api/captcha`.

SỰ CỐ 09/08/2026. Chủ máy: "tôi nhập rồi kích đang không hoạt động", cả trên PC
lẫn điện thoại. Ảnh chụp cho thấy đã điền đủ email, mật khẩu, hạt giống TOTP —
mà danh sách "Tai khoan da luu" vẫn hiện **(0)** dù kho có đúng một tài khoản
`loai='openai'`.

Đo trên máy chủ: **0 request `POST /v1/openai-native/onboard` trong 60 phút**.
Không phải máy chủ từ chối — request chưa bao giờ rời khỏi trình duyệt.

NGUYÊN NHÂN

`captcha_solver_url` trong config là địa chỉ NỘI BỘ để máy chủ gọi máy chủ:
`http://127.0.0.1:8010`. Thẻ OpenAI gốc đọc trường đó rồi dùng làm gốc cho
`fetch()` — tức bảo TRÌNH DUYỆT gọi `127.0.0.1:8010`, là chính máy của người
dùng. Mọi request hỏng im lặng: danh sách tài khoản rỗng, nút bấm không gửi gì.

Bốn thẻ còn lại (Google, ChatGPT-via-Google, Claude, Gemini) đều ép cứng
`/api/captcha` từ trước. Chính chỗ lệch đó làm lỗi trông như "riêng thẻ này
hỏng" thay vì một lỗi cấu hình dễ nhận.

BÀI HỌC: cùng một trường config phục vụ hai người gọi ở hai vị trí mạng khác
nhau (máy chủ → solver, và trình duyệt → solver) thì không thể dùng chung một
giá trị. Trình duyệt phải đi proxy cùng gốc.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
THE = GOC / "web/src/app/settings/components"

# Mọi thẻ gọi thẳng tới solver từ trình duyệt.
CAC_THE = (
    "openai-native-card.tsx",
    "google-providers-card.tsx",
    "chatgpt-onboard-card.tsx",
    "claude-card.tsx",
    "gemini-web-card.tsx",
    "gemini-web-api-card.tsx",
)


class KhongDungDiaChiNoiBoTests(unittest.TestCase):
    def test_khong_the_nao_lay_url_solver_tu_config(self):
        """Đây là ca đã hỏng: `url: flow.captcha_solver_url || "/api/captcha"`.

        Có `|| "/api/captcha"` trông như đã phòng thủ, nhưng nó chỉ đỡ khi config
        RỖNG — mà thực tế config luôn có sẵn địa chỉ nội bộ, nên nhánh dự phòng
        không bao giờ chạy.
        """
        for ten in CAC_THE:
            nguon = (THE / ten).read_text(encoding="utf-8")
            # Chặn `(?<![_a-zA-Z])` để không bắt nhầm chính KHOÁ
            # `captcha_solver_url:` — trường đó là địa chỉ máy-chủ-gọi-máy-chủ,
            # thẻ Flow được phép đọc/ghi nó như một giá trị cấu hình.
            for m in re.finditer(r"(?<![_a-zA-Z])url:\s*([^,\n]+)", nguon):
                gia_tri = m.group(1)
                if "captcha_solver_url" in gia_tri:
                    self.fail(f"{ten}: gán url solver từ config → trình duyệt gọi "
                              f"địa chỉ nội bộ. Dòng: {gia_tri.strip()}")

    def test_moi_the_deu_dat_url_la_proxy(self):
        for ten in CAC_THE:
            nguon = (THE / ten).read_text(encoding="utf-8")
            self.assertIn('url: "/api/captcha"', nguon,
                          f"{ten}: phải ép cứng proxy cùng gốc")


class GhiLaiLyDoTests(unittest.TestCase):
    def test_the_openai_goc_ghi_ro_vi_sao(self):
        """Chỗ vừa sửa phải mang theo lý do — nếu không, lần sau có người thấy
        'lấy từ config linh hoạt hơn' rồi sửa ngược lại.
        """
        nguon = (THE / "openai-native-card.tsx").read_text(encoding="utf-8")
        # Lấy lần gán TRONG `setCs` (sau khi đọc /api/settings), không phải
        # giá trị khởi tạo `useState` ở đầu component.
        i = nguon.index('url: "/api/captcha"', nguon.index("setCs({"))
        truoc = nguon[max(0, i - 900):i]
        self.assertIn("NỘI BỘ", truoc)
        self.assertIn("trình duyệt", truoc)


if __name__ == "__main__":
    unittest.main()
