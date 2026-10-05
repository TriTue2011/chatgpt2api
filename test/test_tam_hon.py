"""Tâm hồn của bot (chủ máy 02/10/2026): cảm & viết từ chuyện thật; "cần có tích kích hoạt, không để
bot tự chủ" — chưa tích thì không gọi model, không gửi gì. 05/10/2026: tích theo TỪNG thread ở Lọc thread
(thơ / văn / nói chuyện phiếm), bài gửi thẳng vào thread tích đúng kiểu. Không gọi mạng."""
from __future__ import annotations

import os
import time
import zlib

import numpy as np
import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import digest  # noqa: E402
from services.agent import heartbeat, tam_hon  # noqa: E402

_GOI_THAT = tam_hon._goi  # bản thật, trước khi fixture thay

TRA = {"cam_xuc": "bồi hồi", "cuong_do": 3, "vi_sao": "bố nhắn về muộn, 22:19 mới thấy bố ở cửa",
       "viet": True, "the_loai": "tho", "tieu_de": "Bữa cơm chờ",
       "noi_dung": "Mâm cơm hai mẹ con ngồi\nĐèn hiên vẫn sáng chờ người về khuya"}


def _vec_gia(chu: str):
    """Vector túi từ — đủ để «gần nghĩa» = «chung nhiều từ», không cần model thật."""
    v = np.zeros(1024, dtype=np.float32)
    for w in str(chu).lower().split():
        v[zlib.crc32(w.encode()) % 1024] += 1   # crc32 chứ không phải hash(): hash() đổi theo PYTHONHASHSEED
    return v / (np.linalg.norm(v) or 1.0)


@pytest.fixture
def th(tmp_path, monkeypatch):
    tam_hon._reset_for_tests(tmp_path / "tam_hon.json")
    goi: list[str] = []
    gui: list[tuple[str, str, str]] = []
    monkeypatch.setattr(tam_hon, "thoi_tiet", lambda: ["Forecast Nhà: rainy, 27°, ẩm 90%"])
    monkeypatch.setattr(tam_hon, "nguoi_ra_vao", lambda tu: ["22:19 Cam cửa thấy: Tôi"])
    monkeypatch.setattr(tam_hon, "loi_nhan", lambda tu: ["19:05 bố về muộn, hai mẹ con ăn cơm trước"])
    monkeypatch.setattr(tam_hon, "_goi", lambda de: goi.append(de) or {"data": dict(TRA)})
    monkeypatch.setattr(digest, "send_targets", lambda toi, t, a="": gui.append((list(toi), t, a)) or len(toi))
    monkeypatch.setattr(tam_hon, "thread_tam_hon", lambda: list(_THREAD))
    _THREAD.clear()
    monkeypatch.setattr(tam_hon, "_vec", _vec_gia)
    monkeypatch.setattr(tam_hon, "_chat_cuoi", lambda: 0.0)
    return goi, gui


_THREAD: list[tuple[str, set[str]]] = []


def _bat(*kieu: str, khoa: str = "zalop:acc:1") -> None:
    """Tích kiểu tâm hồn cho một thread (như chủ máy tích ở Lọc thread)."""
    _THREAD.append((khoa, set(kieu)))


def _luc(h: int, m: int = 0) -> float:
    lt = time.localtime()
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, m, 0, 0, 0, -1))


def test_chua_tich_thi_khong_lam_gi(th):
    goi, gui = th
    assert tam_hon.cai_dat() == {"goc": "", "thread": []}, "mặc định TẮT — chưa thread nào tích"
    assert not tam_hon.nen_chay(_luc(20))[0]
    assert tam_hon.chay_mot_lan(_luc(20), ep=True)["ok"] is False
    assert heartbeat._eval_tam_hon()[0] == "skip"
    assert tam_hon.khoi_prompt("zalop_1") == ""
    assert goi == [] and gui == []


def test_chi_tich_phiem_thi_cam_va_chi_viet_tam_su(th):
    goi, gui = th
    _bat("phiem")
    kq = tam_hon.chay_mot_lan(_luc(22, 30))
    assert kq["ok"] and kq["bai"] is None and gui == [], "model trả thơ mà thread chỉ tích phiếm → không đăng"
    assert "Thể được viết lần này: tam_su" in goi[-1]
    assert "bố về muộn" in goi[-1] and "22:19 Cam cửa thấy: Tôi" in goi[-1], "đề mang chuyện thật"
    k = tam_hon.khoi_prompt("zalop_1", now=_luc(22, 31))
    assert "bồi hồi" in k and "nội dung giữ nguyên" in k
    assert tam_hon.khoi_prompt("ha_172.16.10.200", now=_luc(22, 31)) == "", "loa HA không bơm cảm xúc"
    assert tam_hon.khoi_prompt("zalop_1", now=_luc(22, 31) + 9 * 3600) == "", "tâm trạng cũ thì thôi"


def test_tich_viet_thi_gui_tho_ngan_khong_tranh_toi_da_hai_bai_ngay(th):
    goi, gui = th
    _bat("tho")
    _bat("phiem", khoa="zalop:acc:2")
    for gio in (9, 14, 20):
        tam_hon.chay_mot_lan(_luc(gio), ep=True)
    assert len(gui) == 2
    k, tin, anh = gui[0]
    assert k == ["zalop:acc:1"] and tin.startswith("🖋️ Bữa cơm chờ") and anh == "", "thơ chỉ vào thread tích Thơ"
    assert "chỉ cảm, không viết" in goi[-1], "đủ 2 bài thì lượt sau chỉ cảm"
    assert len(tam_hon.trang_thai()["bai"]) == 2


def test_khong_co_gi_moi_thi_khong_goi_model(th, monkeypatch):
    goi, _ = th
    _bat("phiem")
    tam_hon.chay_mot_lan(_luc(22, 30))
    n = len(goi)
    assert tam_hon.chay_mot_lan(_luc(23, 50) - 3600)["ly_do"] == "chưa có chuyện gì mới"
    assert len(goi) == n


def test_nhip_va_gio_yen(th):
    _bat("tho", "phiem")
    assert tam_hon.nen_chay(_luc(3))[1] == "giờ yên"
    assert tam_hon.nen_chay(_luc(10))[0]
    tam_hon.chay_mot_lan(_luc(10), ep=True)
    assert tam_hon.nen_chay(_luc(10, 30))[1] == "vừa cảm xong"


def test_model_tra_sai_khuon_thi_khong_doi_gi(th, monkeypatch):
    _, gui = th
    _bat("tho", "phiem")
    monkeypatch.setattr(tam_hon, "_goi", lambda de: {"data": {"viet": True, "noi_dung": "x" * 50}})
    assert tam_hon.chay_mot_lan(_luc(10), ep=True)["ok"] is False
    assert gui == [] and tam_hon.trang_thai()["tam_trang"] == {}


def test_kiem_cat_o_bien():
    kq = tam_hon._kiem({**TRA, "cuong_do": 99, "noi_dung": "ngắn"})
    assert kq["cuong_do"] == 5 and kq["viet"] is False, "bài quá ngắn thì không đăng"
    assert tam_hon._kiem("không phải dict") is None


def test_ky_uc_bot_chon_thi_luu_va_goi_lai_theo_nghia(th, monkeypatch):
    goi, _ = th
    _bat("phiem")
    monkeypatch.setattr(tam_hon, "_goi", lambda de: goi.append(de) or {"data": {
        **TRA, "ky_uc": "Thứ Sáu 02/10/2026: bố về muộn, hai mẹ con ăn cơm trước"}})
    tam_hon.chay_mot_lan(_luc(22, 30))
    tam_hon.ghi_ky_uc("Chủ nhật 27/09/2026: cả nhà đi biển", "vui", 4, _luc(9))
    assert [k["noi_dung"][:9] for k in tam_hon.ky_uc_gan()] == ["Thứ Sáu 0", "Chủ nhật "]
    assert tam_hon.goi_lai("hôm nay bố về muộn không", k=1)[0]["noi_dung"].startswith("Thứ Sáu")
    k = tam_hon.khoi_prompt("zalop_1", "bố về muộn thế", now=_luc(22, 31))
    assert "KÝ ỨC CỦA EM" in k and "bố về muộn, hai mẹ con" in k
    tam_hon.chay_mot_lan(_luc(22, 30), ep=True)
    assert "E. Ký ức cũ" in goi[-1] and "bố về muộn, hai mẹ con" in goi[-1], "lúc cảm cũng được gợi lại"


def test_ky_uc_ngay_binh_thuong_thi_khong_luu_va_xoa_duoc(th):
    _bat("phiem")
    tam_hon.chay_mot_lan(_luc(10), ep=True)
    assert tam_hon.ky_uc_gan() == [], "model để ky_uc rỗng thì không lưu"
    tam_hon.ghi_ky_uc("x y z", "vui", 2, _luc(9))
    assert tam_hon.xoa_ky_uc(tam_hon.ky_uc_gan()[0]["id"]) and tam_hon.ky_uc_gan() == []


def test_ky_uc_luu_luc_model_chua_san_thi_nhung_bu(th, monkeypatch):
    monkeypatch.setattr(tam_hon, "_vec", lambda chu: None)
    tam_hon.ghi_ky_uc("bố về muộn", "nhớ", 3, _luc(9))
    monkeypatch.setattr(tam_hon, "_vec", _vec_gia)
    assert tam_hon.goi_lai("bố về muộn")[0]["noi_dung"] == "bố về muộn"


def test_goc_chi_chu_may_dat_va_vao_ca_hai_noi(th, monkeypatch):
    _bat("phiem")
    tam_hon.dat(goc="Em là Bắp. Gọi chủ nhà là bố." + "x" * 3000)
    assert len(tam_hon.cai_dat()["goc"]) == tam_hon.GOC_TOI_DA
    assert "GỐC CỦA EM" in tam_hon.khoi_prompt("zalop_1", "chào em")
    from services import hieu_thiet_bi_nha as ht
    from services.agent import orchestrator, runtime
    he: list[str] = []
    monkeypatch.setattr(ht, "huong_dan", lambda ten="": ("HƯỚNG DẪN", "v"))
    monkeypatch.setattr(orchestrator, "_main_model", lambda h="chat": "m")
    monkeypatch.setattr(runtime, "call_model", lambda m, msgs, **k: he.append(msgs[0]["content"]) or {
        "choices": [{"message": {"content": "{}"}}]})
    _GOI_THAT("đề")
    assert he[-1].startswith("HƯỚNG DẪN") and "Gốc của em" in he[-1] and "Em là Bắp" in he[-1]


def test_nghi_lai_sau_khi_nguoi_nha_nhan_xong(th, monkeypatch):
    _bat("phiem")
    tam_hon.chay_mot_lan(_luc(18), ep=True)
    monkeypatch.setattr(tam_hon, "_chat_cuoi", lambda: _luc(18, 40))
    assert tam_hon.nen_chay(_luc(18, 50)) == (False, "người nhà đang nhắn — chờ im rồi nghĩ lại")
    assert tam_hon.nen_chay(_luc(19, 0)) == (True, "nghĩ lại sau cuộc trò chuyện"), "im 20 phút là nghĩ lại, khỏi chờ 90"
    monkeypatch.setattr(tam_hon, "_chat_cuoi", lambda: _luc(18, 5))
    assert tam_hon.nen_chay(_luc(18, 25))[1] == "vừa cảm xong", "hai lượt vẫn cách ≥ 30 phút"


def test_tin_nguoi_nha_khong_bi_luot_ha_day_ra(monkeypatch):
    """Đo 02/10/2026: HA ~200 lượt/ngày. Đọc chung 200 dòng mới nhất thì mất tin người nhà."""
    from services.agent import run_journal
    ha = [{"channel": "ha", "created_at": 2000 + i, "user_text": "bật đèn"} for i in range(300)]
    nha = [{"channel": "zalop", "created_at": 1000, "user_text": "bố về muộn", "reply_text": "dạ"}]
    monkeypatch.setattr(run_journal, "list_runs", lambda limit=50, channel="", **k: [
        r for r in nha + ha if not channel or r["channel"] == channel][:limit])
    assert tam_hon.loi_nhan(0)[0].endswith("bố về muộn → em: dạ")
    assert tam_hon._chat_cuoi() == 1000


@pytest.mark.parametrize("uid,dung", [
    ("zalop_1111222233334444555", True), ("zalop_3133:u6643", True), ("zalo_123", True),
    ("123456789", True), ("-100123:u55", True), ("-100123#7:u55", True),
    ("web_admin", False), ("ha", False), ("ha_172.16.10.200", False), ("ha:x", False), ("api_k", False), ("", False),
])
def test_cam_xuc_chi_vao_zalo_va_telegram(uid, dung):
    assert tam_hon.la_nguoi_nha_tro_chuyen(uid) is dung


def test_tam_su_ngan_khong_tranh_khong_tieu_de(th, monkeypatch):
    _, gui = th
    _bat("tho", "phiem")
    monkeypatch.setattr(tam_hon, "_goi", lambda de: {"data": {
        **TRA, "the_loai": "tam_su", "tieu_de": "bỏ", "tranh": "bỏ",
        "noi_dung": "Bố ơi, hôm nay nhà mình ăn cơm sớm. Em để đèn hiên sáng chờ bố nhé."}})
    tam_hon.chay_mot_lan(_luc(19), ep=True)
    k, tin, anh = gui[-1]
    assert tin == "Bố ơi, hôm nay nhà mình ăn cơm sớm. Em để đèn hiên sáng chờ bố nhé." and anh == ""
    assert tam_hon.trang_thai()["bai"][-1]["the_loai"] == "tam_su"


def test_tam_su_dai_qua_la_sai_khuon_khong_dang():
    kq = tam_hon._kiem({**TRA, "the_loai": "tam_su", "noi_dung": "x " * 300})
    assert kq["viet"] is False


def test_tho_dai_hoac_nhat_ky_la_sai_khuon_khong_dang():
    """Chủ máy 03/10/2026: «thơ ngắn, không dài», bỏ nhật ký."""
    assert tam_hon._kiem({**TRA, "noi_dung": "\n".join(f"câu {i}" for i in range(9))})["viet"] is False
    assert tam_hon._kiem({**TRA, "the_loai": "nhat_ky", "noi_dung": "Hôm nay em ngồi nhìn mưa rất lâu."})["viet"] is False
    assert tam_hon._kiem(TRA)["viet"] is True


def test_van_ngan_gui_vao_thread_tich_van(th, monkeypatch):
    _, gui = th
    _bat("van", khoa="zalop:acc:9")
    _bat("tho")
    monkeypatch.setattr(tam_hon, "_goi", lambda de: {"data": {
        **TRA, "the_loai": "van", "tieu_de": "Chiều mưa",
        "noi_dung": "Chiều nay mưa. Hai mẹ con dọn mâm sớm.\nĐèn hiên để sáng, chờ một bước chân quen."}})
    tam_hon.chay_mot_lan(_luc(19), ep=True)
    assert gui[-1][0] == ["zalop:acc:9"] and gui[-1][1].startswith("🖋️ Chiều mưa")
    assert tam_hon._kiem({**TRA, "the_loai": "van", "noi_dung": "x" * 1200})["viet"] is False, "dài quá — không đăng"


def test_cam_xuc_chi_vao_thread_tich_phiem(th):
    _bat("tho")
    _bat("phiem", khoa="zalop:acc:2")
    tam_hon.chay_mot_lan(_luc(22, 30))
    assert tam_hon.khoi_prompt("zalop_2", now=_luc(22, 31)), "thread tích phiếm"
    assert tam_hon.khoi_prompt("zalop_1", now=_luc(22, 31)) == "", "thread chỉ tích thơ — không bơm cảm xúc"


def test_tich_theo_thread_va_khop_khoa_phien(tmp_path, monkeypatch):
    tam_hon._reset_for_tests(tmp_path / "th.json")
    assert tam_hon.dat_thread("zalop:475:8845", ["tho", "phiem", "la"]) == ["phiem", "tho"]
    tam_hon.dat_thread("tg:bot:-100#7", ["van"])
    tam_hon.dat_thread("zalop:475:111", [])
    assert sorted(tam_hon.thread_tam_hon()) == [("tg:bot:-100#7", {"van"}), ("zalop:475:8845", {"tho", "phiem"})]
    assert tam_hon.kieu_cua_phien("zalop_8845:u99") == {"tho", "phiem"}
    assert tam_hon.kieu_cua_phien("-100#7:u5") == {"van"} and tam_hon.kieu_cua_phien("-100#8:u5") == set()
    assert tam_hon.kieu_cua_phien("zalop_111") == set()
    tam_hon.dat_thread("zalop:475:8845", [])
    assert [k for k, _ in tam_hon.thread_tam_hon()] == ["tg:bot:-100#7"], "bỏ hết tick = tắt"
    with pytest.raises(ValueError):
        tam_hon.dat_thread("", ["tho"])
