"""A Flow recovery is successful only after the configured project opens for RPC."""
from __future__ import annotations

import unittest
from unittest import mock

from services import account_recovery as ar


class _Response:
    def __init__(self, status_code: int, body: dict):
        self.status_code, self.body = status_code, body

    def json(self):
        return self.body


class FlowProjectSessionTests(unittest.TestCase):
    def setUp(self):
        ar._glogin_captcha_until = 0.0
        ar._glogin_captcha_profile = ""

    def test_no_configured_project_is_not_a_live_session(self):
        with mock.patch.object(ar, "_flow_project_id", return_value=""):
            self.assertEqual(ar._flow_session_trang_thai("google-a"), "mat")

    def test_exact_project_rpc_ready_is_live(self):
        calls = []
        def post(url, **kwargs):
            calls.append((url, kwargs))
            return _Response(200, {"ready": True})
        with mock.patch.object(ar, "_flow_project_id", return_value="project-a"), \
                mock.patch.object(ar, "_solver_cfg", return_value=("http://solver", "k")), \
                mock.patch("requests.post", side_effect=post):
            self.assertEqual(ar._flow_session_trang_thai("google-a"), "ok")
        self.assertTrue(calls[0][0].endswith("/v1/google/flow/check-project"))
        self.assertEqual(calls[0][1]["json"]["project_id"], "project-a")

    def test_generic_project_success_cannot_mask_unready_configured_project(self):
        with mock.patch.object(ar, "_flow_project_id", return_value="project-a"), \
                mock.patch.object(ar, "_solver_cfg", return_value=("http://solver", "k")), \
                mock.patch("requests.post", return_value=_Response(200, {"project_id": "other"})):
            self.assertEqual(ar._flow_session_trang_thai("google-a"), "mat")
