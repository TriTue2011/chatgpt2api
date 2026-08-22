from __future__ import annotations

import json
import os
import unittest

import requests

from services.protocol import openai_v1_models


# Đọc từ biến môi trường, giữ giá trị cũ làm mặc định. Ghim cứng thì bộ test này
# không chạy được ở đâu cả: `chatgpt2api` là khoá mặc định thời trước, nay
# config.py bắt buộc khai qua CHATGPT2API_AUTH_KEY và từ chối giá trị mẫu; còn
# cổng 8000 không phải cổng của bản chạy thật nào (máy chủ publish 3030).
#
#   C2A_TEST_BASE_URL=http://172.16.10.38:3030 C2A_TEST_AUTH_KEY=<khoá> pytest ...
AUTH_KEY = os.getenv("C2A_TEST_AUTH_KEY", "chatgpt2api")
BASE_URL = os.getenv("C2A_TEST_BASE_URL", "http://localhost:8000")


class ModelListTests(unittest.TestCase):
    def test_list_models_function(self):
        """测试直接调用服务层获取模型列表。"""
        result = openai_v1_models.list_models()
        print("function result:")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    def test_list_models_http(self):
        """测试通过 HTTP 接口获取模型列表。"""
        response = requests.get(
            f"{BASE_URL}/v1/models",
            headers={"Authorization": f"Bearer {AUTH_KEY}"},
            timeout=30,
        )
        print("http status:")
        print(response.status_code)
        print("http result:")
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
