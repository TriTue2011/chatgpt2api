"""API «mắt của nhà» — Cài đặt → Home Assistant → tab 🧑 Khuôn mặt.

Cấu hình (`nhin_nha`) lưu qua đường lưu config chung như mọi thẻ khác. Ở đây
chỉ có những việc web không tự làm được: đọc trạng thái model/luồng canh, và
quản sổ khuôn mặt (người, ảnh mặt, mặt lạ, sự kiện).

Ảnh mặt là dữ liệu sinh trắc — mọi đường đều ``require_admin``, ảnh trả về dưới
dạng data URL thu nhỏ chứ không mở một đường tĩnh công khai nào cho kho mặt.

``GET  /api/nhin-nha/trang-thai``            model đã tải + số liệu luồng canh
``GET  /api/nhin-nha/nguoi``                 người đã dạy (kèm từng ảnh mặt + mã)
``POST /api/nhin-nha/day``                   dạy mặt: form ``ten`` + ``anh`` (+ ``ep``)
``POST /api/nhin-nha/nguoi/{id}/doi-ten``    ``{"ten": "..."}``
``DELETE /api/nhin-nha/nguoi/{id}``
``POST /api/nhin-nha/mat/{id}/chuyen``       ``{"ten": "..."}`` — nhận nhầm thì đổi chủ
``GET  /api/nhin-nha/mat-la``                mặt lạ đang theo dõi (kèm ảnh từng lượt)
``POST /api/nhin-nha/mat-la/{id}/dat-ten``   ``{"ten": "..."}``
``POST /api/nhin-nha/mat-la/{id}/thoi-hoi``
``GET  /api/nhin-nha/su-kien?so_gio=24``      lịch sử nhận diện (kèm ảnh nhỏ)
``POST /api/nhin-nha/su-kien/{id}/chuyen``   ``{"ten": "..."}`` — gán lại lượt gặp
"""

from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from api.support import require_admin

logger = logging.getLogger(__name__)

#: Ảnh tải lên để dạy mặt — ảnh điện thoại nguyên gốc hiếm khi quá 12 MB.
_TOI_DA_BYTE = 15_000_000
#: Cạnh dài của ảnh mặt gửi ra web. Trước là 160 và chủ máy kêu «ảnh tách mặt
#: vẫn mờ» — đo 17/09/2026: ảnh LƯU trên đĩa của người đã dạy là 181–428 px
#: (trung vị 269), tức nguồn đủ nét, chính bước thu nhỏ này làm mờ. 320 thì
#: data URL to gấp ~4 lần nhưng vẫn chỉ vài chục KB, chỉ dùng cho hai danh
#: sách thu nhỏ.
#: Lưu ý: ảnh MẶT LẠ trung vị chỉ 152 px — mờ từ nguồn vì người đứng xa, nâng
#: trần ở đây KHÔNG cứu được, muốn nét phải đứng gần hơn hoặc dùng luồng chính
#: độ phân giải cao hơn.
_CANH_NHO = 320
#: Trần số ảnh gửi kèm mỗi người và mỗi cụm mặt lạ. Mỗi ảnh là một data URL
#: ~320 px nhúng thẳng vào JSON, nên hồ sơ 20 ảnh sẽ làm phình cả câu trả lời.
TOI_DA_ANH = 8
#: Trần số ảnh nhỏ kèm LỊCH SỬ nhận diện, tính cho TỪNG TAB (mỗi người quen một
#: tab, cộng tab «Mặt khác») — KHÔNG phải trần toàn cục. Mỗi ảnh nhúng ~13 KB.
#:
#: Vì sao theo tab: đo 17/09/2026 trên lịch sử thật, 100 trong 111 lượt là «không
#: nhận ra ai». Một trần toàn cục 60 ảnh bị nhóm đông ăn hết, làm 3 trong 11 lượt
#: của người quen mất ảnh (hạng 83, 88, 91) — đúng những tab dùng để soi nhận
#: nhầm. Trần sinh ra để giới hạn dung lượng, không phải để chọn tab nào đáng soi.
TOI_DA_ANH_SU_KIEN = 40


def _thu_nho(du_lieu: bytes) -> str:
    """Byte ảnh → data URL JPEG cạnh dài ≤ ``_CANH_NHO``. Hỏng thì chuỗi rỗng."""
    import cv2
    import numpy as np

    anh = cv2.imdecode(np.frombuffer(du_lieu, np.uint8), cv2.IMREAD_COLOR)
    if anh is None:
        return ""
    cao, rong = anh.shape[:2]
    ti_le = _CANH_NHO / max(cao, rong)
    if ti_le < 1:
        anh = cv2.resize(anh, (max(1, int(rong * ti_le)), max(1, int(cao * ti_le))),
                         interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", anh, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii") if ok else ""


def _anh_nho(rel: str) -> str:
    """Ảnh trong kho KHUÔN MẶT → data URL thu nhỏ. Mất ảnh thì chuỗi rỗng."""
    from services import so_mat_nha

    p = so_mat_nha.duong_anh(rel)
    return _thu_nho(p.read_bytes()) if p is not None else ""


def _goc_anh():
    """Thư mục kho ảnh chung. Tách riêng để test thay được mà không đụng config."""
    from pathlib import Path

    from services.config import config

    return Path(config.images_dir)


def _anh_su_kien(url: str) -> str:
    """Ảnh một lượt gặp → data URL thu nhỏ. Không đọc được thì chuỗi rỗng.

    ``su_kien.anh`` giữ URL tuyệt đối trỏ vào kho ảnh chung
    (``http://127.0.0.1:80/images/...``) — địa chỉ ấy là của chính máy chủ nên
    trình duyệt người dùng KHÔNG gọi được. Đọc từ đĩa rồi nhúng, giống mọi ảnh
    mặt khác: ảnh sinh trắc không mở đường tĩnh công khai (xem đầu file).

    Chặn thoát thư mục như ``so_mat_nha.duong_anh``: đường dẫn đi vào từ sổ, mà
    một chuỗi ``..`` lọt qua đây là đọc được file bất kỳ trên máy.
    """
    u = str(url or "")
    if "/images/" not in u:
        return ""
    rel = u.split("/images/", 1)[1]
    if not rel:
        return ""
    try:
        goc = _goc_anh().resolve()
        p = (goc / rel).resolve()
        if not p.is_file() or goc not in p.parents:
            return ""
        return _thu_nho(p.read_bytes())
    except (OSError, ValueError):
        return ""


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/nhin-nha/trang-thai")
    async def trang_thai(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import canh_camera_nha, nhin_nha, so_mat_nha

        from services import yolo_nha

        tt = canh_camera_nha.trang_thai()
        # Danh sách nhãn để web dựng ô tích. Lấy từ bảng tên tiếng Việt chứ
        # không bắt web tự chép: chép là sớm muộn lệch nhau.
        nhan = [{"ma": ma, "ten": ten} for ma, ten in yolo_nha.TEN_VIET.items()]
        return {"ok": True, "model": {**nhin_nha.trang_thai(), "nhan": nhan},
                "canh": {k: v for k, v in tt.items() if k != "cau_hinh"},
                "so_nguoi": len(so_mat_nha.danh_sach_nguoi()),
                "so_mat_la": len(so_mat_nha.danh_sach_mat_la())}

    @router.get("/api/nhin-nha/nguoi")
    async def nguoi(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import so_mat_nha

        def _doc():
            ds = so_mat_nha.danh_sach_nguoi()
            for n in ds:
                n["anh"] = _anh_nho(n["anh"])
                # Kèm MÃ từng ảnh, không chỉ ảnh: web phải trỏ được vào một ảnh
                # cụ thể để chuyển nó sang người khác khi thấy nhận nhầm. `nguon`
                # đi cùng vì mặt vào sổ từ camera dễ sai hơn mặt dạy bằng ảnh tay.
                n["mat_ds"] = [{"id": m["id"], "anh": a, "nguon": m["nguon"]}
                               for m, a in ((m, _anh_nho(m["anh"]))
                                            for m in so_mat_nha.mat_cua(n["id"])[:TOI_DA_ANH])
                               if a]
            return ds
        return {"ok": True, "nguoi": await run_in_threadpool(_doc)}

    @router.post("/api/nhin-nha/mat/{mat_id}/chuyen")
    async def chuyen_mat(mat_id: str, body: dict, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import so_mat_nha

        try:
            kq = await run_in_threadpool(so_mat_nha.chuyen_mat, mat_id,
                                         str(body.get("ten") or ""))
        except so_mat_nha.LoiSoMat as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **kq}

    @router.delete("/api/nhin-nha/mat/{mat_id}")
    async def xoa_mot_mat(mat_id: str, authorization: str | None = Header(default=None)):
        """Xoá MỘT ảnh mặt khỏi sổ — đường dọn ảnh xấu hoặc ảnh vào nhầm.

        `so_mat_nha.xoa_mat` có sẵn từ lâu nhưng KHÔNG endpoint nào gọi tới, nên trên
        web chỉ xoá được cả một người: muốn bỏ một tấm xấu thì phải xoá sạch rồi dạy
        lại từ đầu. Chủ máy báo thiếu 20/09/2026.
        """
        require_admin(authorization)
        from services import so_mat_nha

        return {"ok": so_mat_nha.xoa_mat(mat_id)}

    @router.post("/api/nhin-nha/day")
    async def day(ten: str = Form(...), anh: UploadFile = File(...), ep: bool = Form(False),
                  authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import nhin_nha, so_mat_nha

        du_lieu = await anh.read(_TOI_DA_BYTE + 1)
        if len(du_lieu) > _TOI_DA_BYTE:
            raise HTTPException(413, "Ảnh lớn quá (tối đa 15 MB).")
        try:
            from services import photo_intent
            du_lieu, loi = photo_intent.prepare_incoming(du_lieu)   # HEIC/AVIF → JPEG
            if not du_lieu:
                return {"ok": False, "error": loi}
            kq = await run_in_threadpool(so_mat_nha.day, ten, du_lieu, nguon="web", ep=ep)
        except (so_mat_nha.LoiSoMat, nhin_nha.ChuaCoModel) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **kq}

    @router.post("/api/nhin-nha/nguoi/{nguoi_id}/doi-ten")
    async def doi_ten(nguoi_id: str, body: dict, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import so_mat_nha

        try:
            ok = so_mat_nha.doi_ten(nguoi_id, str(body.get("ten") or ""))
        except so_mat_nha.LoiSoMat as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": ok}

    @router.delete("/api/nhin-nha/nguoi/{nguoi_id}")
    async def xoa_nguoi(nguoi_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import so_mat_nha

        return {"ok": await run_in_threadpool(so_mat_nha.xoa_nguoi, nguoi_id)}

    @router.get("/api/nhin-nha/mat-la")
    async def mat_la(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import so_mat_nha

        def _doc():
            ds = so_mat_nha.danh_sach_mat_la()
            for x in ds:
                x["anh"] = _anh_nho(x["anh"])
                # Ảnh TỪNG lượt gặp, không chỉ tấm đại diện lúc cụm ra đời: chỉ
                # khi nhìn cả nhóm mới thấy cụm có đang trộn hai người hay không.
                x["anh_ds"] = [a for a in (_anh_su_kien(u) for u
                                           in so_mat_nha.anh_su_kien_cua(x["id"], TOI_DA_ANH))
                               if a]
            return ds
        return {"ok": True, "mat_la": await run_in_threadpool(_doc)}

    @router.post("/api/nhin-nha/mat-la/{ma}/dat-ten")
    async def dat_ten_mat_la(ma: str, body: dict, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import nhin_nha, so_mat_nha

        try:
            hoc = True if body.get("hoc") is None else bool(body.get("hoc"))
            kq = await run_in_threadpool(so_mat_nha.dat_ten_mat_la, ma,
                                         str(body.get("ten") or ""), hoc=hoc)
        except (so_mat_nha.LoiSoMat, nhin_nha.ChuaCoModel) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **kq}

    @router.post("/api/nhin-nha/mat-la/{ma}/thoi-hoi")
    async def thoi_hoi(ma: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import so_mat_nha

        return {"ok": so_mat_nha.thoi_hoi_mat_la(ma)}

    @router.get("/api/nhin-nha/su-kien")
    async def su_kien(so_gio: float = 24, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import so_mat_nha

        so_gio = max(0.5, min(24 * 30, float(so_gio)))

        def _doc():
            ds = so_mat_nha.su_kien_gan(so_gio, gioi_han=200)
            dem: dict[str, int] = {}
            for s in ds:
                # Đếm riêng cho từng tab (xem `TOI_DA_ANH_SU_KIEN`): tab nào cũng
                # được đủ ảnh để soi, không để nhóm đông nuốt phần của nhóm ít.
                khoa = str(s.get("nguoi_id") or "la")
                thu = dem.get(khoa, 0)
                dem[khoa] = thu + 1
                s["anh_nho"] = _anh_su_kien(s.get("anh") or "") if thu < TOI_DA_ANH_SU_KIEN else ""
                # `anh` là URL nội bộ (127.0.0.1) — trình duyệt người dùng không
                # gọi được, gửi ra chỉ gây hiểu nhầm là có ảnh mà bấm không ra.
                s.pop("anh", None)
            return ds
        return {"ok": True, "su_kien": await run_in_threadpool(_doc)}

    @router.post("/api/nhin-nha/su-kien/{su_kien_id}/chuyen")
    async def chuyen_su_kien(su_kien_id: int, body: dict,
                             authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import so_mat_nha

        try:
            hoc = True if body.get("hoc") is None else bool(body.get("hoc"))
            if body.get("ve_khac"):
                kq = await run_in_threadpool(so_mat_nha.chuyen_ve_khac, su_kien_id, hoc=hoc)
            else:
                kq = await run_in_threadpool(so_mat_nha.chuyen_su_kien, su_kien_id,
                                             str(body.get("ten") or ""), day_luon=hoc)
        except so_mat_nha.LoiSoMat as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **kq}

    return router
