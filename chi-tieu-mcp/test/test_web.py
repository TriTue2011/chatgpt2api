"""Test route web (/ui, /api/*) — dựng FastMCP test riêng qua dang_ky_route(),
đúng cách main.py wire thật, không đụng server đang chạy hay data/chi_tieu.db."""
import json
import re
import sys
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MAT_KHAU_TEST = "test-key-123"


@pytest.fixture(autouse=True)
def _moi_truong_tam(tmp_path, monkeypatch):
    db_path = tmp_path / "chi_tieu_test.db"
    jars_path = tmp_path / "jars_config.json"
    jars_path.write_text(json.dumps({
        "thu_nhap_thuc_linh_thang": 10_000_000,
        "hu": [
            {"ma": "thiet_yeu", "ten": "Thiết Yếu", "ty_le_phan_tram": 50.0},
            {"ma": "huong_thu", "ten": "Hưởng Thụ", "ty_le_phan_tram": 10.0},
        ],
        "nguong_canh_bao": [0.65, 0.8, 1.0],
    }), encoding="utf-8")

    import app.storage as storage
    monkeypatch.setattr(storage, "DB_PATH", db_path)
    storage.khoi_tao_db()

    import app.jars as jars
    monkeypatch.setattr(jars, "JARS_CONFIG_PATH", jars_path)

    import app.pdf_cong_ty as pdf_cong_ty
    monkeypatch.setattr(pdf_cong_ty, "THU_MUC_PDF", tmp_path / "tam_ung_pdf")

    from app import web
    monkeypatch.setattr(web, "C2A_AUTH_KEY", MAT_KHAU_TEST)
    yield


def _tao_app_test():
    from mcp.server.fastmcp import FastMCP
    from app import web
    mcp_test = FastMCP("test-chi-tieu-bot", stateless_http=True, host="0.0.0.0")
    web.dang_ky_route(mcp_test)
    return mcp_test.streamable_http_app()


def _dang_nhap(client):
    client.post("/ui/dang-nhap", data={"mat_khau": MAT_KHAU_TEST})


def _request_voi_cookie_non_ascii(client, method, url, cookie_value_bytes):
    """Gửi request với header Cookie chứa bytes non-ASCII thẳng.

    httpx từ chối non-ASCII ngay phía client nếu truyền qua client.cookies.set()
    hoặc headers={...} dạng dict str (raise UnicodeEncodeError trước khi kịp gửi
    request) — xác nhận thực nghiệm khi viết test này. Cách duy nhất thấy được
    để đưa bytes non-ASCII vào Cookie header qua TestClient là build request rồi
    thay headers bằng danh sách tuple (bytes, bytes) thô, né bước encode str->ascii
    của httpx.
    """
    req = client.build_request(method, url)
    raw = [h for h in req.headers.raw if h[0].lower() != b"cookie"]
    raw.append((b"cookie", b"chitieu_session=" + cookie_value_bytes))
    req.headers = httpx.Headers(raw)
    return client.send(req, follow_redirects=False)


def test_trang_login_tra_ve_200():
    with TestClient(_tao_app_test()) as client:
        resp = client.get("/ui/login")
        assert resp.status_code == 200
        assert "mat_khau" in resp.text


def test_trang_login_hien_thi_canh_bao_khi_chua_cau_hinh(monkeypatch):
    """I4: trang /ui/login phải chủ động báo 'chưa cấu hình' khi C2A_AUTH_KEY
    rỗng, không chỉ đợi POST thất bại mới báo. Đây là state thật của .env hiện
    tại trên server."""
    from app import web
    monkeypatch.setattr(web, "C2A_AUTH_KEY", "")
    with TestClient(_tao_app_test()) as client:
        resp = client.get("/ui/login")
        assert resp.status_code == 200
        assert "chưa cấu hình" in resp.text.lower()


def test_dang_nhap_chua_cau_hinh_tra_ve_503(monkeypatch):
    """503 (Service Unavailable) đúng nghĩa hơn 500 cho lỗi thiếu cấu hình --
    không đụng tới nhánh 401 (sai mật khẩu)."""
    from app import web
    monkeypatch.setattr(web, "C2A_AUTH_KEY", "")
    with TestClient(_tao_app_test()) as client:
        resp = client.post("/ui/dang-nhap", data={"mat_khau": "bat_ky_gi"}, follow_redirects=False)
        assert resp.status_code == 503


def test_dang_nhap_sai_mat_khau():
    with TestClient(_tao_app_test()) as client:
        resp = client.post("/ui/dang-nhap", data={"mat_khau": "sai"}, follow_redirects=False)
        assert resp.status_code == 401
        assert "chitieu_session" not in resp.cookies


def test_dang_nhap_sai_mat_khau_co_dau_tieng_viet():
    """hmac.compare_digest crash TypeError trên str non-ASCII (I1) — mật khẩu
    sai có dấu phải trả 401 như mật khẩu sai bình thường, không phải 500."""
    with TestClient(_tao_app_test()) as client:
        resp = client.post("/ui/dang-nhap", data={"mat_khau": "mật khẩu sai"}, follow_redirects=False)
        assert resp.status_code == 401
        assert "chitieu_session" not in resp.cookies


def test_dang_nhap_dung_mat_khau_set_cookie():
    with TestClient(_tao_app_test()) as client:
        resp = client.post("/ui/dang-nhap", data={"mat_khau": MAT_KHAU_TEST}, follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui"
        assert "chitieu_session" in resp.cookies


def test_dang_xuat_xoa_cookie():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/ui/dang-xuat", follow_redirects=False)
        assert resp.status_code == 303
        assert client.cookies.get("chitieu_session") is None


def test_api_ngan_sach_can_dang_nhap():
    with TestClient(_tao_app_test()) as client:
        resp = client.get("/api/ngan-sach")
        assert resp.status_code == 401


def test_api_ngan_sach_cookie_non_ascii_tra_ve_401_khong_crash():
    """_da_dang_nhap dùng hmac.compare_digest trên cookie chưa encode — cookie
    non-ASCII trước đây làm TOÀN BỘ route (kể cả /ui) crash 500 (I1). Bất kỳ ai
    trong LAN gửi cookie này (không cần đăng nhập) đều trigger được — availability
    bug, không phải auth bypass."""
    with TestClient(_tao_app_test()) as client:
        resp = _request_voi_cookie_non_ascii(
            client, "GET", "/api/ngan-sach", "mật_khẩu_sai".encode("utf-8")
        )
        assert resp.status_code == 401


def test_trang_chinh_cookie_non_ascii_redirect_khong_crash():
    """Như trên nhưng cho GET /ui — phải redirect về /ui/login (coi như chưa
    đăng nhập), không phải 500."""
    with TestClient(_tao_app_test()) as client:
        resp = _request_voi_cookie_non_ascii(
            client, "GET", "/ui", "mật_khẩu_sai".encode("utf-8")
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui/login"


def test_api_ngan_sach_tra_ve_du_lieu():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.get("/api/ngan-sach")
        assert resp.status_code == 200
        data = resp.json()
        ma_cac_hu = {h["ma"] for h in data["hu"]}
        assert ma_cac_hu == {"thiet_yeu", "huong_thu"}


def test_api_lich_su_can_dang_nhap():
    with TestClient(_tao_app_test()) as client:
        resp = client.get("/api/lich-su")
        assert resp.status_code == 401


def test_api_lich_su_tra_ve_giao_dich_kem_id():
    from app.storage import ghi_chi_tieu
    from app.jars import thang_hien_tai
    id_khoan = ghi_chi_tieu("thiet_yeu", 50_000, "an trua")
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.get(f"/api/lich-su?thang={thang_hien_tai()}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["so_luong"] == 1
        assert data["tong_tien"] == 50_000
        assert data["giao_dich"][0]["id"] == id_khoan


def test_api_lich_su_thang_malformed_tra_ve_400():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.get("/api/lich-su?thang=abc")
        assert resp.status_code == 400


def test_api_de_xuat_can_dang_nhap():
    with TestClient(_tao_app_test()) as client:
        resp = client.get("/api/de-xuat")
        assert resp.status_code == 401


def test_api_de_xuat_tra_ve_du_lieu():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.get("/api/de-xuat")
        assert resp.status_code == 200
        assert "de_xuat" in resp.json()


# --- _so_client_hop_le: helper số dùng chung cho thu_nhap/ty_le_phan_tram/
# so_tien, sau khi round 2 review phát hiện math.isfinite() tự raise
# OverflowError trên int khổng lồ (bug do chính round 1 gây ra) và no-upper-
# -bound trên thu_nhap. Test trực tiếp hàm (khác quy ước black-box qua HTTP
# của phần còn lại file này) vì đây là hàm dùng chung ở nhiều nơi, đã bị lỗi
# 2 lần, và test biên chính xác qua HTTP sẽ dài dòng/khó đọc hơn nhiều.


def test_so_client_hop_le_chap_nhan_so_binh_thuong_va_bien():
    from app.web import _so_client_hop_le, GIOI_HAN_SO_TIEN_VND
    assert _so_client_hop_le(5_000_000, GIOI_HAN_SO_TIEN_VND) is True
    assert _so_client_hop_le(5_000_000.5, GIOI_HAN_SO_TIEN_VND) is True
    assert _so_client_hop_le(0, GIOI_HAN_SO_TIEN_VND) is True
    assert _so_client_hop_le(GIOI_HAN_SO_TIEN_VND, GIOI_HAN_SO_TIEN_VND) is True
    assert _so_client_hop_le(-GIOI_HAN_SO_TIEN_VND, GIOI_HAN_SO_TIEN_VND) is True


def test_so_client_hop_le_tu_choi_vuot_bien():
    from app.web import _so_client_hop_le, GIOI_HAN_SO_TIEN_VND
    assert _so_client_hop_le(GIOI_HAN_SO_TIEN_VND + 1, GIOI_HAN_SO_TIEN_VND) is False
    assert _so_client_hop_le(-(GIOI_HAN_SO_TIEN_VND + 1), GIOI_HAN_SO_TIEN_VND) is False


def test_so_client_hop_le_khong_crash_tren_int_khong_lo():
    """Chính xác lỗi round 2: math.isfinite() tự raise OverflowError trên int
    khổng lồ (10**400) vì Python phải convert sang float trước khi check hữu
    hạn. Hàm mới so sánh trực tiếp bằng toán tử quan hệ (an toàn với MỌI kích
    thước int) nên phải trả False êm re, không raise gì cả."""
    from app.web import _so_client_hop_le, GIOI_HAN_SO_TIEN_VND
    assert _so_client_hop_le(10**400, GIOI_HAN_SO_TIEN_VND) is False
    assert _so_client_hop_le(-(10**400), GIOI_HAN_SO_TIEN_VND) is False


def test_so_client_hop_le_tu_choi_nan_va_infinity():
    from app.web import _so_client_hop_le, GIOI_HAN_SO_TIEN_VND
    assert _so_client_hop_le(float("nan"), GIOI_HAN_SO_TIEN_VND) is False
    assert _so_client_hop_le(float("inf"), GIOI_HAN_SO_TIEN_VND) is False
    assert _so_client_hop_le(float("-inf"), GIOI_HAN_SO_TIEN_VND) is False


def test_so_client_hop_le_tu_choi_bool_va_kieu_sai():
    from app.web import _so_client_hop_le, GIOI_HAN_SO_TIEN_VND
    assert _so_client_hop_le(True, GIOI_HAN_SO_TIEN_VND) is False
    assert _so_client_hop_le(False, GIOI_HAN_SO_TIEN_VND) is False
    assert _so_client_hop_le("5000", GIOI_HAN_SO_TIEN_VND) is False
    assert _so_client_hop_le(None, GIOI_HAN_SO_TIEN_VND) is False
    assert _so_client_hop_le([1, 2], GIOI_HAN_SO_TIEN_VND) is False


def test_api_cau_hinh_can_dang_nhap():
    with TestClient(_tao_app_test()) as client:
        resp = client.post("/api/cau-hinh", json={"thu_nhap_thuc_linh_thang": 10_000_000, "hu": []})
        assert resp.status_code == 401


def test_api_cau_hinh_tu_choi_neu_tong_khac_100():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/api/cau-hinh", json={
            "thu_nhap_thuc_linh_thang": 10_000_000,
            "hu": [{"ma": "thiet_yeu", "ty_le_phan_tram": 50.0},
                   {"ma": "huong_thu", "ty_le_phan_tram": 40.0}],
            "ngay_bat_dau_chu_ky": 1,
        })
        assert resp.status_code == 400
        assert "100" in resp.json()["loi"]


def test_api_cau_hinh_tu_choi_neu_thieu_hu():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/api/cau-hinh", json={
            "thu_nhap_thuc_linh_thang": 10_000_000,
            "hu": [{"ma": "thiet_yeu", "ty_le_phan_tram": 100.0}],
        })
        assert resp.status_code == 400


def test_api_cau_hinh_luu_thanh_cong():
    from app.jars import doc_cau_hinh
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/api/cau-hinh", json={
            "thu_nhap_thuc_linh_thang": 12_000_000,
            "hu": [{"ma": "thiet_yeu", "ty_le_phan_tram": 60.0},
                   {"ma": "huong_thu", "ty_le_phan_tram": 40.0}],
            "ngay_bat_dau_chu_ky": 1,
        })
        assert resp.status_code == 200
        cfg = doc_cau_hinh()
        assert cfg["thu_nhap_thuc_linh_thang"] == 12_000_000
        hu_thiet_yeu = next(h for h in cfg["hu"] if h["ma"] == "thiet_yeu")
        assert hu_thiet_yeu["ty_le_phan_tram"] == 60.0
        assert cfg["nguong_canh_bao"] == [0.65, 0.8, 1.0]


def test_api_cau_hinh_body_la_array_tra_ve_400():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/api/cau-hinh", json=[1, 2, 3])
        assert resp.status_code == 400


def test_api_cau_hinh_hu_chua_phan_tu_khong_phai_object_tra_ve_400():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/api/cau-hinh", json={
            "thu_nhap_thuc_linh_thang": 10_000_000,
            "hu": ["not", "dicts"],
        })
        assert resp.status_code == 400


def test_api_cau_hinh_thu_nhap_nan_tra_ve_400():
    """httpx tu choi allow_nan=False qua json= kwarg (verified thuc nghiem: raise
    ValueError ngay tren client) -- phai tu build raw bytes body de gui NaN thuc su."""
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        body = (
            b'{"thu_nhap_thuc_linh_thang": NaN, "hu": '
            b'[{"ma": "thiet_yeu", "ty_le_phan_tram": 50.0}, '
            b'{"ma": "huong_thu", "ty_le_phan_tram": 50.0}]}'
        )
        resp = client.post(
            "/api/cau-hinh", content=body, headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 400


def test_api_cau_hinh_thu_nhap_boolean_tra_ve_400_va_khong_ghi_file():
    """isinstance(True, int) la True trong Python -- truoc fix, gui boolean cho
    thu_nhap_thuc_linh_thang bi am tham chap nhan va ghi 1 vao jars_config.json."""
    from app.jars import doc_cau_hinh
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        cfg_truoc = doc_cau_hinh()
        resp = client.post("/api/cau-hinh", json={
            "thu_nhap_thuc_linh_thang": True,
            "hu": [{"ma": "thiet_yeu", "ty_le_phan_tram": 50.0},
                   {"ma": "huong_thu", "ty_le_phan_tram": 50.0}],
        })
        assert resp.status_code == 400
        assert doc_cau_hinh() == cfg_truoc


def test_api_cau_hinh_giu_lai_truong_khong_biet():
    """M8: ghi_cau_hinh phai merge tu cau hinh cu, khong dung 1 dict moi tinh chi
    co 3 key da biet -- key la khac (do thu gi do trong tuong lai ghi) phai duoc
    giu nguyen sau khi luu qua API."""
    from app.jars import doc_cau_hinh, ghi_cau_hinh
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        cfg = doc_cau_hinh()
        cfg["truong_tuong_lai"] = "giu nguyen"
        ghi_cau_hinh(cfg)
        resp = client.post("/api/cau-hinh", json={
            "thu_nhap_thuc_linh_thang": 12_000_000,
            "hu": [{"ma": "thiet_yeu", "ty_le_phan_tram": 60.0},
                   {"ma": "huong_thu", "ty_le_phan_tram": 40.0}],
            "ngay_bat_dau_chu_ky": 1,
        })
        assert resp.status_code == 200
        assert doc_cau_hinh()["truong_tuong_lai"] == "giu nguyen"


def test_api_cau_hinh_ty_le_phan_tram_boolean_tra_ve_400_va_khong_ghi_file():
    """Cùng lớp lỗi với boolean thu_nhap_thuc_linh_thang đã fix -- mỗi mục hu
    cũng phải loại bool. 1 (True) + 99.0 = 100.0 đúng nghĩa nên trước fix sẽ
    qua được cả check tổng = 100% và âm thầm ghi 'true' vào file cấu hình."""
    from app.jars import doc_cau_hinh
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        cfg_truoc = doc_cau_hinh()
        resp = client.post("/api/cau-hinh", json={
            "thu_nhap_thuc_linh_thang": 10_000_000,
            "hu": [{"ma": "thiet_yeu", "ty_le_phan_tram": True},
                   {"ma": "huong_thu", "ty_le_phan_tram": 99.0}],
        })
        assert resp.status_code == 400
        assert doc_cau_hinh() == cfg_truoc


def test_api_cau_hinh_ma_la_list_tra_ve_400_khong_500():
    """set(hu_codes) raise TypeError: unhashable type: 'list' nếu ma không
    phải chuỗi -- isinstance(muc, dict) chỉ check được container, chưa bao
    giờ check kiểu của giá trị ma bên trong."""
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/api/cau-hinh", json={
            "thu_nhap_thuc_linh_thang": 10_000_000,
            "hu": [{"ma": ["thiet_yeu"], "ty_le_phan_tram": 50.0},
                   {"ma": "huong_thu", "ty_le_phan_tram": 50.0}],
        })
        assert resp.status_code == 400


def test_api_cau_hinh_ma_la_dict_tra_ve_400_khong_500():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/api/cau-hinh", json={
            "thu_nhap_thuc_linh_thang": 10_000_000,
            "hu": [{"ma": {"a": 1}, "ty_le_phan_tram": 50.0},
                   {"ma": "huong_thu", "ty_le_phan_tram": 50.0}],
        })
        assert resp.status_code == 400


def test_api_cau_hinh_thu_nhap_int_khong_lo_tra_ve_400_khong_500():
    """Lỗi round 2 do chính I3 fix cũ gây ra: math.isfinite(10**400) tự raise
    OverflowError. Giờ phải trả 400 êm re."""
    from app.jars import doc_cau_hinh
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        cfg_truoc = doc_cau_hinh()
        resp = client.post("/api/cau-hinh", json={
            "thu_nhap_thuc_linh_thang": 10**400,
            "hu": [{"ma": "thiet_yeu", "ty_le_phan_tram": 50.0},
                   {"ma": "huong_thu", "ty_le_phan_tram": 50.0}],
        })
        assert resp.status_code == 400
        assert doc_cau_hinh() == cfg_truoc


def test_api_cau_hinh_thu_nhap_huu_han_nhung_thien_van_tra_ve_400():
    """1e308 hữu hạn thật sự (không NaN, không lớn tới mức int() raise) nhưng
    vẫn phải bị chặn bởi trần hợp lý -- nếu không sẽ ghi vào jars_config.json
    rồi làm vỡ Hu.han_muc() (app/jars.py) ở MỌI nơi đọc lại config: /ui,
    Zalo bot tools (app/tools.py), scheduler."""
    from app.jars import doc_cau_hinh
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        cfg_truoc = doc_cau_hinh()
        resp = client.post("/api/cau-hinh", json={
            "thu_nhap_thuc_linh_thang": 1e308,
            "hu": [{"ma": "thiet_yeu", "ty_le_phan_tram": 50.0},
                   {"ma": "huong_thu", "ty_le_phan_tram": 50.0}],
        })
        assert resp.status_code == 400
        assert doc_cau_hinh() == cfg_truoc


def test_api_cau_hinh_ty_le_phan_tram_int_khong_lo_tra_ve_400_khong_500():
    from app.jars import doc_cau_hinh
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        cfg_truoc = doc_cau_hinh()
        resp = client.post("/api/cau-hinh", json={
            "thu_nhap_thuc_linh_thang": 10_000_000,
            "hu": [{"ma": "thiet_yeu", "ty_le_phan_tram": 10**400},
                   {"ma": "huong_thu", "ty_le_phan_tram": 50.0}],
        })
        assert resp.status_code == 400
        assert doc_cau_hinh() == cfg_truoc


def test_api_cau_hinh_tu_choi_neu_ma_trung_lap():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/api/cau-hinh", json={
            "thu_nhap_thuc_linh_thang": 10_000_000,
            "hu": [{"ma": "thiet_yeu", "ty_le_phan_tram": 50.0},
                   {"ma": "thiet_yeu", "ty_le_phan_tram": 40.0},
                   {"ma": "huong_thu", "ty_le_phan_tram": 10.0}],
        })
        assert resp.status_code == 400


def test_api_sua_chi_tieu_can_dang_nhap():
    with TestClient(_tao_app_test()) as client:
        resp = client.patch("/api/chi-tieu/1", json={"so_tien": 1000})
        assert resp.status_code == 401


def test_api_sua_chi_tieu_thanh_cong():
    from app.storage import ghi_chi_tieu, danh_sach_chi_trong_thang
    from app.jars import thang_hien_tai
    id_khoan = ghi_chi_tieu("thiet_yeu", 100_000)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch(f"/api/chi-tieu/{id_khoan}", json={"so_tien": 200_000, "ghi_chu": "sua roi"})
        assert resp.status_code == 200
    rows = danh_sach_chi_trong_thang(thang_hien_tai())
    assert rows[0]["so_tien"] == 200_000
    assert rows[0]["ghi_chu"] == "sua roi"


def test_api_sua_chi_tieu_body_la_array_tra_ve_400():
    """Cùng lớp lỗi với I3 (body phải là object JSON) — top-level array khiến
    body.get(...) crash AttributeError -> 500 nếu không chặn."""
    from app.storage import ghi_chi_tieu
    id_khoan = ghi_chi_tieu("thiet_yeu", 100_000)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch(f"/api/chi-tieu/{id_khoan}", json=[1, 2, 3])
        assert resp.status_code == 400


def test_api_sua_chi_tieu_id_khong_ton_tai():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch("/api/chi-tieu/999999", json={"so_tien": 1000})
        assert resp.status_code == 404


def test_api_sua_chi_tieu_so_tien_am_tra_ve_400():
    from app.storage import ghi_chi_tieu
    id_khoan = ghi_chi_tieu("thiet_yeu", 100_000)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch(f"/api/chi-tieu/{id_khoan}", json={"so_tien": -5000})
        assert resp.status_code == 400


def test_api_sua_chi_tieu_so_tien_chuoi_tra_ve_400():
    from app.storage import ghi_chi_tieu
    id_khoan = ghi_chi_tieu("thiet_yeu", 100_000)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch(f"/api/chi-tieu/{id_khoan}", json={"so_tien": "abc"})
        assert resp.status_code == 400


def test_api_sua_chi_tieu_body_rong_tren_id_khong_ton_tai_tra_ve_400():
    """Task 1's sua_chi_tieu() trả True vô điều kiện nếu cả 3 field đều None,
    không check id tồn tại hay không -- PATCH với body rỗng trước đây trả 200
    kể cả id không tồn tại, phá vỡ hợp đồng 404 mà mọi handler khác tuân theo."""
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch("/api/chi-tieu/999999", json={})
        assert resp.status_code == 400


def test_api_sua_chi_tieu_ghi_chu_khong_phai_chuoi_tra_ve_400():
    from app.storage import ghi_chi_tieu
    id_khoan = ghi_chi_tieu("thiet_yeu", 100_000)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch(f"/api/chi-tieu/{id_khoan}", json={"ghi_chu": 123})
        assert resp.status_code == 400
        resp2 = client.patch(f"/api/chi-tieu/{id_khoan}", json={"ghi_chu": ["a", "b"]})
        assert resp2.status_code == 400


def test_api_sua_chi_tieu_so_tien_int_khong_lo_tra_ve_400_khong_500():
    """Cùng lỗi round 2 với thu_nhap/ty_le: so_tien cũng dùng chung
    _so_client_hop_le nên phải chặn int khổng lồ (10**400) mà không 500, và
    dòng chi trong DB không bị đổi."""
    from app.storage import ghi_chi_tieu, danh_sach_chi_trong_thang
    from app.jars import thang_hien_tai
    id_khoan = ghi_chi_tieu("thiet_yeu", 100_000)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch(f"/api/chi-tieu/{id_khoan}", json={"so_tien": 10**400})
        assert resp.status_code == 400
    rows = danh_sach_chi_trong_thang(thang_hien_tai())
    assert rows[0]["so_tien"] == 100_000


def test_api_sua_chi_tieu_so_tien_vuot_tran_tra_ve_400():
    """so_tien trước đây không có trần trên -- cùng lớp lỗi I3 (no upper
    bound), rated Minor bởi vì /api/lich-su vẫn query được (không như
    thu_nhap_thuc_linh_thang) nhưng vẫn nên chặn khi đã viết helper dùng
    chung rồi."""
    from app.storage import ghi_chi_tieu, danh_sach_chi_trong_thang
    from app.jars import thang_hien_tai
    id_khoan = ghi_chi_tieu("thiet_yeu", 100_000)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch(f"/api/chi-tieu/{id_khoan}", json={"so_tien": 10**12 + 1})
        assert resp.status_code == 400
    rows = danh_sach_chi_trong_thang(thang_hien_tai())
    assert rows[0]["so_tien"] == 100_000


def test_api_sua_chi_tieu_hu_ma_khong_hop_le():
    from app.storage import ghi_chi_tieu
    id_khoan = ghi_chi_tieu("thiet_yeu", 100_000)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch(f"/api/chi-tieu/{id_khoan}", json={"hu_ma": "khong_ton_tai"})
        assert resp.status_code == 400


def test_api_xoa_chi_tieu_can_dang_nhap():
    with TestClient(_tao_app_test()) as client:
        resp = client.delete("/api/chi-tieu/1")
        assert resp.status_code == 401


def test_api_xoa_chi_tieu_thanh_cong():
    from app.storage import ghi_chi_tieu, danh_sach_chi_trong_thang
    from app.jars import thang_hien_tai
    id_khoan = ghi_chi_tieu("thiet_yeu", 100_000)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.delete(f"/api/chi-tieu/{id_khoan}")
        assert resp.status_code == 200
    assert danh_sach_chi_trong_thang(thang_hien_tai()) == []


def test_api_xoa_chi_tieu_id_khong_ton_tai():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.delete("/api/chi-tieu/999999")
        assert resp.status_code == 404


def test_api_sua_chi_tieu_id_malformed():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch("/api/chi-tieu/abc", json={"so_tien": 1000})
        assert resp.status_code == 400


def test_api_xoa_chi_tieu_id_malformed():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.delete("/api/chi-tieu/abc")
        assert resp.status_code == 400


def test_trang_chinh_can_dang_nhap():
    with TestClient(_tao_app_test()) as client:
        resp = client.get("/ui", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui/login"


def test_trang_chinh_hien_thi_khi_da_dang_nhap():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.get("/ui")
        assert resp.status_code == 200
        assert "cau-hinh" in resp.text
        assert "lich-su" in resp.text
        assert "thu-nhap-them" in resp.text
        assert "cong-ty" in resp.text


def test_api_thu_nhap_them_can_dang_nhap():
    with TestClient(_tao_app_test()) as client:
        resp = client.get("/api/thu-nhap-them")
        assert resp.status_code == 401


def test_api_thu_nhap_them_tra_ve_danh_sach():
    from app.storage import ghi_thu_nhap_them
    from app.jars import thang_hien_tai
    id_khoan = ghi_thu_nhap_them("thuong", 2_000_000)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.get(f"/api/thu-nhap-them?thang={thang_hien_tai()}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tong_tien"] == 2_000_000
        assert data["danh_sach"][0]["id"] == id_khoan


def test_api_thu_nhap_them_thang_malformed_tra_ve_400():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.get("/api/thu-nhap-them?thang=abc")
        assert resp.status_code == 400


def test_luu_cau_hinh_tu_thu_nhap_co_dinh_khong_bi_thu_nhap_them_an_vao():
    """Tái hiện đúng lỗi Critical từ vòng review cuối: JS lấy thu_nhap_co_dinh
    (KHÔNG phải thu_nhap_thuc_linh, vốn đã cộng thu nhập phát sinh) để fill ô
    thu nhập trên /ui rồi lưu lại — lương cố định trong jars_config.json phải
    giữ nguyên dù đã có thu nhập phát sinh trong tháng."""
    from app.storage import ghi_thu_nhap_them
    from app.jars import doc_cau_hinh

    ghi_thu_nhap_them("thuong", 2_000_000)  # thu nhap hieu qua: 10tr + 2tr = 12tr

    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        ngan_sach = client.get("/api/ngan-sach").json()
        assert ngan_sach["thu_nhap_co_dinh"] == 10_000_000
        assert ngan_sach["thu_nhap_thuc_linh"] == 12_000_000

        resp = client.post("/api/cau-hinh", json={
            "thu_nhap_thuc_linh_thang": ngan_sach["thu_nhap_co_dinh"],
            "hu": [
                {"ma": "thiet_yeu", "ty_le_phan_tram": 90.0},
                {"ma": "huong_thu", "ty_le_phan_tram": 10.0},
            ],
            "ngay_bat_dau_chu_ky": ngan_sach["ngay_bat_dau_chu_ky"],
        })
        assert resp.status_code == 200

    assert doc_cau_hinh()["thu_nhap_thuc_linh_thang"] == 10_000_000


def test_api_cong_ty_can_dang_nhap():
    with TestClient(_tao_app_test()) as client:
        resp = client.get("/api/cong-ty")
        assert resp.status_code == 401


def test_api_cong_ty_tra_ve_dung_du_lieu():
    from app.storage import ghi_giao_dich_cong_ty
    id1 = ghi_giao_dich_cong_ty("tam_ung", 5_000_000, "di cong tac")
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.get("/api/cong-ty")
        assert resp.status_code == 200
        data = resp.json()
        assert data["so_du"] == 5_000_000
        assert data["giao_dich_dang_mo"][0]["id"] == id1
        assert data["lich_su_giai_chi"] == []


def test_api_sua_giao_dich_cong_ty_can_dang_nhap():
    with TestClient(_tao_app_test()) as client:
        resp = client.patch("/api/cong-ty/giao-dich/1", json={"so_tien": 1000})
        assert resp.status_code == 401


def test_api_sua_giao_dich_cong_ty_thanh_cong():
    from app.storage import ghi_giao_dich_cong_ty
    id1 = ghi_giao_dich_cong_ty("chi", 300_000, "taxi")
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch(
            f"/api/cong-ty/giao-dich/{id1}",
            json={"so_tien": 350_000, "mo_ta": "taxi + gui xe"},
        )
        assert resp.status_code == 200
        resp2 = client.get("/api/cong-ty")
        gd = resp2.json()["giao_dich_dang_mo"][0]
        assert gd["so_tien"] == 350_000
        assert gd["mo_ta"] == "taxi + gui xe"


def test_api_sua_giao_dich_cong_ty_id_khong_ton_tai():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch("/api/cong-ty/giao-dich/999999", json={"so_tien": 1000})
        assert resp.status_code == 404


def test_api_sua_giao_dich_cong_ty_so_tien_am_tra_ve_400():
    from app.storage import ghi_giao_dich_cong_ty
    id1 = ghi_giao_dich_cong_ty("chi", 300_000, "taxi")
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch(f"/api/cong-ty/giao-dich/{id1}", json={"so_tien": -5000})
        assert resp.status_code == 400


def test_api_sua_giao_dich_cong_ty_mo_ta_rong_tra_ve_400():
    from app.storage import ghi_giao_dich_cong_ty
    id1 = ghi_giao_dich_cong_ty("chi", 300_000, "taxi")
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch(f"/api/cong-ty/giao-dich/{id1}", json={"mo_ta": "   "})
        assert resp.status_code == 400


def test_api_sua_giao_dich_cong_ty_mo_ta_qua_dai_tra_ve_400():
    from app.storage import ghi_giao_dich_cong_ty
    id1 = ghi_giao_dich_cong_ty("chi", 300_000, "taxi")
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch(f"/api/cong-ty/giao-dich/{id1}", json={"mo_ta": "a" * 501})
        assert resp.status_code == 400


def test_api_sua_giao_dich_cong_ty_da_khoa_tra_ve_400():
    from app.storage import ghi_giao_dich_cong_ty
    from app.tools import giai_chi_cong_ty
    id1 = ghi_giao_dich_cong_ty("chi", 300_000, "taxi")
    giai_chi_cong_ty()
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch(f"/api/cong-ty/giao-dich/{id1}", json={"so_tien": 400_000})
        assert resp.status_code == 400
        assert "khoá" in resp.json()["loi"]


def test_api_xoa_giao_dich_cong_ty_can_dang_nhap():
    with TestClient(_tao_app_test()) as client:
        resp = client.delete("/api/cong-ty/giao-dich/1")
        assert resp.status_code == 401


def test_api_xoa_giao_dich_cong_ty_thanh_cong():
    from app.storage import ghi_giao_dich_cong_ty
    id1 = ghi_giao_dich_cong_ty("chi", 300_000, "taxi")
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.delete(f"/api/cong-ty/giao-dich/{id1}")
        assert resp.status_code == 200
        resp2 = client.get("/api/cong-ty")
        assert resp2.json()["giao_dich_dang_mo"] == []


def test_api_xoa_giao_dich_cong_ty_id_khong_ton_tai():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.delete("/api/cong-ty/giao-dich/999999")
        assert resp.status_code == 404


def test_api_xoa_giao_dich_cong_ty_da_khoa_tra_ve_400():
    from app.storage import ghi_giao_dich_cong_ty
    from app.tools import giai_chi_cong_ty
    id1 = ghi_giao_dich_cong_ty("chi", 300_000, "taxi")
    giai_chi_cong_ty()
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.delete(f"/api/cong-ty/giao-dich/{id1}")
        assert resp.status_code == 400


def test_api_giai_chi_cong_ty_can_dang_nhap():
    with TestClient(_tao_app_test()) as client:
        resp = client.post("/api/cong-ty/giai-chi")
        assert resp.status_code == 401


def test_api_giai_chi_cong_ty_thanh_cong():
    from app.storage import ghi_giao_dich_cong_ty
    ghi_giao_dich_cong_ty("tam_ung", 5_000_000, "di cong tac")
    ghi_giao_dich_cong_ty("chi", 300_000, "taxi")
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/api/cong-ty/giai-chi")
        assert resp.status_code == 200
        data = resp.json()
        assert data["da_giai_chi"] is True
        assert data["so_du"] == 4_700_000
        assert "duong_dan_pdf" in data


def test_api_giai_chi_cong_ty_khong_co_giao_dich_tra_ve_400():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/api/cong-ty/giai-chi")
        assert resp.status_code == 400


def test_trang_pdf_giai_chi_can_dang_nhap():
    with TestClient(_tao_app_test()) as client:
        resp = client.get("/ui/tam-ung/1/pdf")
        assert resp.status_code == 401


def test_trang_pdf_giai_chi_khong_ton_tai_tra_ve_404():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.get("/ui/tam-ung/999999/pdf")
        assert resp.status_code == 404


def test_trang_pdf_giai_chi_id_malformed_tra_ve_400():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.get("/ui/tam-ung/abc/pdf")
        assert resp.status_code == 400


def _than_ham(trang, dau_ham):
    idx = trang.index(dau_ham)
    return trang[idx:trang.index("\n}", idx)]


def test_thao_tac_giao_dich_tra_dung_bang_theo_loai():
    """I4 (Tính năng C) giữ ở /ui mới: id các bảng chi_tieu / thu_nhap_them /
    chi_phi_dac_biet / cong_ty_giao_dich tự tăng ĐỘC LẬP, có thể trùng số --
    mỗi dòng mang data-loai và timGiaoDich() tra đúng mảng của loại đó, không
    querySelector theo data-id trần (từng chọn nhầm dòng)."""
    from app.web import _TRANG_UI
    for loai in ("chi", "thu", "dac-biet", "cong-ty"):
        assert f'data-loai="{loai}"' in _TRANG_UI
    than_ham = _than_ham(_TRANG_UI, "function timGiaoDich")
    for mang in ("S.lichSu.chi", "S.lichSu.thu", "S.lichSu.dacBiet", "giao_dich_dang_mo"):
        assert mang in than_ham
    assert not re.search(r"querySelector\(`[^`]*\[data-id=", _TRANG_UI)


def test_trang_pdf_giai_chi_thanh_cong():
    from app.storage import ghi_giao_dich_cong_ty
    ghi_giao_dich_cong_ty("tam_ung", 5_000_000, "di cong tac")
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp_giai_chi = client.post("/api/cong-ty/giai-chi")
        giai_chi_id = resp_giai_chi.json()["id"]
        resp = client.get(f"/ui/tam-ung/{giai_chi_id}/pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"


def test_trang_pdf_giai_chi_tu_sinh_lai_khi_file_bi_mat():
    """I1: file PDF co the bi mat (thu muc data/tam_ung_pdf/ khong duoc
    backup, gitignored) nhung ban ghi giai_chi_cong_ty van con trong DB --
    truy cap route phai tu sinh lai PDF thay vi 404 vinh vien."""
    from app.storage import ghi_giao_dich_cong_ty
    from app import pdf_cong_ty
    ghi_giao_dich_cong_ty("tam_ung", 5_000_000, "di cong tac")
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        giai_chi_id = client.post("/api/cong-ty/giai-chi").json()["id"]
        duong_dan = pdf_cong_ty.duong_dan_pdf(giai_chi_id)
        assert duong_dan.exists()
        duong_dan.unlink()
        assert not duong_dan.exists()

        resp = client.get(f"/ui/tam-ung/{giai_chi_id}/pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert duong_dan.exists()


def test_trang_pdf_giai_chi_hien_thi_inline_khong_ep_tai_ve():
    """M2: FileResponse voi filename= ep trinh duyet tai file ve (Content-
    Disposition: attachment), mau thuan voi docstring cua tool MCP
    (giai_chi_cong_ty) noi nguoi dung "mo bang trinh duyet". Bo filename= de
    xem inline."""
    from app.storage import ghi_giao_dich_cong_ty
    ghi_giao_dich_cong_ty("tam_ung", 5_000_000, "di cong tac")
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        giai_chi_id = client.post("/api/cong-ty/giai-chi").json()["id"]
        resp = client.get(f"/ui/tam-ung/{giai_chi_id}/pdf")
        assert resp.status_code == 200
        content_disposition = resp.headers.get("content-disposition", "")
        assert "attachment" not in content_disposition.lower()


def test_api_chi_phi_dac_biet_can_dang_nhap():
    with TestClient(_tao_app_test()) as client:
        resp = client.get("/api/chi-phi-dac-biet")
        assert resp.status_code == 401


def test_api_chi_phi_dac_biet_tra_ve_dung_du_lieu():
    from app.storage import ghi_chi_phi_dac_biet
    from app.jars import thang_hien_tai
    id1 = ghi_chi_phi_dac_biet(thang_hien_tai(), "hoc phi", 4_000_000)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.get(f"/api/chi-phi-dac-biet?thang={thang_hien_tai()}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tong_tien"] == 4_000_000
        assert data["danh_sach"][0]["id"] == id1


def test_api_chi_phi_dac_biet_thang_malformed_tra_ve_400():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.get("/api/chi-phi-dac-biet?thang=abc")
        assert resp.status_code == 400


def test_api_sua_chi_phi_dac_biet_can_dang_nhap():
    with TestClient(_tao_app_test()) as client:
        resp = client.patch("/api/chi-phi-dac-biet/1", json={"so_tien": 1000})
        assert resp.status_code == 401


def test_api_sua_chi_phi_dac_biet_thanh_cong():
    from app.storage import ghi_chi_phi_dac_biet
    from app.jars import thang_hien_tai
    id1 = ghi_chi_phi_dac_biet(thang_hien_tai(), "hoc phi", 4_000_000)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch(f"/api/chi-phi-dac-biet/{id1}", json={"so_tien": 4_500_000})
        assert resp.status_code == 200
        resp2 = client.get(f"/api/chi-phi-dac-biet?thang={thang_hien_tai()}")
        assert resp2.json()["danh_sach"][0]["so_tien"] == 4_500_000


def test_api_sua_chi_phi_dac_biet_id_khong_ton_tai():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch("/api/chi-phi-dac-biet/999999", json={"so_tien": 1000})
        assert resp.status_code == 404


def test_api_sua_chi_phi_dac_biet_so_tien_am_tra_ve_400():
    from app.storage import ghi_chi_phi_dac_biet
    from app.jars import thang_hien_tai
    id1 = ghi_chi_phi_dac_biet(thang_hien_tai(), "hoc phi", 4_000_000)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch(f"/api/chi-phi-dac-biet/{id1}", json={"so_tien": -1000})
        assert resp.status_code == 400


def test_api_sua_chi_phi_dac_biet_mo_ta_rong_tra_ve_400():
    from app.storage import ghi_chi_phi_dac_biet
    from app.jars import thang_hien_tai
    id1 = ghi_chi_phi_dac_biet(thang_hien_tai(), "hoc phi", 4_000_000)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch(f"/api/chi-phi-dac-biet/{id1}", json={"mo_ta": "   "})
        assert resp.status_code == 400


def test_api_sua_chi_phi_dac_biet_body_rong_tra_ve_400():
    from app.storage import ghi_chi_phi_dac_biet
    from app.jars import thang_hien_tai
    id1 = ghi_chi_phi_dac_biet(thang_hien_tai(), "hoc phi", 4_000_000)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.patch(f"/api/chi-phi-dac-biet/{id1}", json={})
        assert resp.status_code == 400


def test_api_xoa_chi_phi_dac_biet_can_dang_nhap():
    with TestClient(_tao_app_test()) as client:
        resp = client.delete("/api/chi-phi-dac-biet/1")
        assert resp.status_code == 401


def test_api_xoa_chi_phi_dac_biet_thanh_cong():
    from app.storage import ghi_chi_phi_dac_biet
    from app.jars import thang_hien_tai
    id1 = ghi_chi_phi_dac_biet(thang_hien_tai(), "hoc phi", 4_000_000)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.delete(f"/api/chi-phi-dac-biet/{id1}")
        assert resp.status_code == 200
        resp2 = client.get(f"/api/chi-phi-dac-biet?thang={thang_hien_tai()}")
        assert resp2.json()["danh_sach"] == []


def test_api_xoa_chi_phi_dac_biet_id_khong_ton_tai():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.delete("/api/chi-phi-dac-biet/999999")
        assert resp.status_code == 404


def test_trang_chinh_hien_thi_chi_phi_dac_biet():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.get("/ui")
        assert resp.status_code == 200
        assert "chi-phi-dac-biet" in resp.text


def test_giao_dien_moi_gan_su_kien_qua_data_hanh_dong_khong_onclick_noi_tuyen():
    """/ui mới gắn thao tác qua data-hanh-dong + 1 bộ lắng nghe click -- không
    còn onclick="...(${id})" chèn id/chuỗi vào thuộc tính sự kiện."""
    from app.web import _TRANG_UI
    assert "onclick=" not in _TRANG_UI.lower()
    assert "document.addEventListener('click'" in _TRANG_UI
    assert "const HANH_DONG = {" in _TRANG_UI


def test_api_cau_hinh_luu_thanh_cong_kem_ngay_bat_dau_chu_ky():
    from app.jars import doc_cau_hinh
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/api/cau-hinh", json={
            "thu_nhap_thuc_linh_thang": 12_000_000,
            "hu": [{"ma": "thiet_yeu", "ty_le_phan_tram": 60.0},
                   {"ma": "huong_thu", "ty_le_phan_tram": 40.0}],
            "ngay_bat_dau_chu_ky": 15,
        })
        assert resp.status_code == 200
        assert doc_cau_hinh()["ngay_bat_dau_chu_ky"] == 15


def test_api_cau_hinh_ngay_bat_dau_chu_ky_thieu_tra_ve_400():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/api/cau-hinh", json={
            "thu_nhap_thuc_linh_thang": 10_000_000,
            "hu": [{"ma": "thiet_yeu", "ty_le_phan_tram": 50.0},
                   {"ma": "huong_thu", "ty_le_phan_tram": 50.0}],
        })
        assert resp.status_code == 400


def test_api_cau_hinh_ngay_bat_dau_chu_ky_ngoai_khoang_tra_ve_400():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        for gia_tri in (0, 29, -1, 100):
            resp = client.post("/api/cau-hinh", json={
                "thu_nhap_thuc_linh_thang": 10_000_000,
                "hu": [{"ma": "thiet_yeu", "ty_le_phan_tram": 50.0},
                       {"ma": "huong_thu", "ty_le_phan_tram": 50.0}],
                "ngay_bat_dau_chu_ky": gia_tri,
            })
            assert resp.status_code == 400, f"gia_tri={gia_tri} phai bi tu choi"


def test_api_cau_hinh_ngay_bat_dau_chu_ky_khong_phai_int_tra_ve_400():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        for gia_tri in (5.5, "15", True, None, [15]):
            resp = client.post("/api/cau-hinh", json={
                "thu_nhap_thuc_linh_thang": 10_000_000,
                "hu": [{"ma": "thiet_yeu", "ty_le_phan_tram": 50.0},
                       {"ma": "huong_thu", "ty_le_phan_tram": 50.0}],
                "ngay_bat_dau_chu_ky": gia_tri,
            })
            assert resp.status_code == 400, f"gia_tri={gia_tri!r} phai bi tu choi"


def test_api_ngan_sach_tra_ve_ngay_bat_dau_chu_ky():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.get("/api/ngan-sach")
        assert resp.status_code == 200
        assert resp.json()["ngay_bat_dau_chu_ky"] == 1


def test_trang_chinh_hien_thi_o_nhap_chu_ky():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.get("/ui")
        assert resp.status_code == 200
        assert 'id="in-ngay-chu-ky"' in resp.text
        assert "Ngày bắt đầu kỳ lương" in resp.text
        assert 'data-hanh-dong="buoc-ngay"' in resp.text


def test_luu_cau_hinh_lam_moi_lich_su_sau_khi_doi_ngay_chu_ky():
    """M1 (review toàn nhánh Tính năng A): đổi ngày bắt đầu chu kỳ có thể đổi
    nhãn kỳ hiện tại -- sau khi lưu phải bỏ kỳ đang xem ở Lịch sử rồi tải lại
    TẤT CẢ (taiTatCa gán lại kỳ hiện tại mới), không giữ dữ liệu kỳ cũ."""
    from app.web import _TRANG_UI
    than_ham = _than_ham(_TRANG_UI, "async function luuCauHinh")
    assert than_ham.index("S.lichSu.thang = null;") < than_ham.index("await taiTatCa();")
    tai_tat_ca = _than_ham(_TRANG_UI, "async function taiTatCa")
    assert "if (!S.lichSu.thang) S.lichSu.thang = S.nganSach.thang;" in tai_tat_ca
    assert "taiLichSu()" in tai_tat_ca


def test_mcp_endpoint_chap_nhan_host_header_lan():
    """C2A gọi vào bằng IP LAN của máy chủ (vd http://10.0.0.5:8801/mcp),
    không phải 127.0.0.1/localhost. FastMCP mặc định host="127.0.0.1" khi
    không truyền tham số -- tự bật DNS-rebinding protection của mcp SDK
    (transport_security.py) với allow-list CHỈ gồm 127.0.0.1/localhost/::1,
    chặn mọi Host header LAN khác bằng 421 "Invalid Host header". Bug này
    khiến C2A không bao giờ gọi được tool nào (agent tự bịa câu trả lời thay
    vì gọi tool thật) mà không có lỗi rõ ràng nào cho người dùng thấy."""
    with TestClient(_tao_app_test()) as client:
        resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2026-07-28",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            },
            headers={
                "Host": "10.0.0.5:8801",
                "Accept": "application/json, text/event-stream",
            },
        )
        assert resp.status_code != 421, (
            f"Bi tu choi boi DNS-rebinding protection: {resp.text!r} -- "
            "thieu host=\"0.0.0.0\" khi tao FastMCP"
        )


def test_api_hoi_ai_phan_tich_can_dang_nhap():
    with TestClient(_tao_app_test()) as client:
        resp = client.post("/api/de-xuat/hoi-ai")
        assert resp.status_code == 401


def test_api_hoi_ai_phan_tich_thanh_cong(monkeypatch):
    from app import web

    async def _gia_lap_hoi_ai(prompt):
        assert "Thiết Yếu" in prompt
        return "Phân tích giả lập: hũ Thiết Yếu quan trọng nhất."

    monkeypatch.setattr(web, "hoi_ai_phan_tich", _gia_lap_hoi_ai)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/api/de-xuat/hoi-ai")
        assert resp.status_code == 200
        assert resp.json()["phan_tich"] == "Phân tích giả lập: hũ Thiết Yếu quan trọng nhất."


def test_api_hoi_ai_phan_tich_loi_ha_tang_tra_ve_502(monkeypatch):
    from app import web

    async def _gia_lap_loi(prompt):
        raise RuntimeError("C2A khong phan hoi")

    monkeypatch.setattr(web, "hoi_ai_phan_tich", _gia_lap_loi)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/api/de-xuat/hoi-ai")
        assert resp.status_code == 502
        assert "loi" in resp.json()


def test_api_hoi_ai_phan_tich_loi_khong_lo_chi_tiet_noi_bo(monkeypatch):
    """Fix 5 (review): message lỗi trả về CLIENT không được chứa text lỗi gốc
    (có thể rò rỉ C2A_BASE_URL nội bộ qua httpx.HTTPStatusError, hoặc
    KeyError repr) -- phải là thông báo cố định chung chung, lỗi thật chỉ log
    lại phía server."""
    from app import web

    async def _gia_lap_loi(prompt):
        raise RuntimeError("http://10.0.0.5:3030/v1/chat/completions tra ve 500")

    monkeypatch.setattr(web, "hoi_ai_phan_tich", _gia_lap_loi)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/api/de-xuat/hoi-ai")
        assert resp.status_code == 502
        data = resp.json()
        assert data["loi"] == "Không gọi được AI, thử lại sau."
        assert "10.0.0.5" not in data["loi"]


def test_trang_chinh_hien_thi_khu_vuc_de_xuat_phan_bo():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.get("/ui")
        assert resp.status_code == 200
        assert 'id="de-xuat-phan-bo"' in resp.text
        assert 'id="btn-hoi-ai"' in resp.text
        assert 'id="ket-qua-hoi-ai"' in resp.text


def test_ap_dung_de_xuat_chi_dien_form_khong_tu_luu():
    """An toàn (QĐ #2 spec): nút Áp dụng đề xuất chỉ điền input có sẵn,
    KHÔNG tự gọi API/lưu -- user vẫn phải tự bấm "Lưu cấu hình"."""
    from app.web import _TRANG_UI
    idx_ham = _TRANG_UI.index("function apDungDeXuat")
    idx_ket_thuc = _TRANG_UI.index("\n}", idx_ham)
    than_ham = _TRANG_UI[idx_ham:idx_ket_thuc]
    assert "goiApi" not in than_ham
    assert "fetch(" not in than_ham
    # Fix 8 (review): chặn cả đường vòng -- gọi 1 helper đặt tên khác mà bản
    # thân helper đó mới tự lưu, thay vì literally chứa goiApi/fetch(.
    assert "luuCauHinh" not in than_ham
    assert "capNhatTongTyLe()" in than_ham


def test_ve_de_xuat_phan_bo_co_chu_thich_co_so_thu_nhap_khac_loi_khuyen_xu_huong():
    """Fix 2 (review): 2 con số "% thu nhập" hiện cạnh nhau trên /ui dùng 2 cơ
    sở KHÁC nhau (thuật toán: tổng thu nhập hiệu quả; lời khuyên xu hướng cũ:
    lương cố định -- xem app/tools.py::de_xuat_dieu_chinh, KHÔNG đổi) mà
    không nói rõ -- phải có 1 dòng chú thích ngắn trong nhánh du_lieu_du."""
    from app.web import _TRANG_UI
    idx_ham = _TRANG_UI.index("function veDeXuatPhanBo")
    idx_ket_thuc = _TRANG_UI.index("\n}", idx_ham)
    than_ham = _TRANG_UI[idx_ham:idx_ket_thuc]
    assert "thu nhập hiệu quả" in than_ham


def test_de_xuat_phan_bo_co_tieu_de_va_nut_dien_bang():
    from app.web import _TRANG_UI
    assert "Đề xuất theo xu hướng 3 kỳ" in _TRANG_UI
    than_ham = _than_ham(_TRANG_UI, "function veDeXuatPhanBo")
    assert "if (!phanBo || !phanBo.du_lieu_du)" in than_ham
    assert 'data-hanh-dong="ap-dung-de-xuat"' in than_ham
    assert "escHtml(tenNgan(d.ma, d.ten))" in than_ham


def test_dien_ty_le_ai_chi_dien_bang_khong_tu_luu():
    """Như "Áp dụng đề xuất": nút "Điền vào bảng phân bổ" của thẻ AI chỉ điền,
    người dùng vẫn phải tự bấm Lưu cấu hình."""
    from app.web import _TRANG_UI
    than_ham = _than_ham(_TRANG_UI, "function apDungTyLeAi")
    assert "goiApi" not in than_ham and "fetch(" not in than_ham and "luuCauHinh" not in than_ham
    assert "capNhatTongTyLe()" in than_ham


def test_tai_goi_y_guard_thieu_phan_bo_de_xuat():
    """Fix 7 (review): taiGoiY() trước đây gọi
    veDeXuatPhanBo(data.phan_bo_de_xuat) vô điều kiện -- nếu field này thiếu,
    throw giữa chừng, để trang ở trạng thái nửa vời kèm banner lỗi chung
    chung. Phải guard bằng if trước khi gọi."""
    from app.web import _TRANG_UI
    idx_ham = _TRANG_UI.index("async function taiGoiY")
    idx_ket_thuc = _TRANG_UI.index("\n}", idx_ham)
    than_ham = _TRANG_UI[idx_ham:idx_ket_thuc]
    assert "if (data.phan_bo_de_xuat)" in than_ham


def test_api_tach_giao_dich_can_dang_nhap():
    with TestClient(_tao_app_test()) as client:
        resp = client.post("/api/chi-tieu/1/tach", json={"danh_sach": []})
        assert resp.status_code == 401


def test_api_tach_giao_dich_thanh_cong():
    from app import storage
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        id_goc = storage.ghi_chi_tieu("thiet_yeu", 100_000, "sinh hoat")
        resp = client.post(f"/api/chi-tieu/{id_goc}/tach", json={"danh_sach": [
            {"hu_ma": "thiet_yeu", "so_tien": 60_000, "ghi_chu": "an uong"},
            {"hu_ma": "huong_thu", "so_tien": 40_000, "ghi_chu": "giai tri"},
        ]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["da_tach"] is True
        assert len(data["id_moi"]) == 2


def test_api_tach_giao_dich_id_khong_ton_tai_tra_ve_400():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/api/chi-tieu/999999/tach", json={"danh_sach": [
            {"hu_ma": "thiet_yeu", "so_tien": 50_000, "ghi_chu": ""},
            {"hu_ma": "huong_thu", "so_tien": 50_000, "ghi_chu": ""},
        ]})
        assert resp.status_code == 400


def test_api_tach_giao_dich_body_thieu_danh_sach_tra_ve_400():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/api/chi-tieu/1/tach", json={})
        assert resp.status_code == 400


def test_trang_chinh_hien_thi_nut_tach_giao_dich():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.get("/ui")
        assert resp.status_code == 200
        assert 'data-hanh-dong="tach"' in resp.text
        assert "Tách thành nhiều hũ" in resp.text
        assert "'tach': el => moTach(Number(el.dataset.id))" in resp.text


def test_luu_tach_goi_dung_route_va_reload_lich_su_ngan_sach():
    from app.web import _TRANG_UI
    than_ham = _than_ham(_TRANG_UI, "async function luuTach")
    assert "/api/chi-tieu/${id}/tach" in than_ham
    assert "await taiTatCa();" in than_ham
    tai_tat_ca = _than_ham(_TRANG_UI, "async function taiTatCa")
    assert "taiNganSach()" in tai_tat_ca and "taiLichSu()" in tai_tat_ca


def test_cap_nhat_tong_tach_disable_nut_khi_khong_hop_le():
    from app.web import _TRANG_UI
    idx_ham = _TRANG_UI.index("function capNhatTongTach")
    idx_ket_thuc = _TRANG_UI.index("\n}", idx_ham)
    than_ham = _TRANG_UI[idx_ham:idx_ket_thuc]
    assert ".disabled = !(hopLe && khopTong)" in than_ham


def test_xoa_dong_tach_exists_and_calls_cap_nhat():
    from app.web import _TRANG_UI
    idx_ham = _TRANG_UI.index("function xoaDongTach")
    idx_ket_thuc = _TRANG_UI.index("\n}", idx_ham)
    than_ham = _TRANG_UI[idx_ham:idx_ket_thuc]
    assert "btn.closest('.tach-dong')" in than_ham
    assert "capNhatTongTach(id)" in than_ham
    assert "tachdongs.length <= 2" in than_ham


def test_api_ngan_sach_tra_ve_tong_con_chi_duoc_va_tu_bu():
    from app.tools import ghi_chi_tieu
    ghi_chi_tieu("huong_thu", 1_300_000)  # riêng 1tr -> bù 300k từ thiet_yeu
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        data = client.get("/api/ngan-sach").json()
        assert data["tong_da_chi"] == 1_300_000
        assert data["tong_con_lai"] == 4_700_000
        assert data["so_ngay_con_lai"] >= 1
        assert "ty_le_tong_da_dung_phan_tram" in data
        assert "canh_bao_tong" in data
        huong_thu = next(h for h in data["hu"] if h["ma"] == "huong_thu")
        thiet_yeu = next(h for h in data["hu"] if h["ma"] == "thiet_yeu")
        assert huong_thu["duoc_bu"] == 300_000
        assert thiet_yeu["da_nhuong"] == 300_000


def test_trang_chinh_co_o_con_chi_duoc_va_dai_canh_bao_vuot_tong():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.get("/ui")
        assert resp.status_code == 200
        assert 'id="o-con-chi-duoc"' in resp.text
        assert 'id="tk-con-chi-duoc"' in resp.text
        assert 'id="canh-bao-vuot-tong"' in resp.text
        assert "function veConChiDuoc" in resp.text
        assert "đã nhường" in resp.text


def test_ve_danh_sach_hu_khong_to_do_hu_chua_chi_da_nhuong_het():
    """F5 (review Recommendation 6) giữ ở /ui mới: hũ chưa chi đồng nào
    (h.da_chi === 0) mà đã nhường hết (con_lai <= 0) KHÔNG được tô đỏ -- đỏ
    chỉ khi chi quá hạn mức RIÊNG (trước tự bù)."""
    from app.web import _TRANG_UI
    than_ham = _than_ham(_TRANG_UI, "function veDanhSachHu")
    assert "const vuot = h.da_chi > hanMuc;" in than_ham
    assert "const hanMuc = h.han_muc_truoc_bu;" in than_ham
    assert "h.da_chi === 0" in than_ham and "đã nhường hết cho hũ khác" in than_ham


# --- Giao diện sáng/tối + chữ co giãn (spec 2026-09-23-giao-dien-sang-toi) ---

MAU_HEX = re.compile(r"(?<![\w-])#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})(?![\w-])")


def _bo_khoi_theme(trang):
    from app import giao_dien
    assert trang.count(giao_dien.THE_HEAD) == 1
    return trang.replace(giao_dien.THE_HEAD, "")


def test_trang_ui_va_login_co_theme_trong_head():
    from app import giao_dien
    with TestClient(_tao_app_test()) as client:
        login = client.get("/ui/login").text
        assert login.index(giao_dien.THE_HEAD) < login.index("</head>")
        assert 'id="nut-che-do"' not in login
        _dang_nhap(client)
        ui = client.get("/ui").text
        assert ui.index(giao_dien.THE_HEAD) < ui.index("</head>")
        assert 'id="nut-che-do"' in ui


def test_regex_mau_hex_khong_bat_nham_selector_id():
    assert MAU_HEX.findall("#cac-slider #de-xuat #fff #A1B2C3 &#39;") == ["#fff", "#A1B2C3"]


def test_template_khong_con_ma_mau_hex_ngoai_theme():
    from app.web import _TRANG_LOGIN, _TRANG_UI
    for trang in (_TRANG_UI, _TRANG_LOGIN):
        assert MAU_HEX.findall(_bo_khoi_theme(trang)) == []


def test_moi_bien_css_template_dung_deu_co_trong_theme():
    from app import giao_dien
    from app.web import _TRANG_LOGIN, _TRANG_UI
    css = giao_dien.css_theme()
    for trang in (_TRANG_UI, _TRANG_LOGIN):
        dung = set(re.findall(r"var\((--(?:mau|co-chu)-[a-z0-9-]+)", _bo_khoi_theme(trang)))
        assert dung
        assert {bien for bien in dung if f"{bien}:" not in css} == set()


def test_template_khong_con_co_chu_px_cung():
    from app.web import _TRANG_LOGIN, _TRANG_UI
    for trang in (_TRANG_UI, _TRANG_LOGIN):
        assert re.findall(r"font-size:\s*[\d.]+px", _bo_khoi_theme(trang)) == []


def test_template_khong_con_marker_chua_thay():
    from app import giao_dien
    from app.web import _TRANG_LOGIN, _TRANG_UI
    assert "__THEME_HEAD__" not in _TRANG_UI and "__THEME_HEAD__" not in _TRANG_LOGIN
    assert "__KHOA_LUU_CHE_DO__" not in _TRANG_UI
    assert f"const KHOA_CHE_DO_MAU = '{giao_dien.KHOA_LUU_CHE_DO}';" in _TRANG_UI


def test_nut_che_do_xoay_vong_tu_dong_sang_toi():
    from app.web import _TRANG_UI
    assert "const CHE_DO_KE_TIEP = {auto: 'light', light: 'dark', dark: 'auto'};" in _TRANG_UI
    idx_ham = _TRANG_UI.index("function apDungCheDoMau")
    than_ham = _TRANG_UI[idx_ham:_TRANG_UI.index("\n}", idx_ham)]
    assert "goc.removeAttribute('data-theme')" in than_ham
    assert "localStorage.setItem(KHOA_CHE_DO_MAU, cheDo)" in than_ham
    assert "localStorage.removeItem(KHOA_CHE_DO_MAU)" in than_ham
    assert "try {" in than_ham
    assert "aria-label" in than_ham
    assert "apDungCheDoMau(docCheDoMau());" in _TRANG_UI
    assert "addEventListener('click', doiCheDoMau)" in _TRANG_UI


def test_o_sua_tach_giao_dich_khong_con_rong_co_dinh():
    from app.web import _TRANG_UI
    assert 'style="width:' not in _TRANG_UI
    assert "style.cssText" not in _TRANG_UI


def test_thanh_truot_ty_le_da_thay_bang_nut_buoc_va_o_go():
    """Tồn đọng #2: thanh trượt % hũ trên điện thoại dễ kéo nhầm (từng thấy tổng
    240%) -- /ui mới dùng nút −/+ bước 0,5% và ô % gõ được."""
    from app.web import _TRANG_UI
    assert 'type="range"' not in _TRANG_UI and "type=range" not in _TRANG_UI
    assert 'data-hanh-dong="buoc-pt"' in _TRANG_UI and 'data-gt="-0.5"' in _TRANG_UI
    assert 'class="o-pt" type="text" inputmode="decimal"' in _TRANG_UI


def test_donut_va_legend_dung_mau_hu_tu_bien_css():
    from app.web import _TRANG_UI
    assert "const MAU " not in _TRANG_UI
    assert "function mauHu" in _TRANG_UI
    idx_ham = _TRANG_UI.index("function veDonut")
    than_ham = _TRANG_UI[idx_ham:_TRANG_UI.index("\n}", idx_ham)]
    assert "mauHu(h.ma)" in than_ham
    assert 'class="cham"' in than_ham


def test_script_trang_ui_dung_cu_phap_node(tmp_path):
    import shutil
    import subprocess
    from app.web import _TRANG_UI
    node = shutil.which("node")
    if node is None:
        pytest.skip("máy này không có node")
    cac_script = re.findall(r"<script>(.*?)</script>", _TRANG_UI, re.S)
    assert len(cac_script) == 2  # script khởi tạo theme trong <head> + script chính
    for i, js in enumerate(cac_script):
        tep = tmp_path / f"script_{i}.js"
        tep.write_text(js, encoding="utf-8")
        ket_qua = subprocess.run([node, "--check", str(tep)], capture_output=True, text=True)
        assert ket_qua.returncode == 0, ket_qua.stderr


def test_api_hoi_ai_phan_tich_markdown_lui_ve_html(monkeypatch):
    """AI bỏ qua yêu cầu JSON và trả markdown -> không có phan_tich_cau_truc,
    /ui hiện phan_tich_html như trước."""
    from app import web
    from app.markdown_an_toan import markdown_sang_html

    tra_loi = "### Nhận xét\n- Hũ **Thiết Yếu** hợp lý\n- Giữ 50%"

    async def _gia_lap_hoi_ai(prompt):
        return tra_loi

    monkeypatch.setattr(web, "hoi_ai_phan_tich", _gia_lap_hoi_ai)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        data = client.post("/api/de-xuat/hoi-ai").json()
    assert data["phan_tich"] == tra_loi
    assert data["phan_tich_cau_truc"] is None
    assert data["phan_tich_html"] == markdown_sang_html(tra_loi)
    assert data["phan_tich_html"].startswith("<h3>Nhận xét</h3>")


def test_api_hoi_ai_phan_tich_json_tra_cau_truc_va_prompt_xin_json(monkeypatch):
    from app import web
    from app.jars import thang_hien_tai

    tra_loi = json.dumps({
        "tom_tat": "Chi <b>ổn</b>.",
        "tung_hu": [{"ma": "thiet_yeu", "danh_gia": "Ổn", "nhan_xet": "Còn nhiều."}],
        "nen_lam": ["Giữ nhịp chi."],
        "ty_le_goi_y": {"thiet_yeu": 50, "huong_thu": 50},
    }, ensure_ascii=False)
    prompt_nhan = {}

    async def _gia_lap_hoi_ai(prompt):
        prompt_nhan["prompt"] = prompt
        return "```json\n" + tra_loi + "\n```"

    monkeypatch.setattr(web, "hoi_ai_phan_tich", _gia_lap_hoi_ai)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        client.post("/api/chi-tieu", json={"hu_ma": "thiet_yeu", "so_tien": 123_000})
        data = client.post("/api/de-xuat/hoi-ai").json()
    assert data["phan_tich_cau_truc"] == {
        "tom_tat": "Chi <b>ổn</b>.",
        "tung_hu": [{"ma": "thiet_yeu", "danh_gia": "Ổn", "nhan_xet": "Còn nhiều."}],
        "nen_lam": ["Giữ nhịp chi."],
        "ty_le_goi_y": {"thiet_yeu": 50.0, "huong_thu": 50.0},
    }
    assert "phan_tich_html" not in data
    assert data["thang"] == thang_hien_tai()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", data["thoi_gian"])
    prompt = prompt_nhan["prompt"]
    assert "Chỉ trả lời bằng đúng một object JSON" in prompt
    assert '"ty_le_goi_y"' in prompt and '"tung_hu"' in prompt
    # trạng thái thật từng hũ nằm trong prompt: mã, đã chi, hạn mức
    assert "thiet_yeu" in prompt and "huong_thu" in prompt
    assert "123.000đ" in prompt
    assert "Còn chi được" in prompt


# Bản chép _BRANCH_TEXT_KEYWORDS của C2A (services/protocol/openai_v1_chat_complete.py,
# đọc 23/09/2026): model "auto" mà câu hỏi (bỏ dấu) chứa 1 cụm này thì C2A tự
# đẩy sang nhánh vẽ ảnh/video/nhạc/code. c2a_client đã gửi x_allowed_groups=[]
# để chặn, test này là lớp phòng thứ 2 cho phần chữ CỐ ĐỊNH của prompt.
_TU_KHOA_NHANH_C2A = (
    "ve anh", "tao anh", "ve hinh", "tao hinh", "ve cho", "ve giup", "ve mot", "ve 1 ", "ve lai",
    "tao logo", "ve logo", "tao poster", "tao icon", "tao hinh anh", "generate image", "draw a ",
    "tao video", "lam video", "tao clip", "lam clip", "tao doan video", "tao 1 video", "tao mot video",
    "generate video", "tao nhac", "tao bai hat", "tao ban nhac", "sang tac nhac", "sang tac bai hat",
    "viet bai hat", "lam bai hat", "lam nhac", "compose music", "make a song", "viet code", "sua code",
    "viet chuong trinh", "viet ham", "viet script", "viet doan code", "code giup", "sua loi code",
    "fix bug", "fix code", "debug", "refactor", "lap trinh", "viet function", "toi uu code",
    "review code", "kiem tra code", "sua file", "viet file", "viet ung dung", "write code",
)


def test_prompt_phan_tich_ai_khong_dinh_tu_khoa_nhanh_c2a(monkeypatch):
    import unicodedata
    from app import web
    nhan = {}

    async def _gia_lap_hoi_ai(prompt):
        nhan["prompt"] = prompt
        return "x"

    monkeypatch.setattr(web, "hoi_ai_phan_tich", _gia_lap_hoi_ai)
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        client.post("/api/de-xuat/hoi-ai")
    bo_dau = "".join(c for c in unicodedata.normalize("NFKD", nhan["prompt"].lower()) if not unicodedata.combining(c))
    assert [k for k in _TU_KHOA_NHANH_C2A if k in bo_dau] == []


def test_hoi_ai_phan_tich_js_cau_truc_bang_textcontent_markdown_bang_html_server():
    from app.web import _TRANG_UI
    hoi = _than_ham(_TRANG_UI, "async function hoiAiPhanTich")
    assert "ketQuaEl.textContent = data.loi" in hoi   # lỗi luôn là textContent
    assert "localStorage.setItem(KHOA_PHAN_TICH_AI" in hoi and "try {" in hoi
    ve = _than_ham(_TRANG_UI, "function veKetQuaAi")
    assert "ketQuaEl.replaceChildren(dungTheAi(kq.phan_tich_cau_truc))" in ve
    assert "ketQuaEl.innerHTML = kq.phan_tich_html" in ve   # HTML an toàn do server sinh
    dung = _than_ham(_TRANG_UI, "function dungTheAi")
    assert "innerHTML" not in dung
    assert "taoPhanTu('div', 'tom-tat-ai', ct.tom_tat)" in dung
    # HTML duy nhất chèn trong thẻ AI là icon hũ dựng từ hằng số + mã đã lọc
    assert dung.count("insertAdjacentHTML") == 1 and "insertAdjacentHTML('afterbegin', iconHu(m.ma))" in dung


def test_trang_moi_co_du_5_man_nav_4_muc_va_nut_them():
    from app.web import _TRANG_UI
    for man in ("tong-quan", "them", "lich-su", "phan-bo", "cong-ty"):
        assert f'data-man="{man}"' in _TRANG_UI
    nav = _TRANG_UI[_TRANG_UI.index('<nav class="dieu-huong"'):_TRANG_UI.index("</nav>")]
    assert re.findall(r'href="#([a-z-]+)"', nav) == ["tong-quan", "lich-su", "phan-bo", "cong-ty"]
    assert '<a class="fab" href="#them"' in _TRANG_UI


def test_them_moi_khoan_chi_di_qua_cong_vuot_tong_cua_server():
    """Nút + không tự quyết vượt tổng: lần gửi đầu luôn xac_nhan_vuot_tong=false
    (tham số mặc định), server trả can_xac_nhan thì hỏi người dùng rồi mới gửi
    lại với true."""
    from app.web import _TRANG_UI
    than_ham = _than_ham(_TRANG_UI, "async function luuThem")
    assert "async function luuThem(xacNhanVuot = false)" in _TRANG_UI
    assert "'/api/chi-tieu'" in than_ham and "xac_nhan_vuot_tong: xacNhanVuot" in than_ham
    assert than_ham.index("if (data.can_xac_nhan)") < than_ham.index("await xacNhan(") < than_ham.index("luuThem(true)")
    assert "'luu-them': () => luuThem(false)" in _TRANG_UI


# ---- /ui mới: tạo mới từ /ui, sửa/xoá thu nhập thêm, thống kê kỳ ----
# (spec 2026-09-23-thiet-ke-lai-ui-design.md, mục "API mới/đổi")

def _dem_dong(bang: str) -> int:
    from app import storage
    with storage.db() as ket_noi:
        return ket_noi.execute(f"SELECT COUNT(*) FROM {bang}").fetchone()[0]


@pytest.mark.parametrize("method,url", [
    ("post", "/api/chi-tieu"), ("post", "/api/thu-nhap-them"), ("patch", "/api/thu-nhap-them/1"),
    ("delete", "/api/thu-nhap-them/1"), ("post", "/api/cong-ty/giao-dich"), ("get", "/api/thong-ke-ky"),
])
def test_api_moi_cua_ui_can_dang_nhap(method, url):
    with TestClient(_tao_app_test()) as client:
        kw = {"json": {}} if method in ("post", "patch") else {}
        assert getattr(client, method)(url, **kw).status_code == 401


def test_api_them_chi_tieu_ghi_voi_nguon_ui():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/api/chi-tieu", json={"hu_ma": "thiet_yeu", "so_tien": 50_000, "ghi_chu": "ăn trưa"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["da_ghi"] is True
        assert data["tong_con_lai"] == 6_000_000 - 50_000
    from app import storage
    with storage.db() as ket_noi:
        dong = ket_noi.execute("SELECT hu_ma, so_tien, ghi_chu, nguon FROM chi_tieu").fetchall()
    assert [tuple(d) for d in dong] == [("thiet_yeu", 50_000, "ăn trưa", "ui")]


@pytest.mark.parametrize("body", [
    {"hu_ma": "thiet_yeu", "so_tien": True},
    {"hu_ma": "thiet_yeu", "so_tien": 0},
    {"hu_ma": "thiet_yeu", "so_tien": -5},
    {"hu_ma": "thiet_yeu", "so_tien": 1.5},
    {"hu_ma": "thiet_yeu", "so_tien": "50000"},
    {"hu_ma": "thiet_yeu", "so_tien": 10**12 + 1},
    {"hu_ma": "khong_co", "so_tien": 50_000},
    {"hu_ma": 5, "so_tien": 50_000},
    {"hu_ma": "thiet_yeu", "so_tien": 50_000, "ghi_chu": 5},
    {"hu_ma": "thiet_yeu", "so_tien": 50_000, "xac_nhan_vuot_tong": "yes"},
    [],
])
def test_api_them_chi_tieu_du_lieu_sai_tra_400_khong_ghi(body):
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/api/chi-tieu", json=body)
        assert resp.status_code == 400
        assert "loi" in resp.json()
    assert _dem_dong("chi_tieu") == 0


def test_api_them_chi_tieu_vuot_tong_chua_ghi_cho_toi_khi_xac_nhan():
    """Cổng vượt tổng của server là nguồn duy nhất -- /ui chỉ hiện sheet xác
    nhận theo can_xac_nhan rồi gửi lại xac_nhan_vuot_tong=true."""
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        body = {"hu_ma": "thiet_yeu", "so_tien": 7_000_000, "ghi_chu": "sửa nhà"}
        lan_1 = client.post("/api/chi-tieu", json=body).json()
        assert lan_1["can_xac_nhan"] is True and lan_1["da_ghi"] is False
        assert "VƯỢT" in lan_1["canh_bao"]
        assert _dem_dong("chi_tieu") == 0
        lan_2 = client.post("/api/chi-tieu", json={**body, "xac_nhan_vuot_tong": True}).json()
        assert lan_2["da_ghi"] is True and lan_2["tong_con_lai"] == -1_000_000
    assert _dem_dong("chi_tieu") == 1


def test_api_them_thu_nhap_them_va_du_lieu_sai():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        resp = client.post("/api/thu-nhap-them", json={"mo_ta": "thưởng quý", "so_tien": 2_000_000})
        assert resp.status_code == 200 and resp.json()["da_ghi"] is True
        for sai in ({"mo_ta": "x", "so_tien": True}, {"mo_ta": "x", "so_tien": 0},
                    {"mo_ta": "", "so_tien": 1_000}, {"mo_ta": 3, "so_tien": 1_000}, {"so_tien": 1_000}):
            assert client.post("/api/thu-nhap-them", json=sai).status_code == 400
    assert _dem_dong("thu_nhap_them") == 1


def test_api_sua_xoa_thu_nhap_them():
    from app import storage
    from app.jars import thang_hien_tai
    id_khoan = storage.ghi_thu_nhap_them("thưởng", 500_000, thang=thang_hien_tai())
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        assert client.patch(f"/api/thu-nhap-them/{id_khoan}", json={}).status_code == 400
        assert client.patch(f"/api/thu-nhap-them/{id_khoan}", json={"so_tien": True}).status_code == 400
        assert client.patch(f"/api/thu-nhap-them/{id_khoan}", json={"mo_ta": " "}).status_code == 400
        assert client.patch("/api/thu-nhap-them/999999", json={"so_tien": 1}).status_code == 404
        assert client.patch("/api/thu-nhap-them/abc", json={"so_tien": 1}).status_code == 400
        resp = client.patch(f"/api/thu-nhap-them/{id_khoan}", json={"so_tien": 700_000, "mo_ta": "thưởng quý 3"})
        assert resp.status_code == 200
        dong = storage.danh_sach_thu_nhap_them_trong_thang(thang_hien_tai())[0]
        assert (dong["so_tien"], dong["mo_ta"]) == (700_000, "thưởng quý 3")
        assert client.delete(f"/api/thu-nhap-them/{id_khoan}").status_code == 200
        assert client.delete(f"/api/thu-nhap-them/{id_khoan}").status_code == 404
    assert _dem_dong("thu_nhap_them") == 0


def test_api_them_giao_dich_cong_ty_hai_loai_va_du_lieu_sai():
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        assert client.post("/api/cong-ty/giao-dich", json={"loai": "tam_ung", "so_tien": 2_000_000, "mo_ta": "công tác"}).status_code == 200
        resp = client.post("/api/cong-ty/giao-dich", json={"loai": "chi", "so_tien": 480_000, "mo_ta": "vé xe"})
        assert resp.status_code == 200
        assert resp.json()["so_du_hien_tai"] == 1_520_000
        for sai in ({"loai": "khac", "so_tien": 1_000, "mo_ta": "x"}, {"loai": "chi", "so_tien": True, "mo_ta": "x"},
                    {"loai": "chi", "so_tien": 1_000, "mo_ta": ""}, {"loai": "chi", "so_tien": 1_000}):
            assert client.post("/api/cong-ty/giao-dich", json=sai).status_code == 400
    assert _dem_dong("cong_ty_giao_dich") == 2


def test_api_thong_ke_ky_6_ky_cu_toi_moi_va_theo_ngay_ky_hien_tai():
    from app import storage
    from app.jars import thang_hien_tai
    from app.web import _lui_nhan_thang
    hien_tai = thang_hien_tai()
    ky_truoc = _lui_nhan_thang(hien_tai, 1)
    with storage.db() as ket_noi:
        for thoi_gian, hu, tien, thang in (
            (f"{hien_tai}-10T08:00:00", "thiet_yeu", 100_000, hien_tai),
            (f"{hien_tai}-10T20:00:00", "huong_thu", 20_000, hien_tai),
            (f"{hien_tai}-11T08:00:00", "thiet_yeu", 5_000, hien_tai),
            (f"{ky_truoc}-10T08:00:00", "thiet_yeu", 300_000, ky_truoc),
        ):
            ket_noi.execute(
                "INSERT INTO chi_tieu (thoi_gian, hu_ma, so_tien, ghi_chu, nguon, thang) VALUES (?, ?, ?, '', 'zalo', ?)",
                (thoi_gian, hu, tien, thang))
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        data = client.get("/api/thong-ke-ky").json()
        assert [k["thang"] for k in data["ky"]] == [_lui_nhan_thang(hien_tai, i) for i in range(5, -1, -1)]
        assert data["ky"][-1] == {"thang": hien_tai, "tong_chi": 125_000, "theo_hu": {"thiet_yeu": 105_000, "huong_thu": 20_000}}
        assert data["ky"][-2]["tong_chi"] == 300_000
        assert data["ky"][0] == {"thang": _lui_nhan_thang(hien_tai, 5), "tong_chi": 0, "theo_hu": {}}
        assert data["theo_ngay"] == [{"ngay": f"{hien_tai}-10", "tong": 120_000}, {"ngay": f"{hien_tai}-11", "tong": 5_000}]
        assert len(client.get("/api/thong-ke-ky?so_ky=3").json()["ky"]) == 3
        for sai in ("0", "13", "abc"):
            assert client.get(f"/api/thong-ke-ky?so_ky={sai}").status_code == 400


def test_lui_nhan_thang_qua_nam():
    from app.web import _lui_nhan_thang
    assert _lui_nhan_thang("2026-02", 3) == "2025-11"
    assert _lui_nhan_thang("2026-09", 0) == "2026-09"


def test_api_ngan_sach_co_ngay_bat_dau_ky_nay():
    from datetime import date
    from app.jars import ngay_bat_dau_chu_ky
    with TestClient(_tao_app_test()) as client:
        _dang_nhap(client)
        data = client.get("/api/ngan-sach").json()
    bat_dau = date.fromisoformat(data["ngay_bat_dau_ky_nay"])
    ky_sau = date.fromisoformat(data["ngay_bat_dau_ky_sau"])
    assert bat_dau.day == ngay_bat_dau_chu_ky() and bat_dau <= date.today() < ky_sau
    assert (ky_sau.year * 12 + ky_sau.month) - (bat_dau.year * 12 + bat_dau.month) == 1
