"""Test logic adapter Veo (mock network) — chứng minh image→video không còn
NameError `key_index`, request có ảnh, và parse b64 video đúng.

Không gọi Google API thật: patch `veo_video.requests` (curl_cffi) để mô phỏng
submit → poll(done) → download.
"""

from __future__ import annotations

import base64
import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.image_providers import veo_video as vv  # noqa: E402


class _FakeResp:
    def __init__(self, status: int, jsondata: dict | None = None, content: bytes = b""):
        self.status_code = status
        self._json = jsondata or {}
        self.content = content
        self.text = ""

    def json(self) -> dict:
        return self._json


class VeoGenerateTests(unittest.TestCase):
    def _submit(self) -> _FakeResp:
        return _FakeResp(200, {"name": "operations/abc"})

    def _poll_done(self) -> _FakeResp:
        return _FakeResp(200, {
            "done": True,
            "response": {"generateVideoResponse": {"generatedSamples": [
                {"video": {"uri": "https://gen/v.mp4"}}]}},
        })

    def test_image_to_video_polls_with_submit_key_and_returns_b64(self) -> None:
        adapter = vv.VeoVideoAdapter()
        creds = {"apiKeys": ["KEY_A", "KEY_B"]}
        img_b64 = base64.b64encode(b"fakepng").decode()
        dl = _FakeResp(200, content=b"VIDEOBYTES")

        with mock.patch.object(vv, "requests") as rq, \
                mock.patch.object(vv.time, "sleep", return_value=None):
            rq.post.return_value = self._submit()
            rq.get.side_effect = [self._poll_done(), dl]
            out = adapter.generate(
                {"prompt": "a cat", "image": img_b64, "aspect_ratio": "9:16"},
                creds,
            )

        # 1) Trả về b64 video (parse đúng chuỗi generateVideoResponse…uri).
        self.assertEqual(out["data"][0]["b64_json"],
                         base64.b64encode(b"VIDEOBYTES").decode())
        # 2) Request submit có ẢNH (image→video).
        submit_json = rq.post.call_args.kwargs["json"]
        self.assertIn("image", submit_json["instances"][0])
        self.assertEqual(submit_json["parameters"]["aspectRatio"], "9:16")
        # 3) Poll dùng ĐÚNG key đã submit (KEY_A) — trước đây NameError key_index.
        poll_url = rq.get.call_args_list[0].args[0]
        self.assertIn("key=KEY_A", poll_url)

    def test_text_to_video_no_image_field(self) -> None:
        adapter = vv.VeoVideoAdapter()
        dl = _FakeResp(200, content=b"VID")
        with mock.patch.object(vv, "requests") as rq, \
                mock.patch.object(vv.time, "sleep", return_value=None):
            rq.post.return_value = self._submit()
            rq.get.side_effect = [self._poll_done(), dl]
            out = adapter.generate({"prompt": "sunset", "aspect_ratio": "16:9"}, {"apiKeys": ["K"]})
        self.assertTrue(out["data"][0]["b64_json"])
        submit_json = rq.post.call_args.kwargs["json"]
        self.assertNotIn("image", submit_json["instances"][0])

    def test_build_body_image_and_params(self) -> None:
        adapter = vv.VeoVideoAdapter()
        body = adapter._build_body({
            "prompt": "p", "image": "B64", "aspect_ratio": "9:16", "duration": "8",
        })
        inst = body["instances"][0]
        self.assertIn("image", inst)
        self.assertEqual(inst["image"]["bytesBase64Encoded"], "B64")
        self.assertEqual(body["parameters"]["aspectRatio"], "9:16")
        self.assertEqual(body["parameters"]["durationSeconds"], 8)


if __name__ == "__main__":
    unittest.main()
