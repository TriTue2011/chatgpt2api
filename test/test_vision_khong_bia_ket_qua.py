"""Không được BỊA kết quả phân tích ảnh, và không đổi model người dùng đã chọn.

Sự cố thật 08/08/2026 (camera Home Assistant):
  1. HA gửi 2 snapshot vào `ai_task.ai_vision`.
  2. Định tuyến nhánh ép request sang combo "AI vision", bỏ qua model đã khai.
  3. Mọi provider vision đều hỏng: Gemini Free hết quota, ChatGPT Free trả 413
     với hai ảnh camera, Claude chưa có session.
  4. Request rơi xuống `oc/deepseek-v4-flash-free` — một model CHỈ XỬ LÝ CHỮ.
     Nó trả vài dòng văn xuôi.
  5. `normalize_content` không bóc được JSON nên dựng object toàn giá trị mặc
     định. `humans_detected` khai kiểu integer → mặc định **0**.
  6. HA đọc `{"humans_detected": 0}` thành "KHÔNG CÓ NGƯỜI".

Không có tấm ảnh nào từng được nhìn, nhưng hệ báo động nói an toàn. Một hệ báo
động im lặng báo an toàn còn tệ hơn một hệ báo lỗi ầm ĩ.
"""
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.protocol import response_format as rf  # noqa: E402
from services.protocol.response_format import KhongPhanTichDuocAnh  # noqa: E402

VISION_META = {"type": "json_object", "schema": rf._VISION_SCHEMA, "name": "vision_ha"}

# Đúng kiểu câu mà một model chỉ-chữ trả về khi được đưa yêu cầu phân tích ảnh.
VAN_XUOI = "Tôi không thể xem được hình ảnh, nhưng tôi có thể giúp bạn việc khác."


class KhongBiaJsonTests(unittest.TestCase):
    def test_van_xuoi_thi_nem_loi_chu_khong_tra_0_nguoi(self):
        with self.assertRaises(KhongPhanTichDuocAnh):
            rf.normalize_content(VAN_XUOI, VISION_META, cho_phep_mac_dinh=False)

    def test_khong_bao_gio_sinh_ra_humans_detected_0_gia(self):
        """Chốt thẳng vào hình dạng JSON đã lừa Home Assistant."""
        try:
            out = rf.normalize_content(VAN_XUOI, VISION_META, cho_phep_mac_dinh=False)
        except KhongPhanTichDuocAnh:
            return
        self.fail(f"vẫn bịa ra JSON thay vì báo lỗi: {out}")

    def test_json_that_van_di_qua_binh_thuong(self):
        that = ('{"humans_detected": 2, "humans_detected_summary": "hai người",'
                ' "humans_detected_description": "đi từ trái sang",'
                ' "animals_detected": 0, "animals_detected_summary": "",'
                ' "animals_detected_description": ""}')
        out = rf.normalize_content(that, VISION_META, cho_phep_mac_dinh=False)
        import json
        self.assertEqual(json.loads(out)["humans_detected"], 2)

    def test_json_lan_trong_van_ban_van_boc_duoc(self):
        lan = "Đây là kết quả:\n```json\n" + (
            '{"humans_detected": 1, "humans_detected_summary": "một người",'
            ' "humans_detected_description": "đứng ở cổng",'
            ' "animals_detected": 0, "animals_detected_summary": "",'
            ' "animals_detected_description": ""}') + "\n```"
        import json
        out = rf.normalize_content(lan, VISION_META, cho_phep_mac_dinh=False)
        self.assertEqual(json.loads(out)["humans_detected"], 1)

    def test_duong_khong_phai_vision_van_dung_mac_dinh_nhu_cu(self):
        """Chỉ đường CAMERA mới fail-closed.

        Với client cấu trúc thường, "0" không mang nghĩa an toàn/nguy hiểm nào,
        nên giữ hành vi cũ để không phá thứ đang chạy.
        """
        meta = {"type": "json_object",
                "schema": {"type": "object", "properties": {"so_luong": {"type": "integer"}}}}
        out = rf.normalize_content("khong phai json", meta)
        self.assertIn("so_luong", out)


class DuongCameraFailClosedTests(unittest.TestCase):
    def _ket_qua(self, noi_dung: str) -> dict:
        return {"choices": [{"message": {"role": "assistant", "content": noi_dung}}]}

    def _body_camera(self, *, co_anh: bool) -> dict:
        phan = [{"type": "text",
                 "text": "Phân tích chuỗi hình ảnh, trả humans_detected và animals_detected."}]
        if co_anh:
            phan.append({"type": "image_url",
                         "image_url": {"url": "data:image/jpeg;base64,/9j/4AAQSkZJRg=="}})
        return {"messages": [{"role": "user", "content": phan}]}

    def test_co_anh_ma_model_tra_van_xuoi_thi_nem_loi(self):
        with self.assertRaises(KhongPhanTichDuocAnh):
            rf.enforce_vision_json_if_needed(self._ket_qua(VAN_XUOI),
                                             self._body_camera(co_anh=True))

    def test_khong_co_anh_thi_khong_bien_chat_thanh_502(self):
        """Câu chat chỉ NHẮC TỚI cụm từ camera thì không được ném lỗi.

        `_looks_like_vision_analysis` nhận dạng bằng cụm từ, mà hội thoại bình
        thường cũng có thể chứa chúng.
        """
        out = rf.enforce_vision_json_if_needed(self._ket_qua(VAN_XUOI),
                                               self._body_camera(co_anh=False))
        self.assertIsInstance(out, dict)

    def test_enforce_vision_fail_closed_khi_co_anh(self):
        src = (GOC / "services/protocol/response_format.py").read_text(encoding="utf-8")
        i = src.index("def enforce_vision_json_if_needed")
        than = src[i:i + 2000]
        self.assertIn("body_has_images(body)", than,
                      "phải fail-closed dựa trên việc CÓ ẢNH, không chỉ theo cụm từ")

    def test_noi_goi_khong_nuot_loi_phan_tich(self):
        """Nuốt lỗi rồi trả kết quả gốc là quay lại đúng vòng cũ.

        HA sẽ nhận văn xuôi, `from_json` hỏng, blueprint lại hiểu thành 0 người.
        """
        src = (GOC / "services/protocol/openai_v1_chat_complete.py").read_text(encoding="utf-8")
        self.assertIn("except KhongPhanTichDuocAnh", src)
        i = src.index("except KhongPhanTichDuocAnh")
        self.assertIn("raise HTTPException", src[i:i + 600],
                      "phải trả lỗi tường minh để automation THẤY là thất bại")


class LuongStreamTests(unittest.TestCase):
    """Nhánh STREAM — đúng đường Home Assistant đi, và là chỗ bản vá đầu BỎ SÓT.

    aa4832b chỉ vá nhánh dict. Nhánh stream vẫn gọi `normalize_content` với mặc
    định cho phép dựng JSON, nên gateway vẫn phát `{"humans_detected":0,...}` từ
    một câu văn xuôi.
    """

    def _stream(self, noi_dung: str):
        yield {"id": "x", "model": "m", "created": 1,
               "choices": [{"index": 0, "delta": {"role": "assistant", "content": noi_dung}}]}
        yield {"id": "x", "model": "m", "created": 1,
               "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}

    def _body_camera(self, *, co_anh: bool) -> dict:
        phan = [{"type": "text",
                 "text": "Phân tích chuỗi hình ảnh, trả humans_detected và animals_detected."}]
        if co_anh:
            phan.append({"type": "image_url",
                         "image_url": {"url": "data:image/jpeg;base64,/9j/4AAQSkZJRg=="}})
        return {"messages": [{"role": "user", "content": phan}], "stream": True}

    def test_stream_co_anh_van_xuoi_thi_nem_loi(self):
        with self.assertRaises(KhongPhanTichDuocAnh):
            rf.enforce_vision_json_if_needed(self._stream(VAN_XUOI),
                                             self._body_camera(co_anh=True))

    def test_stream_khong_bao_gio_phat_humans_detected_0(self):
        try:
            out = rf.enforce_vision_json_if_needed(self._stream(VAN_XUOI),
                                                   self._body_camera(co_anh=True))
            noi_dung = "".join(
                str((c.get("choices") or [{}])[0].get("delta", {}).get("content") or "")
                for c in out
            )
        except KhongPhanTichDuocAnh:
            return
        self.fail(f"stream vẫn phát JSON bịa: {noi_dung}")

    def test_loi_no_TRUOC_khi_stream_bat_dau(self):
        """Phải ném NGAY lúc gọi, không phải lúc lặp.

        Nếu lỗi chỉ nổ khi tầng HTTP kéo phần tử đầu tiên thì header đã gửi và
        SSE đã mở — không còn cách nào trả 502, người gọi nhận stream đứt.
        """
        with self.assertRaises(KhongPhanTichDuocAnh):
            # KHÔNG lặp kết quả — chỉ gọi hàm.
            rf.enforce_vision_json_if_needed(self._stream(VAN_XUOI),
                                             self._body_camera(co_anh=True))

    def test_stream_json_that_van_di_qua(self):
        that = ('{"humans_detected": 3, "humans_detected_summary": "ba người",'
                ' "humans_detected_description": "đứng ở sân",'
                ' "animals_detected": 0, "animals_detected_summary": "",'
                ' "animals_detected_description": ""}')
        out = list(rf.enforce_vision_json_if_needed(self._stream(that),
                                                    self._body_camera(co_anh=True)))
        noi_dung = "".join(
            str((c.get("choices") or [{}])[0].get("delta", {}).get("content") or "")
            for c in out
        )
        import json
        self.assertEqual(json.loads(noi_dung)["humans_detected"], 3)

    def test_stream_khong_co_anh_thi_khong_nem(self):
        out = rf.enforce_vision_json_if_needed(self._stream(VAN_XUOI),
                                               self._body_camera(co_anh=False))
        self.assertTrue(list(out))


class GiuModelNguoiDungChonTests(unittest.TestCase):
    def test_model_cu_the_khong_bi_doi(self):
        from services.protocol.openai_v1_chat_complete import _model_la_auto
        for m in ("cgf/gpt-5-5-instant", "gma/3.1-pro", "claude/sonnet-5",
                  "cx/gpt-5.6-terra"):
            self.assertFalse(_model_la_auto(m), f"{m} là lựa chọn rõ ràng, không được đổi")

    def test_auto_van_duoc_dinh_tuyen(self):
        from services.protocol.openai_v1_chat_complete import _model_la_auto
        for m in ("", None, "auto", "cgf/auto", "gma/auto", "claude/auto"):
            self.assertTrue(_model_la_auto(m), f"{m!r} phải được coi là auto")

    def test_branch_routing_kiem_truoc_khi_doi_model(self):
        src = (GOC / "services/protocol/openai_v1_chat_complete.py").read_text(encoding="utf-8")
        i = src.index("def _apply_branch_routing")
        than = src[i:i + 1200]
        self.assertIn("_model_la_auto", than,
                      "định tuyến nhánh phải bỏ qua khi người gọi đã chỉ đích danh model")


if __name__ == "__main__":
    unittest.main()
