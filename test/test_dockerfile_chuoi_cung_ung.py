"""Chuỗi cung ứng của image: không URL di động, không tải mà không kiểm.

Hai kiểu hỏng mà bộ test này canh:

  1. **URL di động** — `/releases/latest/download/` và `rclone-current-*.deb`.
     Hai lần build CÙNG một commit ra hai image khác nhau, và một bản thượng
     nguồn hỏng (hoặc bị chiếm) đi thẳng vào production mà không qua bước xem
     xét nào. Không có cách nào phát hiện sau đó, vì chẳng có gì để đối chiếu.

  2. **Tải mà không kiểm** — không checksum thì một artifact bị tráo trên đường
     truyền, hoặc một tài khoản phát hành bị chiếm, đều không để lại dấu vết.

Test đọc Dockerfile như VĂN BẢN, cố ý: nó phải chạy được ở mọi nơi, kể cả nơi
không có Docker (máy phát triển, runner CI ở bước test trước khi build).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
DOCKERFILE = (GOC / "Dockerfile").read_text(encoding="utf-8")

# Bỏ dòng chú thích: chúng CÓ nhắc tới các mẫu xấu để giải thích vì sao đã bỏ.
_MA = "\n".join(d for d in DOCKERFILE.splitlines() if not d.lstrip().startswith("#"))


class KhongDungUrlDiDongTests(unittest.TestCase):
    def test_khong_dung_releases_latest(self):
        self.assertNotIn("releases/latest", _MA,
                         "URL 'latest' — mỗi lần build ra một binary khác")

    def test_khong_dung_rclone_current(self):
        self.assertNotIn("rclone-current", _MA,
                         "'rclone-current' là URL di động, không checksum được")

    def test_moi_phien_ban_deu_khai_tuong_minh(self):
        for ten in ("RCLONE_VERSION", "CLOUDFLARED_VERSION", "OFFICECLI_VERSION"):
            self.assertRegex(_MA, rf"ARG {ten}=\S+", f"{ten} chưa ghim")


class BaseImageGhimDigestTests(unittest.TestCase):
    def test_moi_FROM_deu_co_digest(self):
        for dong in re.findall(r"^FROM\s+(\S+)", _MA, re.MULTILINE):
            if dong.lower() == "scratch":
                continue
            self.assertIn("@sha256:", dong, f"FROM {dong} chưa ghim digest")

    def test_moi_COPY_from_image_deu_co_digest(self):
        """`COPY --from=<image>` cũng kéo image từ registry — dễ quên nhất."""
        for tham_chieu in re.findall(r"COPY\s+--from=(\S+)", _MA):
            if "@sha256:" in tham_chieu or "/" not in tham_chieu and ":" not in tham_chieu:
                continue          # tên stage nội bộ (web-build, zalo-build…)
            self.assertIn("@sha256:", tham_chieu,
                          f"COPY --from={tham_chieu} chưa ghim digest")


class MoiArtifactDeuDuocKiemTests(unittest.TestCase):
    """Mỗi khối RUN có tải release binary thì phải có `sha256sum -c` trong đó."""

    def _cac_khoi_run(self) -> list[str]:
        khoi, dang = [], []
        for dong in _MA.splitlines():
            if dang:
                dang.append(dong)
                if not dong.rstrip().endswith("\\"):
                    khoi.append("\n".join(dang))
                    dang = []
            elif dong.startswith("RUN "):
                dang = [dong]
                if not dong.rstrip().endswith("\\"):
                    khoi.append(dong)
                    dang = []
        if dang:
            khoi.append("\n".join(dang))
        return khoi

    def test_khoi_nao_tai_binary_thi_khoi_do_phai_kiem(self):
        thieu = []
        for k in self._cac_khoi_run():
            tai = ("github.com" in k and "releases/download" in k) or \
                  ("downloads.rclone.org" in k)
            if tai and "sha256sum -c" not in k:
                thieu.append(k.splitlines()[0][:70])
        self.assertEqual(thieu, [], f"tải mà không kiểm checksum: {thieu}")

    def test_co_du_bon_cho_kiem(self):
        """piper, rclone, cloudflared, officecli."""
        self.assertGreaterEqual(_MA.count("sha256sum -c"), 4)

    def test_checksum_dung_dinh_dang_sha256(self):
        for sha in re.findall(r'_SHA="([^"]+)"', _MA):
            self.assertRegex(sha, r"^[0-9a-f]{64}$", f"{sha!r} không phải SHA-256")


if __name__ == "__main__":
    unittest.main()
