"""Proxy noVNC — chiều lên KHÔNG được đóng phiên khi trình duyệt chưa gửi gì.

Ca thật 10/09/2026: chủ máy mở noVNC thì treo ở "Connecting…", noVNC nối lại 17
lần trong 20 phút. Hạ tầng VNC hoàn toàn khoẻ — `Xvfb :99`, `x11vnc` cổng 5900,
`websockify` 6080 đều sống, nối thẳng vào 6080 trả ngay `b'RFB 003.008\\n'`.

Lỗi nằm ở lớp proxy: chiều lên viết `await ws.receive_bytes()` và chỉ bắt
`(WebSocketDisconnect, RuntimeError)`. RFB là giao thức SERVER NÓI TRƯỚC nên
ngay sau bắt tay trình duyệt chưa gửi byte nào, còn Starlette vẫn có thể giao
khung `text` hoặc sự kiện `websocket.disconnect` — `receive_bytes()` gặp hai
thứ đó thì ném `KeyError`, KHÔNG nằm trong bộ bắt. Ngoại lệ thoát ra,
`asyncio.wait(FIRST_COMPLETED)` coi như xong, proxy huỷ chiều kia rồi đóng.

Bằng chứng là THỨ TỰ trong log: `connection open` → `connection closed` → rồi
websockify mới ghi nhận kết nối. Tức proxy đóng phía trình duyệt TRƯỚC khi kịp
bơm banner RFB xuống.

Bộ test này khoá đúng hành vi đó, không khoá cách viết.
"""

from __future__ import annotations

import asyncio
import unittest


class ChieuLenKhongDongSomTest(unittest.IsolatedAsyncioTestCase):
    """Mô phỏng đúng cặp `_len`/`_xuong` của `api/novnc_proxy.py`."""

    @staticmethod
    async def _chay(nhan_ham) -> list[bytes]:
        """Chạy hai chiều như proxy, trả các gói đã bơm xuống trình duyệt.

        `nhan_ham` đóng vai `ws.receive()` — thứ quyết định chiều lên sống hay
        chết. `_xuong` luôn có dữ liệu để bơm, nên gói xuống rỗng nghĩa là
        chiều lên đã kéo sập cả phiên.
        """
        xuong: list[bytes] = []

        async def _len():
            try:
                while True:
                    tin = await nhan_ham()
                    if tin.get("type") == "websocket.disconnect":
                        return
                    goi = tin.get("bytes")
                    if goi is None:
                        chu = tin.get("text")
                        if chu is None:
                            continue
                        goi = chu.encode()
            except Exception:
                pass

        async def _xuong():
            # websockify gửi banner ngay; giữ phiên một nhịp rồi thôi.
            await asyncio.sleep(0.02)
            xuong.append(b"RFB 003.008\n")
            await asyncio.sleep(0.05)

        xong, con_lai = await asyncio.wait(
            {asyncio.create_task(_len()), asyncio.create_task(_xuong())},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in con_lai:
            t.cancel()
        return xuong

    async def test_TRINH_DUYET_IM_thi_van_bom_duoc_RFB(self):
        """Ca thật: RFB server nói trước, trình duyệt chưa gửi gì cả."""
        async def nhan():
            await asyncio.sleep(3600)      # im suốt, đúng như noVNC lúc đầu
            return {}

        self.assertEqual(await self._chay(nhan), [b"RFB 003.008\n"],
                         "trình duyệt im mà phiên đã chết = lỗi cũ quay lại")

    async def test_KHUNG_TEXT_khong_lam_chet_phien(self):
        """`receive_bytes()` gặp khung text thì ném KeyError — bản cũ chết ở đây."""
        async def nhan():
            await asyncio.sleep(0.01)
            return {"type": "websocket.receive", "text": "xin chào"}

        self.assertEqual(await self._chay(nhan), [b"RFB 003.008\n"])

    async def test_KHUNG_LA_khong_lam_chet_phien(self):
        """Khung không có `bytes` lẫn `text` thì bỏ qua, không được ném ra."""
        async def nhan():
            await asyncio.sleep(0.01)
            return {"type": "websocket.receive"}

        self.assertEqual(await self._chay(nhan), [b"RFB 003.008\n"])

    async def test_NGOAI_LE_LA_khong_lam_treo(self):
        """Bắt Exception RỘNG: chiều này đứt kiểu gì cũng chỉ một cách xử lý."""
        async def nhan():
            await asyncio.sleep(0.01)
            raise KeyError("bytes")        # đúng lỗi `receive_bytes()` ném ra

        # Chiều lên chết thì phiên đóng — chấp nhận được; điều PHẢI có là
        # không treo và không ném ngoại lệ ra ngoài.
        await self._chay(nhan)

    async def test_TRINH_DUYET_NGAT_thi_ket_thuc_gon(self):
        async def nhan():
            await asyncio.sleep(0.01)
            return {"type": "websocket.disconnect", "code": 1000}

        await self._chay(nhan)


class HopDongProxyTest(unittest.TestCase):
    def test_router_du_ba_duong(self):
        """Thiếu một đường là màn hình đen: tệp tĩnh, kênh RFB, và vé."""
        from api.novnc_proxy import create_router

        duong = {getattr(r, "path", "") for r in create_router().routes}
        self.assertIn("/novnc/websockify", duong)
        self.assertIn("/api/novnc/ve", duong)
        self.assertIn("/novnc/{path:path}", duong)

    def test_KHONG_con_receive_bytes_trong_ma_song(self):
        """Chốt chặn lớp lỗi: `receive_bytes()` ép kiểu khung, gặp text hay
        disconnect là ném `KeyError` rồi kéo sập cả phiên.

        Chỉ soi MÃ SỐNG — tên hàm vẫn được nhắc trong lời giải thích ở
        docstring, và đó là chuyện nên giữ.
        """
        import inspect

        from api import novnc_proxy

        nguon = inspect.getsource(novnc_proxy)
        ma_song = "\n".join(
            d for d in nguon.splitlines()
            if not d.lstrip().startswith("#")
        )
        # Bỏ mọi docstring để chỉ còn câu lệnh thật.
        for dau in ('"""', "'''"):
            phan = ma_song.split(dau)
            ma_song = "".join(phan[::2])
        self.assertNotIn("receive_bytes", ma_song,
                         "mã sống không được dùng receive_bytes — xem docstring")


class ChanTrinhDuyetNhoMatKhauTest(unittest.TestCase):
    """Chủ máy không muốn mật khẩu VNC nằm trong kho mật khẩu trình duyệt.

    `vnc.html` của noVNC đặt ô mật khẩu trong `<form>` có nút submit mà KHÔNG
    khai `autocomplete` — đúng hình dạng Chrome nhận là form đăng nhập, nên nó
    hỏi lưu rồi tự điền theo tên miền ở lần sau (đo 11/09/2026).

    Khoá HÀNH VI: HTML phục vụ ra phải mang `autocomplete`. Không khoá cách
    viết — thay `replace` bằng regex hay parser đều được, miễn kết quả đúng.
    """

    # Nguyên văn từ gói Debian novnc 1.6.0, đã đối chiếu bằng `cat -A`.
    THAT = (
        b'<div id="noVNC_credentials_dlg" class="noVNC_panel"><form>\n'
        b'        <div id="noVNC_username_block">\n'
        b'            <input id="noVNC_username_input">\n'
        b'        </div>\n'
        b'        <div id="noVNC_password_block">\n'
        b'            <input id="noVNC_password_input" type="password">\n'
        b'        </div>\n'
        b'    </form></div>\n'
    )

    def test_O_MAT_KHAU_duoc_khai_autocomplete(self):
        from api.novnc_proxy import _chan_trinh_duyet_nho_mat_khau

        ra = _chan_trinh_duyet_nho_mat_khau(self.THAT)
        self.assertIn(b'id="noVNC_password_input"', ra)
        self.assertIn(b'autocomplete="new-password"', ra,
                      "ô mật khẩu phải khai autocomplete để Chrome thôi tự điền")

    def test_O_TEN_cung_phai_khai_vi_Chrome_ghep_cap(self):
        """Chrome ghép tên+mật khẩu mới coi là form đăng nhập — khai thiếu một
        nửa thì nó vẫn lưu."""
        from api.novnc_proxy import _chan_trinh_duyet_nho_mat_khau

        ra = _chan_trinh_duyet_nho_mat_khau(self.THAT)
        self.assertIn(b'id="noVNC_username_input" autocomplete="off"', ra)

    def test_KHONG_con_o_nhap_tran_trui(self):
        """Chốt chặn: sau khi sửa, không còn ô nào thiếu `autocomplete`."""
        from api.novnc_proxy import _chan_trinh_duyet_nho_mat_khau

        ra = _chan_trinh_duyet_nho_mat_khau(self.THAT)
        self.assertNotIn(b'<input id="noVNC_password_input" type="password">', ra)
        self.assertNotIn(b'<input id="noVNC_username_input">', ra)

    def test_HTML_LA_di_qua_nguyen_xi(self):
        """noVNC đổi markup thì bản vá mất tác dụng — nhưng KHÔNG được làm hỏng
        trang. Tệp không chứa ô nào thì trả lại y nguyên."""
        from api.novnc_proxy import _chan_trinh_duyet_nho_mat_khau

        goc = b"<html><body>khong co o nhap nao</body></html>"
        self.assertEqual(goc, _chan_trinh_duyet_nho_mat_khau(goc))


if __name__ == "__main__":
    unittest.main()
