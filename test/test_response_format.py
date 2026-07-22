"""response_format json_schema inject + enforce for HA AI Task."""
from __future__ import annotations

import json
import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.protocol import response_format as rf  # noqa: E402


class ResponseFormatTests(unittest.TestCase):
    def test_parse_json_schema(self) -> None:
        body = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "Phan_tich",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "humans_detected": {"type": "integer", "description": "count"},
                            "humans_detected_summary": {"type": "string"},
                            "humans_detected_description": {"type": "string"},
                            "animals_detected": {"type": "integer"},
                            "animals_detected_summary": {"type": "string"},
                            "animals_detected_description": {"type": "string"},
                        },
                        "required": [
                            "humans_detected",
                            "humans_detected_summary",
                            "humans_detected_description",
                            "animals_detected",
                            "animals_detected_summary",
                            "animals_detected_description",
                        ],
                    },
                },
            },
            "messages": [{"role": "user", "content": "analyze"}],
        }
        meta = rf.parse_response_format(body)
        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta["type"], "json_schema")
        self.assertIn("humans_detected", meta["schema"]["properties"])

        body2 = rf.inject_response_format_prompt(dict(body))
        msgs = body2["messages"]
        self.assertTrue(any("[response_format_json_schema]" in str(m.get("content")) for m in msgs if isinstance(m, dict)))
        self.assertTrue(body2.get("_response_format_meta"))

    def test_coerce_and_normalize(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "humans_detected": {"type": "integer"},
                "humans_detected_summary": {"type": "string"},
                "humans_detected_description": {"type": "string"},
                "animals_detected": {"type": "integer"},
                "animals_detected_summary": {"type": "string"},
                "animals_detected_description": {"type": "string"},
            },
        }
        # missing animals + string count
        data = {
            "humans_detected": "1",
            "humans_detected_summary": "1 bé trai",
            "humans_detected_description": "đi vào",
        }
        out = rf.coerce_to_schema(data, schema)
        self.assertEqual(out["humans_detected"], 1)
        self.assertEqual(out["animals_detected"], 0)
        self.assertEqual(out["animals_detected_summary"], "")

        # collapsed keys (strip markdown artifact)
        data2 = {
            "humansdetected": 2,
            "humansdetectedsummary": "2 người",
            "humansdetecteddescription": "x",
        }
        out2 = rf.coerce_to_schema(data2, schema)
        self.assertEqual(out2["humans_detected"], 2)

        text = 'Here you go:\n```json\n{"humans_detected":1,"humans_detected_summary":"1"}\n```'
        meta = {"type": "json_schema", "schema": schema}
        cleaned = rf.normalize_content(text, meta)
        obj = json.loads(cleaned)
        self.assertEqual(obj["humans_detected"], 1)
        self.assertEqual(obj["animals_detected"], 0)

    def test_recover_mangled_after_underscore_strip(self) -> None:
        schema = {
            "properties": {
                "humans_detected": {"type": "integer"},
                "humans_detected_summary": {"type": "string"},
                "humans_detected_description": {"type": "string"},
                "animals_detected": {"type": "integer"},
                "animals_detected_summary": {"type": "string"},
                "animals_detected_description": {"type": "string"},
            }
        }
        mangled = (
            "humans detected2,humans detected summaryPhát hiện 2 người 1 phụ nữ và 1 bé trai đi vào nhà.,"
            "humans detected descriptionCó 1 phụ nữ và 1 bé trai đang đi vào nhà.,"
            "animals detected0,animals detected summary,animals detected description"
        )
        meta = {"type": "json_schema", "schema": schema}
        cleaned = rf.normalize_content(mangled, meta)
        obj = json.loads(cleaned)
        self.assertEqual(obj["humans_detected"], 2)
        self.assertIn("phụ nữ", obj["humans_detected_summary"])
        self.assertEqual(obj["animals_detected"], 0)

    def test_enforce_dict_result(self) -> None:
        schema = {
            "properties": {
                "humans_detected": {"type": "integer"},
                "humans_detected_summary": {"type": "string"},
                "humans_detected_description": {"type": "string"},
                "animals_detected": {"type": "integer"},
                "animals_detected_summary": {"type": "string"},
                "animals_detected_description": {"type": "string"},
            }
        }
        body = {
            "_response_format_meta": {"type": "json_schema", "schema": schema},
        }
        result = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": '{"humans_detected":1,"humans_detected_summary":"1 bé trai","humans_detected_description":"vào nhà"}',
                },
                "finish_reason": "stop",
            }]
        }
        out = rf.enforce_response_format(result, body)
        assert isinstance(out, dict)
        content = out["choices"][0]["message"]["content"]
        obj = json.loads(content)
        self.assertEqual(obj["humans_detected"], 1)
        self.assertEqual(obj["animals_detected"], 0)
        self.assertIn("bé trai", obj["humans_detected_summary"])


    def test_vision_json_enforced_without_response_format(self) -> None:
        mangled = (
            "humans detected1,humans detected summary1 đàn ông,"
            "humans detected descriptionMột người đàn ông áo xanh,"
            "animals detected0,animals detected summary,animals detected description"
        )
        body = {
            "_is_ha_request": True,
            "messages": [{
                "role": "user",
                "content": "Đây là chuỗi hình ảnh. humans_detected trong JSON.",
            }],
        }
        result = {
            "choices": [{
                "message": {"role": "assistant", "content": mangled},
                "finish_reason": "stop",
            }]
        }
        out = rf.enforce_vision_json_if_needed(result, body)
        assert isinstance(out, dict)
        content = out["choices"][0]["message"]["content"]
        obj = json.loads(content)
        self.assertEqual(obj["humans_detected"], 1)
        self.assertIn("đàn ông", obj["humans_detected_summary"])


if __name__ == "__main__":
    unittest.main()
