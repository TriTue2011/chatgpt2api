"""Workflow tự kích hoạt + trần đồng thời + kiểm chuỗi băm nhật ký duyệt.

Ba thứ mượn thiết kế của block/buzz (đọc 19/08/2026):

* buzz cho workflow bắn theo sự kiện (`message_posted`, `webhook`) thay vì nằm
  chờ ai đó nhớ ra mà gọi → `workflows.khop_tin_nhan` + `cho_phep_webhook`.
* buzz hết chỗ chạy thì trả `CapacityExceeded` NGAY, không xếp hàng → trần
  `agent_workflows.max_concurrent`.
* buzz có `verify_chain()` đi kèm chuỗi băm ngay từ đầu → `verify_chain()` cho
  `approval_audit.jsonl` (chuỗi băm đã có từ trước, chỉ thiếu người kiểm).

Cái cần ghim là HÀNH VI, không phải câu chữ: từ khoá quá ngắn không được nuốt
mọi câu, hết chỗ phải từ chối chứ không chờ, và chỗ chạy phải được trả lại.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import approval_gate  # noqa: E402
from services.agent import workflows as wf  # noqa: E402
from services.config import config  # noqa: E402
from test._fakes import install_data_dir  # noqa: E402

_THAN = (
    "\n## Bước 1: Thu thập\n"
    "Input: {{input}}\n"
    "\n## Bước 2: Viết\n"
    "Từ {{prev}} viết tóm tắt.\n"
)


def _viet(root: Path, slug: str, frontmatter: str) -> None:
    (root / f"{slug}.md").write_text(
        "---\n" + frontmatter.strip("\n") + "\n---\n" + _THAN, encoding="utf-8",
    )


class _NenWorkflow(unittest.TestCase):
    """Thư mục workflow riêng cho mỗi test, không đụng data thật."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        wf._reset_for_tests(self.root)
        wf._seeded = True  # đừng chép workflow mặc định vào bài đo
        self._cfg = mock.patch.dict(
            config.data,
            {"agent_workflows": {"enabled": True, "max_steps": 5}},
        )
        self._cfg.start()

    def tearDown(self) -> None:
        self._cfg.stop()
        wf._reset_for_tests()
        self._tmp.cleanup()


@pytest.mark.pure
class DocTriggerTests(_NenWorkflow):
    def test_doc_trigger_va_tu_khoa(self) -> None:
        _viet(self.root, "su-co", "name: Sự cố\ntrigger: tin_nhan\nkhi: sự cố|mất điện")
        w = wf.get_workflow("su-co")
        assert w is not None
        self.assertEqual(w.trigger, "tin_nhan")
        # Từ khoá được fold sẵn lúc đọc file — khớp lúc chat khỏi fold lại.
        self.assertEqual(w.keywords, ["su co", "mat dien"])

    def test_khai_trigger_ma_thieu_khi_thi_coi_nhu_chua_khai(self) -> None:
        """Không có `khi:` thì điều kiện khớp là RỖNG — khớp mọi câu, tức một
        file lỡ tay sẽ nuốt sạch luồng chat. Phải tắt hẳn trigger."""
        _viet(self.root, "trong", "name: Trống\ntrigger: tin_nhan")
        w = wf.get_workflow("trong")
        assert w is not None
        self.assertEqual(w.trigger, "")
        self.assertIsNone(wf.khop_tin_nhan("một câu bất kỳ"))

    def test_tu_khoa_qua_ngan_bi_bo(self) -> None:
        """"an" nằm trong "bàn ăn", "làm", "sáng"… — 2 ký tự là khớp mọi câu."""
        _viet(self.root, "ngan", "name: Ngắn\ntrigger: tin_nhan\nkhi: an|đi|báo cáo")
        w = wf.get_workflow("ngan")
        assert w is not None
        self.assertEqual(w.keywords, ["bao cao"])

    def test_trigger_la_thi_khong_nhan(self) -> None:
        _viet(self.root, "la", "name: Lạ\ntrigger: cron\nkhi: mỗi sáng")
        w = wf.get_workflow("la")
        assert w is not None
        self.assertEqual(w.trigger, "")


@pytest.mark.pure
class KhopCauTests(_NenWorkflow):
    def test_khop_khong_can_dau(self) -> None:
        _viet(self.root, "sang", "name: Sáng\ntrigger: tin_nhan\nkhi: báo cáo sáng")
        w = wf.khop_tin_nhan("cho anh xin bao cao sang nhé")
        assert w is not None
        self.assertEqual(w.slug, "sang")

    def test_cau_khong_lien_quan_thi_khong_khop(self) -> None:
        _viet(self.root, "sang", "name: Sáng\ntrigger: tin_nhan\nkhi: báo cáo sáng")
        self.assertIsNone(wf.khop_tin_nhan("hôm nay trời thế nào em"))

    def test_workflow_khong_khai_trigger_thi_khong_tu_bắn(self) -> None:
        """Workflow cũ (chỉ chạy khi model gọi run_workflow) phải giữ nguyên nết."""
        _viet(self.root, "cu", "name: Cũ\ndescription: workflow cũ")
        self.assertIsNone(wf.khop_tin_nhan("chạy workflow cũ đi"))

    def test_hai_workflow_cung_khop_thi_ket_qua_on_dinh(self) -> None:
        """Theo thứ tự tên file, không theo thứ tự hệ điều hành trả thư mục."""
        _viet(self.root, "b-sau", "name: Sau\ntrigger: tin_nhan\nkhi: sự cố")
        _viet(self.root, "a-truoc", "name: Trước\ntrigger: tin_nhan\nkhi: sự cố")
        for _ in range(3):
            w = wf.khop_tin_nhan("báo sự cố")
            assert w is not None
            self.assertEqual(w.slug, "a-truoc")

    def test_webhook_phai_tu_khai_moi_goi_duoc(self) -> None:
        _viet(self.root, "mo", "name: Mở\ntrigger: webhook")
        _viet(self.root, "dong", "name: Đóng\ndescription: không khai gì")
        self.assertIsNotNone(wf.cho_phep_webhook("mo"))
        self.assertIsNone(wf.cho_phep_webhook("dong"))
        self.assertIsNone(wf.cho_phep_webhook("khong-co-file"))
        # Khai webhook thì KHÔNG tự bắn trong chat.
        self.assertIsNone(wf.khop_tin_nhan("mở cái gì đó"))


@pytest.mark.adapter
class TranDongThoiTests(_NenWorkflow):
    def test_het_cho_thi_tu_choi_ngay_va_tra_lai_cho(self) -> None:
        _viet(self.root, "cham", "name: Chậm\ndescription: pipeline chậm")
        self._cfg.stop()
        self._cfg = mock.patch.dict(
            config.data,
            {"agent_workflows": {"enabled": True, "max_steps": 5,
                                 "max_concurrent": 1}},
        )
        self._cfg.start()

        dang_trong_buoc = threading.Event()
        cho_nha = threading.Event()

        def _buoc_cham(**kwargs: object) -> str:
            dang_trong_buoc.set()
            cho_nha.wait(timeout=10)
            return "xong bước"

        with mock.patch.object(wf, "_run_llm_step", side_effect=_buoc_cham):
            ket_qua_a: dict = {}
            luong = threading.Thread(
                target=lambda: ket_qua_a.update(wf.run("cham", "chạy đi")),
                daemon=True,
            )
            luong.start()
            self.assertTrue(dang_trong_buoc.wait(timeout=10), "bước 1 chưa chạy")

            # Lượt thứ hai lúc chỗ đã đầy: phải trả lời NGAY, không chờ.
            kq_b = wf.run("cham", "chạy nữa")
            self.assertTrue(kq_b.get("busy"))
            self.assertFalse(kq_b.get("ok"))
            self.assertIn("chờ", str(kq_b.get("text") or "").lower())

            cho_nha.set()
            luong.join(timeout=10)
            self.assertTrue(ket_qua_a.get("ok"))

        # Chỗ phải được trả lại — rò một chỗ là workflow chết hẳn tới lần khởi
        # động lại sau (đúng lý do phải bọc try/finally quanh thân run()).
        self.assertEqual(wf.dang_chay(), 0)
        with mock.patch.object(wf, "_run_llm_step", return_value="ok"):
            self.assertTrue(wf.run("cham", "lần ba").get("ok"))

    def test_khong_thay_workflow_thi_khong_an_cho(self) -> None:
        """Gõ sai slug là chuyện thường; nó không được chiếm suất chạy."""
        kq = wf.run("khong-ton-tai", "gì đó")
        self.assertFalse(kq.get("ok"))
        self.assertEqual(wf.dang_chay(), 0)


@pytest.mark.pure
class KiemChuoiBamTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.log = Path(self._tmp.name) / "approval_audit.jsonl"
        self._patch = mock.patch.object(approval_gate, "_AUDIT_FILE", self.log)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def _ghi(self, n: int) -> None:
        for i in range(n):
            approval_gate.log_event("pending", f"u{i}", "control_home",
                                    summary=f"bật đèn {i}")

    def test_file_chua_co_thi_coi_nhu_lanh(self) -> None:
        kq = approval_gate.verify_chain()
        self.assertTrue(kq["ok"])
        self.assertEqual(kq["so_dong"], 0)

    def test_chuoi_nguyen_ven(self) -> None:
        self._ghi(4)
        kq = approval_gate.verify_chain()
        self.assertTrue(kq["ok"], kq["ly_do"])
        self.assertEqual(kq["so_dong"], 4)
        self.assertEqual(kq["mat_xich_khong_ro"], 0)

    def test_sua_noi_dung_mot_dong_thi_lo(self) -> None:
        self._ghi(4)
        dong = self.log.read_text(encoding="utf-8").splitlines()
        row = json.loads(dong[2])
        row["capability"] = "send_money"  # sửa lén việc đã duyệt
        dong[2] = json.dumps(row, ensure_ascii=False)
        self.log.write_text("\n".join(dong) + "\n", encoding="utf-8")

        kq = approval_gate.verify_chain()
        self.assertFalse(kq["ok"])
        self.assertEqual(kq["hong_dong"], 3)
        self.assertIn("băm", kq["ly_do"])

    def test_xoa_mot_dong_giua_thi_lo(self) -> None:
        self._ghi(4)
        dong = self.log.read_text(encoding="utf-8").splitlines()
        del dong[1]
        self.log.write_text("\n".join(dong) + "\n", encoding="utf-8")

        kq = approval_gate.verify_chain()
        self.assertFalse(kq["ok"])
        self.assertEqual(kq["hong_dong"], 2)
        self.assertIn("mắt xích", kq["ly_do"])

    def test_cat_cut_dau_file_thi_lo(self) -> None:
        self._ghi(4)
        dong = self.log.read_text(encoding="utf-8").splitlines()
        self.log.write_text("\n".join(dong[2:]) + "\n", encoding="utf-8")

        kq = approval_gate.verify_chain()
        self.assertFalse(kq["ok"])
        self.assertEqual(kq["hong_dong"], 1)

    def test_ky_tu_ngat_dong_unicode_khong_lam_gay_chuoi(self) -> None:
        """U+2028 (LINE SEPARATOR) lọt vào `summary` từ chính câu người dùng gõ.
        `json.dumps(ensure_ascii=False)` ghi nó ra nguyên vẹn, mà `splitlines()`
        lại tách ở đó — một dòng JSON lành lặn bị cắt đôi và chuỗi gãy oan."""
        approval_gate.log_event("pending", "u1", "control_home", summary="bật đèn")
        approval_gate.log_event("pending", "u2", "send_message",
                                summary="gửi:\u2028dòng hai")
        approval_gate.log_event("pending", "u3", "control_home", summary="tắt đèn")

        kq = approval_gate.verify_chain()
        self.assertTrue(kq["ok"], kq["ly_do"])
        self.assertEqual(kq["so_dong"], 3)
        # Và bản ghi TIẾP THEO vẫn nối đúng mắt xích, không rơi vào "unknown".
        self.assertEqual(kq["mat_xich_khong_ro"], 0)

    def test_tra_ve_moc_de_phat_hien_cat_duoi(self) -> None:
        """Cắt đuôi để lại tiền tố hợp lệ nên `ok` vẫn true — đó là điểm mù đã
        ghi rõ trong docstring. Bù lại phải trả mốc để so giữa hai lần kiểm."""
        self._ghi(4)
        truoc = approval_gate.verify_chain()
        self.assertTrue(truoc["hash_cuoi"])

        dong = self.log.read_text(encoding="utf-8").splitlines()
        self.log.write_text("\n".join(dong[:2]) + "\n", encoding="utf-8")

        sau = approval_gate.verify_chain()
        self.assertTrue(sau["ok"])                       # điểm mù đã biết
        self.assertLess(sau["so_dong"], truoc["so_dong"])  # nhưng lộ ở số dòng
        self.assertNotEqual(sau["hash_cuoi"], truoc["hash_cuoi"])

    def test_mat_xich_khong_ro_khong_bi_ket_luan_la_bi_sua(self) -> None:
        """`prev: unknown` là do lúc ghi không đọc nổi dòng cuối (đĩa lỗi).
        Kết luận "bị sửa" ở đây là báo động giả, và báo động giả thì người ta
        bỏ luôn thói quen kiểm."""
        self._ghi(2)
        row = {"ts": 1.0, "kind": "pending", "user_id": "u9",
               "capability": "control_home", "summary": "sau sự cố đĩa",
               "prev": "unknown"}
        row["hash"] = approval_gate._bam_dong(row)
        with self.log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._ghi(1)

        kq = approval_gate.verify_chain()
        self.assertTrue(kq["ok"], kq["ly_do"])
        self.assertEqual(kq["mat_xich_khong_ro"], 1)
        self.assertEqual(kq["so_dong"], 4)


@pytest.mark.adapter
class DuongTatTrongLuotChatTests(unittest.TestCase):
    """Câu khớp trigger phải đi thẳng pipeline, không phó cho model định tuyến."""

    def test_cau_khop_trigger_chay_thang_workflow(self) -> None:
        import services.agent.orchestrator as orch

        with install_data_dir() as root:
            thu_muc = root / "agent" / "workflows"
            thu_muc.mkdir(parents=True, exist_ok=True)
            wf._reset_for_tests(thu_muc)
            wf._seeded = True
            _viet(thu_muc, "su-co", "name: Sự cố\ntrigger: tin_nhan\nkhi: mất điện")
            try:
                with mock.patch.dict(
                    config.data,
                    {"agent_workflows": {"enabled": True, "max_steps": 5}},
                ):
                    with mock.patch.object(
                        wf, "_run_llm_step", return_value="đã kiểm tra tủ điện",
                    ) as buoc:
                        with mock.patch.object(orch, "call_model") as model_router:
                            out = orch.orchestrate(
                                "nhà mình mất điện rồi em ơi", "zalop_wf_trigger",
                            )
            finally:
                wf._reset_for_tests()

        text = str(out.get("text") or "")
        self.assertIn("đã kiểm tra tủ điện", text)
        self.assertEqual(buoc.call_count, 2)  # đủ hai bước của pipeline
        # Không vòng qua lượt model định tuyến — đó chính là điểm của đường tắt.
        self.assertEqual(model_router.call_count, 0)


@pytest.mark.adapter
class PhanHoiGuiNguoiDungTests(_NenWorkflow):
    """Người dùng nhận NỘI DUNG, không nhận nhật ký chạy máy."""

    def test_tin_nhan_khong_kem_nhat_ky_buoc(self) -> None:
        """Đo thật trên `morning-brief`: tin gửi đi 562 ký tự mà nội dung chỉ
        102 — phần dư là bản nháp các bước, lặp lại chính nội dung ấy hai lần."""
        _viet(self.root, "gon", "name: Gọn\ndescription: hai bước")
        with mock.patch.object(wf, "_run_llm_step", return_value="nội dung cuối"):
            kq = wf.run("gon", "chạy đi")
        self.assertEqual(kq["text"], "nội dung cuối")
        for rac in ("———", "• B1", "⏱", "🔄", "bước"):
            self.assertNotIn(rac, kq["text"])

    def test_buoc_loi_thi_dung_han_khong_chay_tiep(self) -> None:
        """Bước hỏng mà chạy tiếp thì bước sau nhận câu báo lỗi làm dữ liệu vào,
        tốn thêm lượt model để sinh ra thứ bỏ đi, mà `verify` còn chấm PASS."""
        _viet(self.root, "hong", "name: Hỏng\nverify: true")
        goi = {"n": 0}

        def gia_lap(model: object, messages: object, **kw: object) -> dict:
            goi["n"] += 1
            if goi["n"] == 1:
                return {"choices": [{"message": {"content": "xong bước 1"}}]}
            return {"error": "429 rate limit"}

        with mock.patch.object(wf, "call_model", side_effect=gia_lap):
            kq = wf.run("hong", "chạy đi")

        self.assertFalse(kq["ok"])
        self.assertEqual(kq["steps_run"], 1)
        self.assertIn("bước 2", kq["text"])
        self.assertIn("429", str(kq.get("error") or ""))
        # Dừng = KHÔNG đốt thêm lượt model nào. Bước 1 đạt, bước 2 lỗi, hết.
        # Bản cũ chạy tiếp sẽ tốn thêm ít nhất một lượt cho bước kiểm chứng.
        self.assertEqual(goi["n"], 2)
        # Và không được chấm đạt cho một chuỗi đã hỏng giữa chừng.
        self.assertIsNone(kq.get("verified"))

    def test_loi_ngay_buoc_dau_van_tra_loi_tu_te(self) -> None:
        _viet(self.root, "hong1", "name: Hỏng ngay")
        with mock.patch.object(wf, "call_model", return_value={"error": "hết hạn mức"}):
            kq = wf.run("hong1", "chạy đi")
        self.assertFalse(kq["ok"])
        self.assertEqual(kq["steps_run"], 0)
        self.assertTrue(str(kq["text"]).strip())
        # Chỗ chạy phải được trả lại kể cả khi dừng giữa chừng.
        self.assertEqual(wf.dang_chay(), 0)


@pytest.mark.adapter
class CongGiaoVienTests(_NenWorkflow):
    """Ba đường vào cùng một pipeline phải qua CHUNG một cổng quyền."""

    def test_duong_tat_khong_duoc_bo_qua_cong_giao_vien(self) -> None:
        """Bản đầu chỉ tool `run_workflow` bị kiểm, nên một thread chưa hề được
        cấp nhóm «Giáo viên tiểu học» chỉ cần gõ đúng từ khoá là chạy `cham-bai`."""
        from services.agent import teacher as teach

        _viet(self.root, "cham-bai", "name: Chấm bài\ntrigger: tin_nhan\nkhi: chấm bài")
        self.assertIn("cham-bai", teach.TEACHER_WORKFLOWS)

        with mock.patch.object(teach, "is_enabled", return_value=True), \
             mock.patch.object(teach, "can_use_teacher", return_value=False), \
             mock.patch.object(wf, "_run_llm_step", return_value="ĐÃ CHẤM") as buoc:
            kq = wf.run("cham-bai", "chấm bài giúp em", ctx={"user_id": "zalop_x"})

        self.assertFalse(kq["ok"])
        self.assertIn("Giáo viên", kq["text"])
        # Chặn nghĩa là KHÔNG chạy bước nào, không phải chạy xong rồi mới nói.
        self.assertEqual(buoc.call_count, 0)

    def test_thread_duoc_cap_quyen_thi_chay_binh_thuong(self) -> None:
        from services.agent import teacher as teach

        _viet(self.root, "cham-bai", "name: Chấm bài\ntrigger: tin_nhan\nkhi: chấm bài")
        with mock.patch.object(teach, "is_enabled", return_value=True), \
             mock.patch.object(teach, "can_use_teacher", return_value=True), \
             mock.patch.object(wf, "_run_llm_step", return_value="ĐÃ CHẤM"):
            kq = wf.run("cham-bai", "chấm bài giúp em", ctx={"user_id": "zalop_x"})
        self.assertTrue(kq["ok"])

    def test_workflow_thuong_khong_bi_cong_giao_vien_chan(self) -> None:
        _viet(self.root, "thuong", "name: Thường")
        with mock.patch.object(wf, "_run_llm_step", return_value="xong"):
            self.assertTrue(wf.run("thuong", "chạy đi").get("ok"))


@pytest.mark.pure
class DanhSoBuocTests(_NenWorkflow):
    def test_bao_dung_buoc_THU_MAY_du_file_danh_so_la(self) -> None:
        """`## Bước 3` / `## Bước 7` là số người viết TỰ gõ, không phải vị trí.
        Lấy nhầm nó thì bước đầu tiên hỏng lại báo "chạy tới bước 3, xong 2 bước"."""
        (self.root / "la.md").write_text(
            "---\nname: Đánh số lạ\n---\n\n## Bước 3: Một\nx\n\n## Bước 7: Hai\ny\n",
            encoding="utf-8",
        )
        with mock.patch.object(wf, "call_model", return_value={"error": "hỏng"}):
            kq = wf.run("la", "chạy đi")
        self.assertFalse(kq["ok"])
        self.assertEqual(kq["steps_run"], 0)
        self.assertIn("bước 1", kq["text"])


if __name__ == "__main__":
    unittest.main()
