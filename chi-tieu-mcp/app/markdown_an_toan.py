"""Đổi câu trả lời Markdown của AI thành HTML an toàn cho khung "Hỏi AI phân
tích" trên /ui.

Phát sinh 23/09/2026: câu trả lời hiện thành 1 khối chữ dính liền (bảng, tiêu
đề, gạch đầu dòng mất hết) -- /ui gán bằng textContent nên mọi xuống dòng bị
gộp. Xem docs/superpowers/specs/2026-09-23-giao-dien-sang-toi-design.md.

An toàn: escape TOÀN BỘ đầu vào bằng html.escape TRƯỚC khi nhận dạng cú pháp,
sau đó chỉ chèn thẻ cố định do chính module này sinh ra -- không bao giờ lấy
thuộc tính (href, src, on*...) từ đầu vào. Vì escape trước nên dấu ">" của
trích dẫn được nhận dạng ở dạng "&gt;". Link/ảnh [chữ](url) chỉ giữ chữ, bỏ
URL (chặn luôn javascript:). Python thuần, không thêm thư viện.

Hiệu năng: hàm chạy đồng bộ trong request -- mọi regex inline đều giới hạn độ
dài khớp ({1,300}...) để không bị chậm bậc hai trên dòng bệnh lý (bản đầu
không giới hạn mất ~20 giây với "**a " lặp 20.000 lần).
"""
from __future__ import annotations

import html
import re

_RAO_CODE = re.compile(r"^\s{0,3}```")
_TIEU_DE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
_KE_NGANG = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_MUC_KHONG_SO = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_MUC_CO_SO = re.compile(r"^(\s*)(\d{1,9})[.)]\s+(.*)$")
_TRICH_DAN = re.compile(r"^\s{0,3}&gt;\s?(.*)$")
# Khớp trên dòng ĐÃ strip (xem _la_dong_phan_cach): bản đầu mở bằng ^\s*\|?\s*
# -- 2 cụm \s* kề nhau, dòng có ống + dãy khoảng trắng dài thì chậm bậc hai.
_DONG_PHAN_CACH = re.compile(r"\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?")

_MA_CODE = re.compile(r"`([^`\n]{1,500})`")
_LINK = re.compile(r"!?\[([^\[\]\n]{1,300})\]\((?:[^()\s]|\([^()\s]{0,200}\)){0,500}\)")
_DAM_NGHIENG = re.compile(r"\*\*\*(?=\S)(.{1,300}?)(?<=\S)\*\*\*")
_DAM_SAO = re.compile(r"\*\*(?=\S)(.{1,300}?)(?<=\S)\*\*")
_DAM_GACH = re.compile(r"(?<!\w)__(?=\S)(.{1,300}?)(?<=\S)__(?!\w)")
_NGHIENG = re.compile(r"(?<![*\w])\*(?=[^\s*])([^*\n]{0,300}?[^\s*])\*(?![*\w])")
_GIU_CHO = re.compile(r"\x00(\d+)\x00")


def markdown_sang_html(van_ban: str) -> str:
    """Markdown (tập con AI hay dùng) -> HTML. Đầu vào rỗng -> chuỗi rỗng."""
    if not van_ban:
        return ""
    van_ban = van_ban.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    dong = html.escape(van_ban.expandtabs(4), quote=True).split("\n")
    ra: list[str] = []
    i = 0
    while i < len(dong):
        d = dong[i]
        if not d.strip():
            i += 1
        elif _RAO_CODE.match(d):
            i = _khoi_code(dong, i, ra)
        elif _TIEU_DE.match(d):
            m = _TIEU_DE.match(d)
            the = "h3" if len(m.group(1)) <= 3 else "h4"
            ra.append(f"<{the}>{_inline(_bo_day_thang_dong(m.group(2)))}</{the}>")
            i += 1
        elif _KE_NGANG.match(d):
            ra.append("<hr>")
            i += 1
        elif _bat_dau_bang(dong, i):
            i = _khoi_bang(dong, i, ra)
        elif _TRICH_DAN.match(d):
            i = _khoi_trich_dan(dong, i, ra)
        elif _la_muc(d):
            i = _khoi_danh_sach(dong, i, ra)
        else:
            i = _khoi_doan(dong, i, ra)
    return "\n".join(ra)


def _inline(s: str) -> str:
    """Định dạng trong dòng trên chuỗi ĐÃ escape. Nội dung `code` được cất
    riêng (ký tự \\x00 làm chỗ giữ -- đã lọc khỏi đầu vào) để không bị xử lý
    đậm/nghiêng tiếp."""
    ma: list[str] = []

    def _cat_ma(m: re.Match) -> str:
        ma.append(m.group(1))
        return f"\x00{len(ma) - 1}\x00"

    s = _MA_CODE.sub(_cat_ma, s)
    s = _LINK.sub(r"\1", s)
    s = _DAM_NGHIENG.sub(r"<strong><em>\1</em></strong>", s)
    s = _DAM_SAO.sub(r"<strong>\1</strong>", s)
    s = _DAM_GACH.sub(r"<strong>\1</strong>", s)
    s = _NGHIENG.sub(r"<em>\1</em>", s)
    return _GIU_CHO.sub(lambda m: f"<code>{ma[int(m.group(1))]}</code>", s)


def _bo_day_thang_dong(noi_dung: str) -> str:
    """"## Tiêu đề ##" -> "Tiêu đề"; "C#" giữ nguyên (dãy # đóng phải cách
    chữ 1 khoảng trắng). Dùng rstrip thay vì regex để không bị chậm bậc hai
    trên dòng có dãy khoảng trắng dài."""
    noi_dung = noi_dung.rstrip()
    bo_thang = noi_dung.rstrip("#")
    if bo_thang != noi_dung and (not bo_thang or bo_thang[-1].isspace()):
        return bo_thang.rstrip()
    return noi_dung


def _la_muc(d: str) -> bool:
    return bool(_MUC_KHONG_SO.match(d) or _MUC_CO_SO.match(d))


def _la_dong_phan_cach(d: str) -> bool:
    return "|" in d and bool(_DONG_PHAN_CACH.fullmatch(d.strip()))


def _bat_dau_bang(dong: list[str], i: int) -> bool:
    d = dong[i]
    if "|" not in d:
        return False
    return d.lstrip().startswith("|") or (i + 1 < len(dong) and _la_dong_phan_cach(dong[i + 1]))


def _bat_dau_khoi(dong: list[str], i: int) -> bool:
    """Dòng i mở 1 khối khác (không phải đoạn văn) -- dùng để kết thúc đoạn
    văn/danh sách/bảng đang gom."""
    d = dong[i]
    return bool(
        _RAO_CODE.match(d) or _TIEU_DE.match(d) or _KE_NGANG.match(d)
        or _bat_dau_bang(dong, i) or _TRICH_DAN.match(d) or _la_muc(d)
    )


def _khoi_code(dong: list[str], i: int, ra: list[str]) -> int:
    j = i + 1
    noi_dung: list[str] = []
    while j < len(dong) and not _RAO_CODE.match(dong[j]):
        noi_dung.append(dong[j])
        j += 1
    ra.append("<pre><code>" + "\n".join(noi_dung) + "</code></pre>")
    return j + 1


def _tach_o(d: str) -> list[str]:
    s = d.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [o.strip() for o in s.split("|")]


def _khoi_bang(dong: list[str], i: int, ra: list[str]) -> int:
    """Có dòng phân cách |---| ngay sau dòng đầu -> dòng đầu là <thead>; không
    có (C2A vẫn trả kiểu này) -> mọi dòng là <td>. Dòng phân cách ở giữa bị
    bỏ. Bọc <div class="bang-cuon"> để chỉ bảng cuộn ngang, trang thì không."""
    cac_dong = [dong[i]]
    i += 1
    while (i < len(dong) and dong[i].strip() and "|" in dong[i]
           and not (_bat_dau_khoi(dong, i) and not _bat_dau_bang(dong, i))):
        cac_dong.append(dong[i])
        i += 1
    co_tieu_de = (len(cac_dong) >= 2 and not _la_dong_phan_cach(cac_dong[0])
                  and _la_dong_phan_cach(cac_dong[1]))
    hang = [_tach_o(d) for d in cac_dong if not _la_dong_phan_cach(d)]
    if not hang:
        return i
    phan = ['<div class="bang-cuon"><table>']
    if co_tieu_de:
        tieu_de, hang = hang[0], hang[1:]
        phan.append("<thead><tr>" + "".join(f"<th>{_inline(o)}</th>" for o in tieu_de) + "</tr></thead>")
    if hang:
        phan.append("<tbody>" + "".join(
            "<tr>" + "".join(f"<td>{_inline(o)}</td>" for o in h) + "</tr>" for h in hang
        ) + "</tbody>")
    phan.append("</table></div>")
    ra.append("".join(phan))
    return i


def _khoi_trich_dan(dong: list[str], i: int, ra: list[str]) -> int:
    cac_dong: list[str] = []
    while i < len(dong) and _TRICH_DAN.match(dong[i]):
        cac_dong.append(_inline(_TRICH_DAN.match(dong[i]).group(1).strip()))
        i += 1
    ra.append("<blockquote>" + "<br>".join(cac_dong) + "</blockquote>")
    return i


def _khoi_danh_sach(dong: list[str], i: int, ra: list[str]) -> int:
    """Gom 1 danh sách (lồng theo độ thụt đầu dòng). ngan_xep giữ (độ thụt,
    "ul"/"ol") của các danh sách đang mở; <li> hiện tại luôn để mở cho tới
    khi gặp mục kế tiếp hoặc đóng danh sách."""
    ngan_xep: list[tuple[int, str]] = []
    phan: list[str] = []
    while i < len(dong):
        d = dong[i]
        if not d.strip():
            j = i
            while j < len(dong) and not dong[j].strip():
                j += 1
            if j < len(dong) and _la_muc(dong[j]) and not _KE_NGANG.match(dong[j]):
                i = j  # dòng trống giữa 2 mục: vẫn cùng 1 danh sách
                continue
            break
        m_so = _MUC_CO_SO.match(d)
        m_khong_so = _MUC_KHONG_SO.match(d)
        if (m_so or m_khong_so) and not _KE_NGANG.match(d):
            if m_so:
                thut, the, so, noi_dung = len(m_so.group(1)), "ol", int(m_so.group(2)), m_so.group(3)
            else:
                thut, the, so, noi_dung = len(m_khong_so.group(1)), "ul", 1, m_khong_so.group(2)
            while ngan_xep and ngan_xep[-1][0] > thut:
                phan.append(f"</li></{ngan_xep.pop()[1]}>")
            if ngan_xep and ngan_xep[-1] == (thut, the):
                phan.append("</li><li>")
            else:
                if ngan_xep and ngan_xep[-1][0] == thut:
                    phan.append(f"</li></{ngan_xep.pop()[1]}>")
                phan.append((f'<ol start="{so}">' if the == "ol" and so != 1 else f"<{the}>") + "<li>")
                ngan_xep.append((thut, the))
            phan.append(_inline(noi_dung.strip()))
            i += 1
        elif _bat_dau_khoi(dong, i):
            break
        else:
            phan.append("<br>" + _inline(d.strip()))  # dòng thường ngay sau mục: nối vào mục
            i += 1
    while ngan_xep:
        phan.append(f"</li></{ngan_xep.pop()[1]}>")
    ra.append("".join(phan))
    return i


def _khoi_doan(dong: list[str], i: int, ra: list[str]) -> int:
    doan = [_inline(dong[i].strip())]
    i += 1
    while i < len(dong) and dong[i].strip() and not _bat_dau_khoi(dong, i):
        doan.append(_inline(dong[i].strip()))
        i += 1
    ra.append("<p>" + "<br>".join(doan) + "</p>")
    return i
