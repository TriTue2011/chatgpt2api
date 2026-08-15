"""TokenRouter — đường RIÊNG, tách khỏi Custom Providers dùng chung.

Vì sao có file này thay vì sửa `custom_openai.py`: TokenRouter cần hai thứ mà
đường dùng chung không nên có, vì sửa ở đó là chạm vào mọi provider khác đang
chạy tốt (đo thật 30/07 — hai rủi ro cụ thể):

  · THỬ LẠI khi lỗi truyền tải. api.tokenrouter.com chập chờn: gọi 3 lượt liên
    tiếp cùng một body thì 1 lượt chết `curl (56) Connection closed abruptly`,
    2 lượt còn lại HTTP 200. Nhưng thêm thử-lại vào đường dùng chung sẽ làm CHẬM
    pool nhiều endpoint (Gemini Custom 4 cổng): ở đó lỗi kết nối vốn được xử lý
    tốt hơn bằng cách hạ endpoint rồi nhảy sang cái kế NGAY.
  · `stream_options={"include_usage": true}` để lấy usage ở chunk cuối. Tham số
    này CHỈ hợp lệ khi stream=true; kèm mù vào request không-stream là 400
    "stream_options can only be used with stream=true" — đủ để làm hỏng những
    lời gọi không-stream đang chạy tốt của các provider khác.

Định tuyến: tiền tố `tr/` (xem services/backend_router.py). Tiền tố
`tokenrouter/` của mục trong `custom_providers` GIỮ NGUYÊN đường cũ — hai đường
sống song song, muốn dùng đường nào thì gọi tiền tố đó.

Cấu hình: đọc `config.data["tokenrouter"]`, thiếu thì lấy lại từ mục
`custom_providers["tokenrouter"]` (khỏi phải nhập key lần nữa).
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Iterator

from curl_cffi import requests

from services.config import config
from utils.log import logger

_MAC_DINH_BASE = "https://api.tokenrouter.com/v1"

# Lỗi TRUYỀN TẢI (kết nối đứt giữa chừng, reset, bắt tay TLS hỏng) không phải lỗi
# của request nên thử lại là đúng. KHÔNG thử lại lỗi HTTP: 4xx/5xx là câu trả lời
# thật của máy chủ, người gọi phải thấy.
_THU_LAI_TOI_DA = 3
_CHO_GIUA_CAC_LAN_S = (0.8, 2.0)


def _cfg() -> dict[str, Any]:
    """Cấu hình TokenRouter: khoá riêng trước, không có thì mượn mục custom cũ."""
    data = config.data if isinstance(config.data, dict) else {}
    rieng = data.get("tokenrouter")
    if isinstance(rieng, dict) and (rieng.get("api_key") or rieng.get("api_keys")):
        return rieng
    cu = (data.get("custom_providers") or {}).get("tokenrouter")
    return cu if isinstance(cu, dict) else {}


class TokenRouterProvider:
    """Proxy OpenAI-compatible tới api.tokenrouter.com."""

    @property
    def base_url(self) -> str:
        return str(_cfg().get("base_url") or _MAC_DINH_BASE).rstrip("/")

    @property
    def api_key(self) -> str:
        cfg = _cfg()
        key = str(cfg.get("api_key") or "").strip()
        if key:
            return key
        nhieu = cfg.get("api_keys") or []
        if isinstance(nhieu, list):
            for k in nhieu:
                if str(k or "").strip():
                    return str(k).strip()
        return ""

    @property
    def enabled(self) -> bool:
        return bool(_cfg().get("enabled", True)) and bool(self.api_key)

    @property
    def is_available(self) -> bool:
        return self.enabled

    def _duong_dan(self, duoi: str) -> str:
        """Ghép URL, tránh /v1 lặp đôi khi base_url đã có sẵn /v1."""
        base = self.base_url
        if base.endswith("/v1"):
            return f"{base}{duoi}"
        return f"{base}/v1{duoi}"

    def _headers(self, stream: bool) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if stream:
            h["Accept"] = "text/event-stream"
        return h

    # ── HTTP có thử lại ─────────────────────────────────────────────────────

    def _post(self, url: str, headers: dict[str, str], body: dict[str, Any], stream: bool):
        loi_cuoi: Exception | None = None
        for lan in range(_THU_LAI_TOI_DA):
            try:
                return requests.post(url, headers=headers, json=body,
                                     timeout=300, stream=stream)
            except requests.RequestsError as exc:
                loi_cuoi = exc
                # Timeout thì ĐỪNG thử lại: đã chờ đủ 300s, thử nữa chỉ bắt người
                # dùng chờ thêm 10 phút cho một kết cục y hệt.
                if type(exc).__name__ == "Timeout" or lan == _THU_LAI_TOI_DA - 1:
                    break
                cho = _CHO_GIUA_CAC_LAN_S[min(lan, len(_CHO_GIUA_CAC_LAN_S) - 1)]
                logger.warning({
                    "event": "tokenrouter_retry_transport",
                    "lan": lan + 1,
                    "cho_s": cho,
                    "error": str(exc)[:160],
                })
                time.sleep(cho)
        raise loi_cuoi  # type: ignore[misc]

    # ── API ─────────────────────────────────────────────────────────────────

    def list_models(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        r = None
        try:
            r = self._post_get(self._duong_dan("/models"))
            if r.status_code != 200:
                logger.warning({"event": "tokenrouter_models_failed",
                                "status": r.status_code, "body": (r.text or "")[:200]})
                return []
            data = r.json() or {}
            return [m for m in (data.get("data") or []) if isinstance(m, dict)]
        except Exception as exc:
            logger.warning({"event": "tokenrouter_models_error", "error": str(exc)[:160]})
            return []
        finally:
            if r is not None:
                try:
                    r.close()
                except Exception:
                    pass

    def _post_get(self, url: str):
        """GET có thử lại — cùng lý do với _post."""
        loi_cuoi: Exception | None = None
        for lan in range(_THU_LAI_TOI_DA):
            try:
                return requests.get(url, headers=self._headers(False), timeout=60)
            except requests.RequestsError as exc:
                loi_cuoi = exc
                if type(exc).__name__ == "Timeout" or lan == _THU_LAI_TOI_DA - 1:
                    break
                time.sleep(_CHO_GIUA_CAC_LAN_S[min(lan, len(_CHO_GIUA_CAC_LAN_S) - 1)])
        raise loi_cuoi  # type: ignore[misc]

    def chat_completions(
        self,
        messages: list[dict[str, Any]],
        model: str = "",
        stream: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        **kwargs,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        if not self.api_key:
            raise RuntimeError("[tokenrouter] chưa có API key trong cấu hình")

        body: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens:
            body["max_tokens"] = max_tokens
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
        for key in ("top_p", "frequency_penalty", "presence_penalty", "seed",
                    "response_format"):
            if kwargs.get(key) is not None:
                body[key] = kwargs[key]
        # CHỈ khi stream — xem chú thích đầu file.
        if stream:
            body["stream_options"] = kwargs.get("stream_options") or {"include_usage": True}

        logger.info({"event": "tokenrouter_request", "model": model, "stream": stream})

        resp = self._post(self._duong_dan("/chat/completions"),
                          self._headers(stream), body, stream)

        if resp.status_code >= 400:
            loi = ""
            try:
                loi = (resp.text or "")[:400]
            except Exception:
                pass
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
            logger.error({"event": "tokenrouter_error", "status": resp.status_code,
                          "model": model, "error": loi})
            raise RuntimeError(f"[tokenrouter] Error {resp.status_code}: {loi[:200]}")

        return self._doc_stream(resp, model) if stream else self._doc_thuong(resp, model)

    # ── Đọc phản hồi ────────────────────────────────────────────────────────

    def _doc_thuong(self, resp, model: str) -> dict[str, Any]:
        try:
            data = resp.json()
            if not isinstance(data, dict):
                raise RuntimeError("[tokenrouter] phản hồi không phải JSON object")
            data.setdefault("object", "chat.completion")
            msg = ((data.get("choices") or [{}])[0].get("message")) or {}
            self._canh_bao_neu_trong(model, str(msg.get("content") or ""),
                                     bool(msg.get("reasoning_content")),
                                     data.get("usage") or {})
            return data
        finally:
            try:
                resp.close()
            except Exception:
                pass

    @staticmethod
    def _canh_bao_neu_trong(model: str, noi_dung: str, co_suy_luan: bool,
                            usage: dict[str, Any]) -> None:
        """Nội dung TRỐNG mà vẫn tốn token thì nói rõ vì sao.

        kimi-k3 và các model suy luận khác tiêu token vào `reasoning_content`
        TRƯỚC rồi mới sinh câu trả lời. Đặt `max_tokens` nhỏ là phần suy luận ăn
        hết ngân sách, client chỉ đọc `delta.content` nên thấy TRỐNG — trông y
        như lỗi mạng. Đo thật 30/07: max_tokens=60 → completion_tokens=60, trong
        đó reasoning_tokens=57, content rỗng; bỏ max_tokens ra thì trả lời bình
        thường trong 3,3s.
        """
        if noi_dung.strip():
            return
        chi_tiet = usage.get("completion_tokens_details") or {}
        token_suy_luan = chi_tiet.get("reasoning_tokens") or 0
        if not (co_suy_luan or token_suy_luan):
            return
        logger.warning({
            "event": "tokenrouter_content_rong",
            "model": model,
            "reasoning_tokens": token_suy_luan,
            "completion_tokens": usage.get("completion_tokens"),
            "hint": "model suy luận đã tiêu hết ngân sách vào reasoning_content — "
                    "bỏ max_tokens hoặc đặt lớn hơn (≥ 512)",
        })

    def _doc_stream(self, resp, model: str) -> Iterator[dict[str, Any]]:
        """SSE → chunk OpenAI (đã đúng định dạng, chỉ chuyển tiếp).

        Giữ luôn chunk mang `usage` ở cuối (nhờ stream_options.include_usage) —
        đó là chỗ duy nhất báo số token đã dùng.
        """
        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())
        co_noi_dung = False
        co_suy_luan = False
        usage_cuoi: dict[str, Any] = {}
        try:
            for raw in resp.iter_lines():
                if not raw:
                    continue
                line = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else str(raw)
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except Exception:
                    continue
                if not isinstance(chunk, dict):
                    continue
                chunk.setdefault("id", completion_id)
                chunk.setdefault("created", created)
                chunk.setdefault("model", model)
                chunk.setdefault("object", "chat.completion.chunk")
                if chunk.get("usage"):
                    usage_cuoi = chunk["usage"]
                for c in chunk.get("choices") or []:
                    d = c.get("delta") or {}
                    if d.get("content"):
                        co_noi_dung = True
                    if d.get("reasoning_content"):
                        co_suy_luan = True
                yield chunk
        finally:
            if not co_noi_dung:
                self._canh_bao_neu_trong(model, "", co_suy_luan, usage_cuoi)
            try:
                resp.close()
            except Exception:
                pass


tokenrouter_provider = TokenRouterProvider()
