"""Nhận KHUÔN MẶT — dò mặt (SCRFD) → căn mặt → vector (ArcFace), chạy ONNX trên CPU.

Chủ máy chốt 15/09/2026: không dùng nhận diện mặt của Frigate, dùng cách của
IRIS (github.com/anhnvme/facedetect). Lý do đo được: YOLO trên Coral chỉ có
nhãn ``person`` — COCO không có lớp khuôn mặt, nên phải có bước dò mặt riêng.

Đây là bản CHÉP LẠI đúng đường ``insightface.app.FaceAnalysis`` mà IRIS gọi
(chỉ hai mô-đun ``detection`` + ``recognition``, như IRIS bật mặc định), viết
thẳng trên onnxruntime + OpenCV + numpy. Không cài gói ``insightface``: bản 2.0
đòi ``opencv-python`` bản GUI, ``scipy``, ``scikit-image`` và ``onnx`` — hai gói
OpenCV cùng tên ``cv2`` đè nhau trong ảnh đang có ``opencv-python-headless``.

Hằng số dưới đây đọc từ mã insightface 1.0.1 (``model_zoo/scrfd.py``,
``arcface_onnx.py``, ``utils/face_align.py``). Đo khớp 15/09/2026: chạy cả bản
này lẫn ``FaceAnalysis`` gốc (venv nháp có gói insightface) trên 4 ảnh — ảnh
6 mặt, ảnh đường phố, ảnh xoay dọc, ảnh thu nhỏ 320 px — cả hai bộ model: số
mặt bằng nhau, hộp và điểm mốc lệch 0,0000 px, cosine vector nhỏ nhất
0,999999. Hai người khác nhau trong ảnh mẫu giống nhau tối đa 22,8/100.

Đo 15/09/2026 trên máy chủ, ảnh mẫu ``t1.jpg`` (6 mặt), 2 luồng:

    bộ          dò mặt    vector mỗi mặt
    buffalo_s   31 ms     22 ms      (IRIS mặc định)
    buffalo_l   321 ms    310 ms

Giấy phép: mã insightface MIT; model InsightFace chỉ cho nghiên cứu phi thương
mại — dùng trong nhà được, KHÔNG đưa model vào repo hay ảnh. Tải bằng
``scripts/download_nhin_nha.py``.

File này KHÔNG import gì trong gói ở đầu file (cùng nếp ``yolo_nha.py``).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

PHAT_HANH = "https://github.com/deepinsight/insightface/releases/download/v0.7/"


@dataclass(frozen=True)
class BoMat:
    ma: str
    zip_mb: float
    tep_do: str
    sha_do: str
    tep_vector: str
    sha_vector: str
    mo_ta: str
    #: Độ lớn vector GỐC (trước chuẩn hoá) dưới ngần này thì không phải mặt nhận
    #: được. 0 = chưa đo cho bộ này, không lọc. Độ lớn phụ thuộc model nên mỗi bộ
    #: một số (ý của MagFace/AdaFace: độ lớn đặc trưng đi theo độ dễ nhận).
    chuan_toi_thieu: float = 0.0

    @property
    def zip(self) -> str:
        return f"{self.ma}.zip"


#: Release v0.7 không có trường `digest` cho hai gói này. Băm đo 15/09/2026 trên
#: bản tải về có kích thước khớp đúng số GitHub báo (127 607 557 và 288 621 354
#: byte) — ghim để lần tải sau ra đúng model đã đo.
BO: tuple[BoMat, ...] = (
    BoMat("buffalo_s", 127.6,
          "det_500m.onnx", "5e4447f50245bbd7966bd6c0fa52938c61474a04ec7def48753668a9d8b4ea3a",
          "w600k_mbf.onnx", "9cc6e4a75f0e2bf0b1aed94578f144d15175f357bdc05e815e5c4a02b319eb4f",
          "nhẹ — IRIS mặc định, ngưỡng 40/55 chỉnh cho bộ này"),
    BoMat("buffalo_l", 288.6,
          "det_10g.onnx", "5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91",
          "w600k_r50.onnx", "4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43",
          "chính xác hơn với mặt nhỏ/xa, chậm gấp khoảng mười lần",
          # Đo 24/09/2026 trên 573 lượt camera thật: 65 lượt dưới 16 không lượt
          # nào từng được nhận «quen» (ảnh: tường, khung cửa, gáy, đầu cúi);
          # 16–19 là 0–31% đạt ngưỡng; từ 20 trở lên 77%.
          chuan_toi_thieu=16.0),
)
MAC_DINH = "buffalo_s"


def get(ma: str) -> BoMat | None:
    return next((b for b in BO if b.ma == ma), None)


# ── Hằng số của insightface 1.0.1 ────────────────────────────────────────────
#: `SCRFD._init_vars` / `prepare`: chuẩn hoá, ngưỡng, lọc trùng.
_DO_TRUNG_BINH, _DO_LECH = 127.5, 128.0
_NGUONG_DO, _NGUONG_TRUNG = 0.5, 0.4
#: 9 đầu ra = 3 tầng × (điểm, hộp, 5 điểm mốc), mỗi ô 2 neo.
_BUOC, _SO_NEO = (8, 16, 32), 2
CANH_DO = 640
#: `ArcFaceONNX.__init__`: hai model w600k không có nút Sub/Mul đầu đồ thị nên
#: nhận 127.5/127.5 (đọc bằng chính insightface trên cả hai tệp, 15/09/2026).
_VEC_TRUNG_BINH, _VEC_LECH = 127.5, 127.5
CANH_MAT = 112
#: `face_align.arcface_dst` — năm điểm mốc chuẩn trên khung 112×112.
_MOC_CHUAN = ((38.2946, 51.6963), (73.5318, 51.5014), (56.0252, 71.7366),
              (41.5493, 92.3655), (70.7299, 92.2041))


@dataclass
class Mat:
    """Một khuôn mặt. ``hop`` và ``moc`` tính bằng pixel của ảnh đưa vào."""

    hop: tuple[float, float, float, float]
    diem: float
    moc: object                    # ndarray (5, 2) float32
    vector: object = None          # ndarray (512,) float32, đã chuẩn hoá độ dài 1
    chuan: float = 0.0             # độ lớn vector gốc — thước đo mặt có nhận được không

    @property
    def rong(self) -> float:
        return self.hop[2] - self.hop[0]

    @property
    def cao(self) -> float:
        return self.hop[3] - self.hop[1]


def _nms(det, nguong: float) -> list[int]:
    """Lọc trùng — chép `SCRFD.nms` (kể cả cái +1 pixel của bản gốc)."""
    import numpy as np

    x1, y1, x2, y2, diem = det[:, 0], det[:, 1], det[:, 2], det[:, 3], det[:, 4]
    dien_tich = (x2 - x1 + 1) * (y2 - y1 + 1)
    thu_tu = diem.argsort()[::-1]
    giu: list[int] = []
    while thu_tu.size > 0:
        i = thu_tu[0]
        giu.append(int(i))
        xx1 = np.maximum(x1[i], x1[thu_tu[1:]])
        yy1 = np.maximum(y1[i], y1[thu_tu[1:]])
        xx2 = np.minimum(x2[i], x2[thu_tu[1:]])
        yy2 = np.minimum(y2[i], y2[thu_tu[1:]])
        giao = np.maximum(0.0, xx2 - xx1 + 1) * np.maximum(0.0, yy2 - yy1 + 1)
        ovr = giao / (dien_tich[i] + dien_tich[thu_tu[1:]] - giao)
        thu_tu = thu_tu[np.where(ovr <= nguong)[0] + 1]
    return giu


def giai_ma_scrfd(dau_ra: list, canh: int, ti_le: float, nguong: float = _NGUONG_DO):
    """9 đầu ra SCRFD → ``(det (n,5), moc (n,5,2))`` trong toạ độ ảnh gốc, đã lọc trùng."""
    import numpy as np

    diem_ds, hop_ds, moc_ds = [], [], []
    for i, buoc in enumerate(_BUOC):
        diem = dau_ra[i]
        hop = dau_ra[i + 3] * buoc
        moc = dau_ra[i + 6] * buoc
        o = canh // buoc
        tam = np.stack(np.mgrid[:o, :o][::-1], axis=-1).astype(np.float32)
        tam = (tam * buoc).reshape(-1, 2)
        tam = np.stack([tam] * _SO_NEO, axis=1).reshape(-1, 2)
        chon = np.where(diem >= nguong)[0]
        h = np.stack([tam[:, 0] - hop[:, 0], tam[:, 1] - hop[:, 1],
                      tam[:, 0] + hop[:, 2], tam[:, 1] + hop[:, 3]], axis=-1)
        m = np.stack([tam[:, j % 2] + moc[:, j] for j in range(10)], axis=-1).reshape(-1, 5, 2)
        diem_ds.append(diem[chon])
        hop_ds.append(h[chon])
        moc_ds.append(m[chon])
    if sum(d.size for d in diem_ds) == 0:
        return np.empty((0, 5), np.float32), np.empty((0, 5, 2), np.float32)
    diem = np.vstack(diem_ds).ravel()
    thu_tu = diem.argsort()[::-1]
    det = np.hstack((np.vstack(hop_ds) / ti_le, diem[:, None])).astype(np.float32)[thu_tu]
    moc = (np.vstack(moc_ds) / ti_le)[thu_tu]
    giu = _nms(det, _NGUONG_TRUNG)
    return det[giu], moc[giu]


def _umeyama(nguon, dich):
    """Phép đồng dạng bình phương tối thiểu — chép `skimage._umeyama` (có tỉ lệ)."""
    import numpy as np

    nguon = np.asarray(nguon, np.float64)
    dich = np.asarray(dich, np.float64)
    n, chieu = nguon.shape
    tb_n, tb_d = nguon.mean(axis=0), dich.mean(axis=0)
    lech_n, lech_d = nguon - tb_n, dich - tb_d
    a = lech_d.T @ lech_n / n
    d = np.ones((chieu,), np.float64)
    if np.linalg.det(a) < 0:
        d[chieu - 1] = -1
    t = np.eye(chieu + 1, dtype=np.float64)
    u, s, v = np.linalg.svd(a)
    hang = np.count_nonzero(s > s.max() * max(a.shape) * np.finfo(float).eps)
    if hang == 0:
        return np.nan * t
    if hang == chieu - 1:
        if np.linalg.det(u) * np.linalg.det(v) > 0:
            t[:chieu, :chieu] = u @ v
        else:
            cu = d[chieu - 1]
            d[chieu - 1] = -1
            t[:chieu, :chieu] = u @ np.diag(d) @ v
            d[chieu - 1] = cu
    else:
        t[:chieu, :chieu] = u @ np.diag(d) @ v
    ti_le = 1.0 / lech_n.var(axis=0).sum() * (s @ d)
    t[:chieu, chieu] = tb_d - ti_le * (t[:chieu, :chieu] @ tb_n.T)
    t[:chieu, :chieu] *= ti_le
    return t


def can_mat(anh, moc, canh: int = CANH_MAT):
    """Xoay–thu mặt về khung chuẩn 112×112 theo năm điểm mốc (`norm_crop`)."""
    import cv2
    import numpy as np

    m = _umeyama(moc, np.asarray(_MOC_CHUAN, np.float32) * (canh / 112.0))[:2, :]
    return cv2.warpAffine(anh, m, (canh, canh), borderValue=0.0)


def moc_la_mat(hop, moc) -> bool:
    """Năm điểm mốc có đúng hình một khuôn mặt không.

    SCRFD chấm điểm cao cả cạnh cửa và tường phẳng (đo 23/09/2026, Cam cửa:
    ảnh lưu là tường trắng + cạnh cửa, vẫn vượt ngưỡng 0,6). Tường không có
    hai mắt nằm ngang, mũi ở dưới và miệng ở dưới mũi. Thiếu mốc thì không
    kết luận — caller cũ không luôn có mốc.
    """
    import numpy as np

    try:
        m = np.asarray(moc, np.float32)
    except (TypeError, ValueError):
        return True
    if m.shape != (5, 2) or not np.isfinite(m).all():
        return True
    le, re, mui, tm, pm = m
    rong = max(1.0, float(hop[2]) - float(hop[0]))
    khoang_mat = float(np.linalg.norm(re - le))
    if not (0.15 * rong <= khoang_mat <= 1.05 * rong):
        return False
    if le[0] >= re[0]:
        return False
    giua_y = (le[1] + re[1]) * 0.5
    if not (le[0] - 0.35 * khoang_mat <= mui[0] <= re[0] + 0.35 * khoang_mat):
        return False
    if mui[1] <= giua_y:
        return False
    if tm[0] >= pm[0] or (tm[1] + pm[1]) * 0.5 <= mui[1]:
        return False
    if float(np.linalg.norm(pm - tm)) < 0.2 * khoang_mat:
        return False
    cao = (tm[1] + pm[1]) * 0.5 - giua_y
    return 0.2 * khoang_mat <= cao <= 3.0 * khoang_mat


def do_giong(a, b) -> float:
    """Độ giống kiểu IRIS: cosine của hai vector đã chuẩn hoá, kẹp ≥ 0, thang 0–100."""
    import numpy as np

    return max(0.0, float(np.dot(a, b))) * 100.0


class BoNhanMat:
    """Hai phiên ONNX (dò + vector) của một bộ model. Dùng chung giữa các luồng."""

    def __init__(self, thu_muc: Path, bo: BoMat, luong: int = 2) -> None:
        import onnxruntime as ort

        def _phien(tep: str):
            tc = ort.SessionOptions()
            tc.intra_op_num_threads = max(1, int(luong))
            tc.inter_op_num_threads = 1
            return ort.InferenceSession(str(thu_muc / tep), tc,
                                        providers=["CPUExecutionProvider"])

        self.bo = bo
        self._do = _phien(bo.tep_do)
        self._vec = _phien(bo.tep_vector)
        self._ten_ra_do = [o.name for o in self._do.get_outputs()]
        if len(self._ten_ra_do) != 9:
            raise ValueError(f"model dò mặt {bo.tep_do} có {len(self._ten_ra_do)} đầu ra, cần 9")
        self._khoa = threading.Lock()

    def do(self, anh, nguong: float = _NGUONG_DO) -> list[Mat]:
        """Dò mặt trong ảnh BGR — chép `SCRFD._detect_candidates` + `detect`."""
        import cv2
        import numpy as np

        cao, rong = anh.shape[:2]
        if cao / rong > 1.0:
            moi_c, moi_r = CANH_DO, int(CANH_DO / (cao / rong))
        else:
            moi_r, moi_c = CANH_DO, int(CANH_DO * (cao / rong))
        ti_le = moi_c / cao
        khung = np.zeros((CANH_DO, CANH_DO, 3), np.uint8)
        khung[:moi_c, :moi_r] = cv2.resize(anh, (moi_r, moi_c))
        blob = cv2.dnn.blobFromImage(khung, 1.0 / _DO_LECH, (CANH_DO, CANH_DO),
                                     (_DO_TRUNG_BINH,) * 3, swapRB=True)
        with self._khoa:
            ra = self._do.run(self._ten_ra_do, {self._do.get_inputs()[0].name: blob})
        det, moc = giai_ma_scrfd(ra, CANH_DO, ti_le, nguong)
        ra_mat = []
        for i in range(det.shape[0]):
            hop = tuple(float(x) for x in det[i, :4])
            if not moc_la_mat(hop, moc[i]):
                continue
            ra_mat.append(Mat(hop, float(det[i, 4]), moc[i]))
        return ra_mat

    def vector(self, anh, mat: Mat):
        """Tính vector cho một mặt đã dò (gán vào ``mat.vector`` và trả về)."""
        import cv2
        import numpy as np

        mat_can = can_mat(anh, mat.moc)
        blob = cv2.dnn.blobFromImages([mat_can], 1.0 / _VEC_LECH, (CANH_MAT, CANH_MAT),
                                      (_VEC_TRUNG_BINH,) * 3, swapRB=True)
        with self._khoa:
            v = self._vec.run(None, {self._vec.get_inputs()[0].name: blob})[0].ravel()
        mat.chuan = float(np.linalg.norm(v))
        mat.vector = (v / mat.chuan).astype(np.float32)
        return mat.vector

    def phan_tich(self, anh, nguong: float = _NGUONG_DO) -> list[Mat]:
        """Dò rồi tính vector cho MỌI mặt — như `FaceAnalysis.get`."""
        mats = self.do(anh, nguong)
        for m in mats:
            self.vector(anh, m)
        return mats
