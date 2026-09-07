"""Regression: Flow mới xác thực bằng cookie, không dùng OAuth của labs.google."""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import types
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image


ROOT = Path(__file__).resolve().parents[1] / "captcha-solver/src/solvers"


def load(name):
    spec = importlib.util.spec_from_file_location(f"flow_cookie_test.solvers.{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FR = load("flow_rest")
RPC = load("flow_rpc")


def wire(result, rpc="ogiZ0b"):
    payload = json.dumps([["wrb.fr", rpc, json.dumps(result), None, None, None, "generic"]])
    return ")]}'\n\n" + str(len(payload.encode())) + "\n" + payload + '\n25\n[["di",1]]\n'


def generated():
    # Redacted shape captured from a successful Flow UI generation, 07/09/2026.
    image = [None, 123, None, None, None, None, 1, "a teapot", 25, None, None,
             "workflow", None, "https://cdn.example/image.jpg", 3]
    return [[["media", None, "workflow", None, None, None, [image, None, [1376, 768]]]], []]


class ProtocolTests(unittest.TestCase):
    def test_models_ratios_references_and_batch_count(self):
        for model in ("GEM_PIX_2", "NARWHAL", "HARBOR_SEAL"):
            for ratio, number in {"16:9": 3, "4:3": 5, "1:1": 1, "3:4": 4, "9:16": 2}.items():
                with self.subTest(model=model, ratio=ratio):
                    body = RPC.image_body("project", "Ấm trà", model, ratio, 2, "captcha", ["reference"])
                    self.assertEqual(len(body[1]), 2)
                    req = body[1][0]
                    self.assertEqual(req[2], [["reference", None, None, None, 1]])
                    self.assertEqual(req[4:6], [number, model])
                    self.assertEqual(req[8], [[["Ấm trà"]]])
                    self.assertEqual(req[7][5], "project")
                    self.assertEqual(req[7][10], ["captcha", 1])
                    self.assertEqual(req[7], body[3])
                    self.assertNotEqual(req[12:], body[1][1][12:])
                    self.assertEqual(RPC.image_body("p", "x", model, FR.TY_LE_ANH[ratio], 1, "c", [])[1][0][4], number)

    def test_count_limits_and_input_validation(self):
        for requested, expected in ((0, 1), (1, 1), (4, 4), (5, 4)):
            self.assertEqual(len(RPC.image_body("p", "x", "NARWHAL", "1:1", requested, "c", [])[1]), expected)
        for model, ratio in (("NANO_BANANA_PRO", "1:1"), ("NARWHAL", "unknown")):
            with self.assertRaises(ValueError):
                RPC.image_body("p", "x", model, ratio, 1, "c", [])

    def test_parse_captured_response_and_ignore_other_rpc(self):
        text = wire(["irrelevant"], "other") + wire(generated())
        self.assertEqual(RPC.image_result(RPC.rpc_result(text, "ogiZ0b")),
                         (["media"], ["https://cdn.example/image.jpg"]))

    def test_http_200_rpc_errors_are_not_success(self):
        for code, expected in ((3, 400), (7, 403), (8, 429), (16, 401), (13, 502)):
            for row in (["er", "ogiZ0b", code], ["wrb.fr", "ogiZ0b", None, None, None, [code]]):
                with self.subTest(row=row):
                    with self.assertRaises(FR.LoiFlowRest) as caught:
                        RPC.rpc_result(json.dumps([row]), "ogiZ0b")
                    self.assertEqual(caught.exception.status, expected)
                    self.assertIn(f"HTTP {expected}", str(caught.exception))

    def test_missing_or_malformed_result_never_succeeds(self):
        for text in ("<html>sign in</html>", wire({}, "ogiZ0b"), wire([], "other"),
                     '[["er","ogiZ0b",{}]]'):
            with self.subTest(text=text), self.assertRaises(FR.LoiFlowRest):
                RPC.rpc_result(text, "ogiZ0b")
        for result in ([], [[]], [[[]]], [[None]], [[["media", None, None, None, None, None, [[]]]]]):
            with self.subTest(result=result), self.assertRaises(FR.LoiFlowRest):
                RPC.image_result(result)

    def test_upload_detects_actual_mime(self):
        for fmt, mime in (("PNG", "image/png"), ("JPEG", "image/jpeg")):
            output = io.BytesIO()
            Image.new("RGB", (2, 2)).save(output, format=fmt)
            raw = output.getvalue()
            body = RPC.upload_body("p", raw, "captcha")
            self.assertEqual(base64.b64decode(body[1]), raw)
            self.assertEqual(body[2], mime)
            self.assertEqual(body[0][10], ["captcha", 1])

    @unittest.skipUnless(shutil.which("node"), "Requires Node to evaluate browser readiness")
    def test_ready_waits_for_runtime_and_csrf_not_script_tag(self):
        script = "const vm=require('vm');const fn=" + json.dumps(RPC.READY) + ";"
        script += """
        function check(window, hostname='flow.google.com', pathname='/project/p') {
          return vm.runInNewContext('('+fn+')()', {window,location:{hostname,pathname}});
        }
        const assert=require('assert');
        assert.equal(check({}),false);
        assert.equal(check({WIZ_global_data:{SNlM0e:'csrf'}}),false);
        assert.equal(check({grecaptcha:{enterprise:{execute(){}}}}),false);
        assert.equal(check({grecaptcha:{enterprise:{execute(){}}},WIZ_global_data:{SNlM0e:'csrf'}}),true);
        assert.equal(check({},'accounts.google.com','/signin'),true);
        assert.equal(check({},'flow.google.com','/about'),true);
        """
        subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)


class ImageFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.page = types.SimpleNamespace(url="https://flow.google.com/project/p",
            goto=AsyncMock(), wait_for_function=AsyncMock(), evaluate=AsyncMock(), wait_for_url=AsyncMock())
        self.captcha = AsyncMock(return_value=("captcha", "sitekey"))
        browser = types.ModuleType("flow_cookie_test.browser_pool")
        google = types.ModuleType("flow_cookie_test.solvers.flow_google")
        google._get_recaptcha_token = self.captcha

        @asynccontextmanager
        async def page_context(**kwargs):
            yield self.page

        browser.pool = types.SimpleNamespace(page=page_context)
        modules = patch.dict(sys.modules, {browser.__name__: browser, google.__name__: google})
        modules.start()
        self.addCleanup(modules.stop)

    async def test_image_endpoint_never_reads_expired_legacy_oauth(self):
        self.page.evaluate.return_value = {"status": 200, "text": wire(generated())}
        with patch.object(FR, "lay_bearer", AsyncMock(side_effect=AssertionError("legacy OAuth called"))):
            result = await FR.tao_anh(profile="google-profile", project_id="p", prompt="teapot", model="gem_pix_2")
        self.assertEqual(result["urls"], ["https://cdn.example/image.jpg"])
        self.assertEqual(result["media_ids"], ["media"])
        self.assertEqual(result["model"], "GEM_PIX_2")
        self.page.goto.assert_awaited_once_with("https://flow.google.com/project/p", wait_until="domcontentloaded", timeout=30000)
        self.captcha.assert_awaited_once_with(self.page, action="IMAGE_GENERATION")

    async def test_uploads_finish_before_fresh_generation_captcha(self):
        events = []
        async def captcha(page, action):
            page.wait_for_function.assert_awaited_once()
            events.append(action)
            return action, "sitekey"
        async def post(page, rpc, body, timeout):
            events.append(rpc)
            if rpc == "maseQ":
                return [["reference-id"]]
            self.assertEqual(body[1][0][2], [["reference-id", None, None, None, 1]])
            self.assertEqual(body[3][10][0], "IMAGE_GENERATION")
            return generated()
        self.captcha.side_effect = captcha
        raw = io.BytesIO()
        Image.new("RGB", (2, 2)).save(raw, format="PNG")
        with patch.object(RPC, "post_rpc", side_effect=post):
            await RPC.generate_image(profile="g", project_id="p", prompt="x", model="NARWHAL",
                aspect_ratio="1:1", count=1, anh_tham_chieu=[raw.getvalue()], headless=True, timeout=120)
        self.assertEqual(events, ["UPLOAD_IMAGE", "maseQ", "IMAGE_GENERATION", "ogiZ0b"])

    async def test_login_redirect_is_actionable_without_generation(self):
        self.page.url = "https://accounts.google.com/v3/signin/challenge"
        with self.assertRaises(FR.LoiFlowRest) as caught:
            await RPC.generate_image(profile="g", project_id="p", prompt="x", model="NARWHAL",
                aspect_ratio="1:1", count=1, anh_tham_chieu=None, headless=True, timeout=120)
        self.assertEqual(caught.exception.status, 401)
        self.assertIn("đăng nhập", str(caught.exception))
        self.captcha.assert_not_awaited()

    async def test_marketing_cta_enters_project_once(self):
        self.page.url = "https://flow.google.com/about"
        self.page.evaluate.return_value = True
        async def entered(predicate, **kwargs):
            self.assertFalse(predicate("https://flow.google.com/about"))
            self.assertTrue(predicate("https://flow.google.com/"))
            self.page.url = "https://flow.google.com/"
            async def goto(url, **kwargs):
                self.page.url = url
            self.page.goto.side_effect = goto
        self.page.wait_for_url.side_effect = entered
        await RPC.open_project(self.page, "p", "g")
        self.assertEqual(self.page.url, "https://flow.google.com/project/p")
        self.page.evaluate.assert_awaited_once()

    async def test_marketing_cta_stops_at_google_login(self):
        self.page.url = "https://flow.google.com/about"
        self.page.evaluate.return_value = True
        async def redirected(*args, **kwargs):
            self.page.url = "https://accounts.google.com/v3/signin/challenge"
        self.page.wait_for_url.side_effect = redirected
        with self.assertRaises(FR.LoiFlowRest) as caught:
            await RPC.open_project(self.page, "p", "g")
        self.assertEqual(caught.exception.status, 401)
        self.page.evaluate.assert_awaited_once()
        self.page.goto.assert_awaited_once()

    async def test_http_error_does_not_leak_response_secrets(self):
        self.page.evaluate.return_value = {"status": 403, "text": "private CSRF value"}
        with self.assertRaises(FR.LoiFlowRest) as caught:
            await RPC.post_rpc(self.page, "ogiZ0b", [], 120)
        self.assertEqual(caught.exception.status, 403)
        self.assertNotIn("private", str(caught.exception))
