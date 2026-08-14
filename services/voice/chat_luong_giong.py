"""Chất lượng PHÁT ÂM đo được của từng giọng tiếng Việt — đo ngày 14/08/2026.

**Vì sao cần bảng này.** Người dùng chọn `nghi:ngoc-huyen-moi` rồi nghe "xin
chào" thành "chin chào". Đo ra thì đúng: giọng đó làm rụng gi, k, d và đọc âm xát
/s/ yếu hơn giọng tốt cả trăm lần. Nhưng trong danh mục nó nằm cạnh 51 giọng khác
không có gì phân biệt, nên lần sau vẫn chọn nhầm. Bảng này đưa kết quả đo lên
giao diện để chọn giọng là chọn có căn cứ.

**Vì sao không sửa được bằng cách khác.** Các giọng NghiTTS dùng CÙNG bộ phiên âm
espeak `vi` và CÙNG bảng âm vị (cùng giá trị băm file cấu hình, xem
`nghitts_voices.py`), nên phần phiên âm giống nhau tuyệt đối — chỗ hụt nằm trong
trọng số model, không có tham số nào vá được. Cách sửa duy nhất là chọn giọng.

**Đo thế nào.** `scripts/kiem_phat_am.py vi --lap 3`: 20 câu phủ đủ phụ âm đầu
và phụ âm cuối tiếng Việt, mỗi câu đọc lại 3 lần rồi cho STT của chính máy nghe
lại, lấy đa số (VITS đọc ngẫu nhiên mỗi lần nên một mẫu không kết luận được).
Chữ đồng âm Bắc bộ được gộp (d/gi/r cùng /z/, s/x cùng /s/, ch/tr cùng /tɕ/) nên
"da" nghe ra "ra" KHÔNG tính là rụng. Cột âm xát là tỉ lệ năng lượng >4 kHz trên
≤2 kHz ở 70 ms đầu chữ "xin" và "sáu", lấy giá trị nhỏ hơn.

**Giới hạn cần biết.** Số âm xát chỉ đáng tin ở mức THỨ TỰ và ở mức thô
mạnh/yếu, không đáng tin ở con số lẻ: mốc dò đầu tiếng xê dịch theo từng lần đọc
nên giá trị nhảy vài lần giữa hai lượt đo, dù thứ tự các giọng thì giữ nguyên.

Một phát hiện ở mức HỌ MODEL, không phải từng giọng: âm /k/ trong "kem" bị 13
trong 19 giọng NghiTTS làm rụng, còn Piper thì 15 trong 19 giọng đọc đúng. Đo hai
họ mới tách được "STT nghe kém" khỏi "họ model đọc kém" — ở đây là họ model.
"""

from __future__ import annotations

TONG_AM = 33      # số âm phải nghe lại được trong bộ 20 câu

# id giọng → (số âm nghe lại được, sức mạnh âm xát, các âm bị rụng)
DO_DUOC: dict[str, tuple[int, float, tuple[str, ...]]] = {
    # ── Piper (id trần) ──
    "lacphi": (33, 7.0, ()),
    "maiphuong": (33, 10.0, ()),
    "manhdung": (33, 11.1, ()),
    "mytam2794": (33, 16.8, ()),
    "ngochuyen": (33, 24.4, ()),
    "ngocngan3701": (33, 32.5, ()),
    "taian2": (33, 3.6, ()),
    "taian4": (33, 13.0, ()),
    "tranthanh3870": (33, 37.6, ()),
    "vietthao3886": (33, 26.5, ()),
    "minhkhang": (32, 0.8, ("ng",)),
    "mytam2": (32, 16.9, ("gh",)),
    "ngochuyennew": (32, 12.9, ("ng",)),
    "phuongtrang": (32, 0.1, ("ng",)),
    "thanhphuong2": (32, 53.4, ("k",)),
    "banmai": (31, 2.0, ("gi", "k")),
    "chieuthanh": (29, 0.1, ("ph", "r", "gh", "k")),
    "minhquang": (29, 0.1, ("ph", "nh", "ng", "t")),
    "thientam": (28, 1.2, ("x", "ph", "tr", "gh", "k")),
    # ── NghiTTS (id "nghi:<mã>") ──
    "nghi:manh-dung": (33, 4.1, ()),
    "nghi:viet-thao": (33, 27.0, ()),
    "nghi:mai-phuong": (32, 20.0, ("k",)),
    "nghi:my-tam": (31, 0.2, ("nh", "k")),
    "nghi:ngoc-ngan": (31, 3.9, ("nh", "d")),
    "nghi:ban-mai": (30, 0.1, ("gi", "gh", "k")),
    "nghi:chieu-thanh": (30, 0.1, ("ph", "r", "k")),
    "nghi:duy-onyx-moi": (30, 0.0, ("ph", "gi", "t")),
    "nghi:lac-phi": (30, 5.5, ("gi", "k", "d")),
    "nghi:minh-quang": (30, 0.0, ("ph", "gi", "qu")),
    "nghi:ngoc-huyen-moi": (30, 0.2, ("gi", "k", "d")),
    "nghi:thanh-phuong-viettel": (30, 0.2, ("ph", "nh", "d")),
    "nghi:duy-oryx": (29, 0.0, ("ph", "gi", "k", "t")),
    "nghi:my-tam-real": (29, 0.1, ("gi", "đ", "k", "d")),
    "nghi:phuong-trang": (29, 0.1, ("x", "ngh", "k", "ng")),
    "nghi:tran-thanh": (29, 0.2, ("nh", "gi", "k", "d")),
    "nghi:tai-an": (29, 0.1, ("nh", "gi", "k", "d")),
    "nghi:minh-khang": (28, 0.0, ("kh", "nh", "ng", "gi", "k")),
    "nghi:thien-tam": (26, 0.0, ("x", "ph", "r", "kh", "tr", "gh", "k")),
}

# Dưới mốc này thì âm xát /s/ nhẹ tới mức tai nghe lệch sang âm khác — đúng ca
# "xin" nghe thành "chin". Lấy 1,0 vì số đo chia hai nhóm rất rạch ròi: nhóm đọc
# rõ nằm từ 3,6 trở lên, nhóm đọc nhẹ nằm ở 0,0–0,2.
XAT_YEU = 1.0


def nhan_xet(voice_id: str) -> dict[str, object] | None:
    """Kết quả đo của một giọng, hoặc None nếu giọng đó chưa được đo.

    `nhan` là câu ngắn cho giao diện; `diem`/`am_xat`/`rung` để ai muốn xem số.
    """
    do = DO_DUOC.get((voice_id or "").strip())
    if do is None:
        return None
    diem, am_xat, rung = do
    phan = []
    if rung:
        phan.append("rụng " + ", ".join(rung))
    if am_xat < XAT_YEU:
        phan.append("âm xát yếu")
    return {
        "nhan": " · ".join(phan) if phan else "đọc rõ",
        "diem": diem,
        "tong": TONG_AM,
        "am_xat": am_xat,
        "rung": list(rung),
        "dat": not phan,
    }
