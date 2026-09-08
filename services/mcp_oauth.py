"""OAuth 2.1 for remote MCPs. Secrets stay in an encrypted, process-safe store.

The config only holds an opaque connection ID. OAuth metadata never receives
the gateway's headers or credentials. Tokens are bound to the exact MCP URL.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import fcntl
import hashlib
import hmac
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from urllib.error import HTTPError
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, ProxyHandler, build_opener

from cryptography.fernet import Fernet, InvalidToken

from services import net_guard

FLOW_TTL = 600
CALLBACK_PATH = "/api/mcp/oauth/callback"
METADATA_PATH = "/api/mcp/oauth/client-metadata"


class OAuthError(ValueError):
    """Safe, user-facing error. Never include raw provider responses."""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _https_url(value: str) -> str:
    if not isinstance(value, str):
        raise OAuthError("URL trong OAuth metadata không hợp lệ.")
    try:
        p = urlsplit(value)
        if (len(value) > 2048 or p.scheme != "https" or not p.hostname
                or p.username is not None or p.password is not None or p.fragment
                or any(ord(c) < 33 for c in value)):
            raise ValueError()
        _ = p.port
        if p.hostname.lower() == "localhost":
            raise ValueError()
        try:
            if not ipaddress.ip_address(p.hostname).is_global:
                raise OAuthError("OAuth yêu cầu địa chỉ HTTPS công khai.")
        except ValueError as exc:
            if isinstance(exc, OAuthError):
                raise
    except ValueError as exc:
        raise OAuthError("OAuth yêu cầu URL HTTPS hợp lệ, không có credential hoặc fragment.") from exc
    return value


def public_base(value: str) -> str:
    """Callback origin is configured by the admin, never a provider redirect."""
    value = value.rstrip("/")
    p = urlsplit(value)
    if p.path or p.query or p.fragment or p.username or p.password:
        raise OAuthError("URL công khai OAuth phải là origin, ví dụ https://ai.example.com.")
    if p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1", "::1"):
        _ = p.port
        return value
    return _https_url(value)


def _strings(value):
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise OAuthError("Danh sách trong OAuth metadata không hợp lệ.")
    return value


def _resource_audience(endpoint, advertised):
    """A server may identify its resource by an origin or a containing path.

    This changes the requested audience only; outgoing tokens remain bound to
    the exact configured endpoint. Never accept another origin or sibling path.
    """
    _https_url(advertised)
    target, resource = urlsplit(endpoint), urlsplit(advertised)
    if ((target.hostname.lower(), target.port or 443) != (resource.hostname.lower(), resource.port or 443)
            or (resource.query and resource.query != target.query)
            or not (target.path.rstrip("/") == resource.path.rstrip("/")
                    or target.path.startswith(resource.path.rstrip("/") + "/"))):
        raise OAuthError("OAuth resource không khớp URL MCP.")
    return advertised


class OAuthHTTP:
    """Bounded public HTTPS requests; no redirects, proxies or DNS rebinding."""

    def request(self, url, *, method="GET", body=None, headers=None):
        _https_url(url)
        try:
            net_guard.check_url(url)
            outgoing = {"User-Agent": "chatgpt2api/1.5.0", "Accept": "application/json"}
            outgoing.update(headers or {})
            data = None
            if body is not None:
                if outgoing.get("Content-Type") == "application/json":
                    data = json.dumps(body).encode()
                else:
                    outgoing["Content-Type"] = "application/x-www-form-urlencoded"
                    data = urlencode(body).encode()
            opener = build_opener(ProxyHandler({}), net_guard._NoRedirect(),
                                  net_guard._PeerCheckedHTTPHandler(), net_guard._PeerCheckedHTTPSHandler())
            try:
                response = opener.open(Request(url, data=data, headers=outgoing, method=method), timeout=10)
            except HTTPError as exc:
                response = exc
            with response:
                raw = response.read(1024 * 1024 + 1)
                status = response.code
                response_headers = {k.lower(): v for k, v in response.headers.items()}
            if len(raw) > 1024 * 1024:
                raise OAuthError("Phản hồi OAuth quá lớn.")
            try:
                document = json.loads(raw) if raw else {}
            except (ValueError, UnicodeDecodeError):
                document = {}
            return status, response_headers, document if isinstance(document, dict) else {}
        except OAuthError:
            raise
        except Exception:
            raise OAuthError("Không kết nối được dịch vụ OAuth. Kiểm tra URL và thử lại.") from None


class OAuthStore:
    """SQLite serializes callback consumption and refresh-token rotation across workers."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)
        self.path = self.directory / "credentials.sqlite3"
        # The lock also protects first-run key creation across processes.
        with open(self.directory / "init.lock", "a+b") as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            key_path = self.directory / "key"
            configured_key = os.getenv("MCP_OAUTH_ENCRYPTION_KEY", "").strip()
            if configured_key:
                key = configured_key.encode()
            else:
                if not key_path.exists():
                    if self.path.exists():
                        raise OAuthError("Thiếu khóa mã hóa OAuth; khôi phục khóa từ bản sao lưu.")
                    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "wb") as f:
                        f.write(Fernet.generate_key())
                key = key_path.read_bytes()
            try:
                self.cipher = Fernet(key)
            except ValueError:
                raise OAuthError("Khóa mã hóa OAuth không hợp lệ.") from None
            with sqlite3.connect(self.path) as db:
                db.execute("CREATE TABLE IF NOT EXISTS credentials (id TEXT PRIMARY KEY, state_hash TEXT, payload BLOB NOT NULL)")
                db.execute("CREATE UNIQUE INDEX IF NOT EXISTS oauth_state ON credentials(state_hash)")
            os.chmod(self.path, 0o600)

    def _decode(self, row):
        if row is None:
            return None
        try:
            return json.loads(self.cipher.decrypt(row[0]))
        except (InvalidToken, ValueError):
            raise OAuthError("Không giải mã được OAuth; kiểm tra khóa mã hóa.") from None

    def get(self, oauth_id):
        with sqlite3.connect(self.path, timeout=35) as db:
            return self._decode(db.execute("SELECT payload FROM credentials WHERE id=?", (oauth_id,)).fetchone())

    def find_state(self, state):
        with sqlite3.connect(self.path, timeout=35) as db:
            row = db.execute("SELECT id FROM credentials WHERE state_hash=?", (_hash(state),)).fetchone()
            return row[0] if row else None

    @contextmanager
    def edit(self, oauth_id):
        db = sqlite3.connect(self.path, timeout=35)
        try:
            db.execute("BEGIN IMMEDIATE")
            record = self._decode(db.execute("SELECT payload FROM credentials WHERE id=?", (oauth_id,)).fetchone()) or {}
            yield record
            encrypted = self.cipher.encrypt(json.dumps(record).encode())
            db.execute("INSERT OR REPLACE INTO credentials VALUES (?, ?, ?)",
                       (oauth_id, record.get("state_hash"), encrypted))
            db.commit()
        finally:
            db.close()


class OAuthManager:
    def __init__(self, store, http=None, *, now=time.time):
        self.store = store
        self.http = http or OAuthHTTP()
        self.now = now

    def discover(self, resource):
        _https_url(resource)
        status, headers, _ = self.http.request(resource, method="POST", body={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                       "clientInfo": {"name": "chatgpt2api", "version": "1.5.0"}},
        }, headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        challenge = headers.get("www-authenticate", "")
        def parameter(name):
            match = re.search(r'(?:^|[\s,])' + name + r'=(?:"([^"\r\n]*)"|([^\s,]+))', challenge, re.I)
            return (match.group(1) if match.group(1) is not None else match.group(2)) if match else None
        p = urlsplit(resource)
        origin = urlunsplit((p.scheme, p.netloc, "", "", ""))
        explicit = parameter("resource_metadata")
        candidates = [explicit] if explicit else list(dict.fromkeys([
            origin + "/.well-known/oauth-protected-resource" + p.path.rstrip("/"),
            origin + "/.well-known/oauth-protected-resource",
        ]))
        protected = None
        for url in candidates:
            code, _, data = self.http.request(_https_url(url))
            if code == 200:
                protected = data
                break
        if not protected:
            raise OAuthError("Không tìm được OAuth metadata khớp URL MCP.")
        audience = _resource_audience(resource, protected.get("resource"))
        issuers = _strings(protected.get("authorization_servers", []))
        if not issuers:
            raise OAuthError("MCP chưa khai báo máy chủ đăng nhập OAuth.")
        issuer = _https_url(str(issuers[0]))
        ip = urlsplit(issuer)
        if ip.query:
            raise OAuthError("OAuth issuer không được có query.")
        root = urlunsplit((ip.scheme, ip.netloc, "", "", ""))
        path = ip.path.rstrip("/")
        metadata = None
        for url in dict.fromkeys([root + "/.well-known/oauth-authorization-server" + path,
                                  root + "/.well-known/openid-configuration" + path,
                                  issuer.rstrip("/") + "/.well-known/openid-configuration"]):
            code, _, data = self.http.request(url)
            if code == 200:
                metadata = data
                break
        if not metadata or metadata.get("issuer") != issuer:
            raise OAuthError("OAuth issuer không khớp metadata.")
        if "S256" not in _strings(metadata.get("code_challenge_methods_supported", [])):
            raise OAuthError("Nhà cung cấp chưa công bố hỗ trợ PKCE S256.")
        for key in ("authorization_endpoint", "token_endpoint"):
            _https_url(str(metadata.get(key, "")))
        scope = parameter("scope")
        if scope is None:
            scope = " ".join(_strings(protected.get("scopes_supported", [])))
        return metadata, audience, scope

    def begin(self, resource, redirect_uri, browser_binding, *, client_id="", client_secret="", scope=None, client_metadata_url="", reuse_oauth_id=""):
        base = public_base(redirect_uri.removesuffix(CALLBACK_PATH))
        if redirect_uri != base + CALLBACK_PATH:
            raise OAuthError("Callback OAuth không hợp lệ.")
        metadata, audience, suggested_scope = self.discover(resource)
        methods = _strings(metadata.get("token_endpoint_auth_methods_supported", ["client_secret_basic"]))
        # A registration belongs to this issuer, resource and callback. Reuse it
        # for reconnects, without ever returning client credentials to the browser.
        previous = self.store.get(reuse_oauth_id) if reuse_oauth_id else None
        reused_auth_method = None
        if (not client_id and not client_secret and previous
                and previous.get("resource") == resource and previous.get("redirect_uri") == redirect_uri
                and previous.get("metadata", {}).get("issuer") == metadata["issuer"]):
            client_id = previous.get("client_id", "")
            client_secret = previous.get("client_secret", "")
            reused_auth_method = previous.get("auth_method", "none")
        auth_method = "none"
        if reused_auth_method is not None:
            auth_method = reused_auth_method
        elif client_id:
            if client_secret:
                auth_method = next((m for m in ("client_secret_basic", "client_secret_post") if m in methods), "")
                if not auth_method:
                    raise OAuthError("Nhà cung cấp không hỗ trợ kiểu Client Secret này.")
        elif client_secret:
            raise OAuthError("Client Secret cần đi cùng Client ID.")
        elif metadata.get("client_id_metadata_document_supported") is True and client_metadata_url:
            client_id = _https_url(client_metadata_url)
        elif metadata.get("registration_endpoint"):
            code, _, registered = self.http.request(_https_url(metadata["registration_endpoint"]), method="POST", body={
                "client_name": "chatgpt2api", "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            }, headers={"Content-Type": "application/json"})
            if code not in (200, 201) or not isinstance(registered.get("client_id"), str):
                raise OAuthError("Không tự đăng ký được OAuth client. Nhập Client ID đã đăng ký với nhà cung cấp.")
            client_id = registered["client_id"]
            client_secret = registered.get("client_secret", "")
            auth_method = registered.get("token_endpoint_auth_method", "none")
            if auth_method not in ("none", "client_secret_basic", "client_secret_post"):
                raise OAuthError("Kiểu xác thực OAuth client chưa được hỗ trợ.")
        else:
            raise OAuthError("Nhà cung cấp yêu cầu Client ID đăng ký trước. Mở cấu hình nâng cao để nhập.")
        if (not isinstance(client_id, str) or not client_id or len(client_id) > 2048
                or not isinstance(client_secret, str) or len(client_secret) > 8192
                or any(ord(c) < 32 for c in client_id + client_secret)
                or (auth_method != "none" and not client_secret)):
            raise OAuthError("Thông tin đăng ký OAuth client không hợp lệ.")
        state, verifier, oauth_id = secrets.token_urlsafe(32), secrets.token_urlsafe(48), secrets.token_hex(16)
        granted_scope = suggested_scope if scope is None else scope.strip()
        if len(granted_scope) > 2048 or any(ord(c) < 32 for c in granted_scope):
            raise OAuthError("Scope OAuth không hợp lệ.")
        record = {"resource": resource, "audience": audience, "metadata": metadata,
                  "redirect_uri": redirect_uri, "client_id": client_id, "client_secret": client_secret,
                  "auth_method": auth_method, "scope": granted_scope, "status": "pending",
                  "state_hash": _hash(state), "browser_hash": _hash(browser_binding),
                  "verifier": verifier, "deadline": self.now() + FLOW_TTL}
        with self.store.edit(oauth_id) as target:
            target.update(record)
        params = dict(parse_qsl(urlsplit(metadata["authorization_endpoint"]).query))
        params.update({"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
                       "state": state, "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode(),
                       "code_challenge_method": "S256", "resource": audience})
        if granted_scope:
            params["scope"] = granted_scope
        endpoint = urlsplit(metadata["authorization_endpoint"])
        return {"oauth_id": oauth_id, "state": state, "authorization_url": urlunsplit(endpoint._replace(query=urlencode(params)))}

    def _token_request(self, record, form, endpoint=None):
        form = {**form, "client_id": record["client_id"], "resource": record["audience"]}
        headers = {}
        if record["auth_method"] == "client_secret_basic":
            credentials = quote(record["client_id"], safe="") + ":" + quote(record["client_secret"], safe="")
            headers["Authorization"] = "Basic " + base64.b64encode(credentials.encode()).decode()
        elif record["auth_method"] == "client_secret_post":
            form["client_secret"] = record["client_secret"]
        return self.http.request(endpoint or record["metadata"]["token_endpoint"], method="POST", body=form, headers=headers)

    def _save_token(self, record, token):
        access = token.get("access_token")
        refresh = token.get("refresh_token", record.get("refresh_token", ""))
        if (not isinstance(access, str) or not access or len(access) > 16384
                or any(ord(c) < 33 or ord(c) > 126 for c in access)
                or str(token.get("token_type", "")).lower() != "bearer"
                or not isinstance(refresh, str) or len(refresh) > 16384):
            raise OAuthError("Phản hồi token OAuth không hợp lệ.")
        expiry = None
        if token.get("expires_in") is not None:
            try:
                ttl = float(token["expires_in"])
                if not math.isfinite(ttl) or ttl <= 0:
                    raise ValueError()
                expiry = self.now() + ttl
            except (ValueError, TypeError):
                raise OAuthError("Thời hạn token OAuth không hợp lệ.") from None
        record.update(access_token=access, refresh_token=refresh, expires_at=expiry,
                      status="connected", error="", retry_at=0)
        if isinstance(token.get("scope"), str):
            record["scope"] = token["scope"][:2048]

    def finish(self, state, browser_binding, *, code="", error="", issuer=""):
        if not state or len(state) > 128 or not browser_binding:
            raise OAuthError("Phiên đăng nhập không hợp lệ hoặc đã hết hạn.")
        oauth_id = self.store.find_state(state)
        if not oauth_id:
            raise OAuthError("Phiên đăng nhập không hợp lệ hoặc đã được sử dụng.")
        failure = None
        with self.store.edit(oauth_id) as record:
            if (record.get("state_hash") != _hash(state)
                    or not hmac.compare_digest(record.get("browser_hash", ""), _hash(browser_binding))):
                raise OAuthError("Phiên đăng nhập không thuộc trình duyệt này.")
            record.pop("state_hash", None)
            try:
                if self.now() >= record["deadline"]:
                    raise OAuthError("Phiên đăng nhập đã hết hạn; hãy kết nối lại.")
                if ((issuer or record["metadata"].get("authorization_response_iss_parameter_supported") is True)
                        and issuer != record["metadata"]["issuer"]):
                    raise OAuthError("Nhà cung cấp trả về issuer không khớp.")
                if error or not code or len(code) > 8192:
                    raise OAuthError("Đăng nhập bị hủy hoặc nhà cung cấp từ chối cấp quyền.")
                status, _, token = self._token_request(record, {
                    "grant_type": "authorization_code", "code": code,
                    "redirect_uri": record["redirect_uri"], "code_verifier": record["verifier"],
                })
                if status != 200:
                    raise OAuthError("Không đổi được mã đăng nhập thành token. Hãy kết nối lại.")
                self._save_token(record, token)
            except OAuthError as exc:
                failure = exc
                record.update(status="disconnected", error=str(exc))
            finally:
                record.pop("verifier", None)
                record.pop("browser_hash", None)
        if failure:
            raise failure
        return oauth_id

    def status(self, oauth_id):
        record = self.store.get(oauth_id) or {}
        status = record.get("status", "disconnected")
        if status == "pending" and self.now() >= record.get("deadline", 0):
            status = "disconnected"
        if (status == "connected" and record.get("expires_at") is not None
                and self.now() >= record["expires_at"] and not record.get("refresh_token")):
            status = "reauth_required"
        return {"status": status, "expires_at": record.get("expires_at"),
                "can_refresh": bool(record.get("refresh_token")), "scope": record.get("scope", ""),
                "error": record.get("error", "")}

    def token(self, oauth_id, resource, *, rejected_token=None):
        failure = None
        result = ""
        # Keep the refresh and persistence in one transaction. A second worker
        # must see the rotated refresh token, never redeem the old one again.
        with self.store.edit(oauth_id) as record:
            if record.get("resource") != resource or record.get("status") != "connected":
                raise OAuthError("MCP OAuth chưa kết nối hoặc cần đăng nhập lại.")
            if record.get("retry_at", 0) > self.now():
                raise OAuthError("Dịch vụ OAuth tạm lỗi; thử lại sau ít giây.")
            expiry = record.get("expires_at")
            refresh = (expiry is not None and self.now() >= expiry - (60 if record.get("refresh_token") else 0))
            refresh |= rejected_token is not None and rejected_token == record.get("access_token")
            if refresh:
                try:
                    if not record.get("refresh_token"):
                        record.update(status="reauth_required", access_token="")
                        raise OAuthError("Token đã hết hiệu lực; hãy kết nối tài khoản lại.")
                    status, _, token = self._token_request(record, {"grant_type": "refresh_token", "refresh_token": record["refresh_token"]})
                    if status != 200:
                        if status in (400, 401, 403) and token.get("error") in ("invalid_grant", "invalid_client", "unauthorized_client"):
                            record.update(status="reauth_required", access_token="", refresh_token="")
                        raise OAuthError("Không gia hạn được OAuth; thử lại hoặc kết nối tài khoản lại.")
                    self._save_token(record, token)
                except OAuthError as exc:
                    failure = exc
                    record.update(error=str(exc), retry_at=self.now() + 30)
            result = record.get("access_token", "")
        if failure:
            raise failure
        return result

    def disconnect(self, oauth_id, *, forget_client=False):
        with self.store.edit(oauth_id) as record:
            old = dict(record)
            record.clear()
            # Retain the encrypted client registration so reconnect needs only
            # provider login. All tokens and pending browser state are removed.
            if not forget_client:
                record.update({k: old[k] for k in ("resource", "audience", "metadata", "redirect_uri",
                                                  "client_id", "client_secret", "auth_method") if k in old})
            record.update(status="disconnected")
        # Local disconnect is unconditional even when the provider is down.
        endpoint = old.get("metadata", {}).get("revocation_endpoint")
        token = old.get("refresh_token") or old.get("access_token")
        revoked = False
        if endpoint and token:
            try:
                status, _, _ = self._token_request(old, {"token": token, "token_type_hint": "refresh_token" if old.get("refresh_token") else "access_token"}, _https_url(endpoint))
                revoked = status == 200
            except OAuthError:
                pass
        return {"ok": True, "revoked": revoked}

    def reject(self, oauth_id, token):
        """Do not invalidate a newer token rotated by another worker."""
        with self.store.edit(oauth_id) as record:
            if record.get("access_token") == token:
                record.update(status="reauth_required", access_token="", refresh_token="",
                              error="Token bị từ chối; hãy kết nối tài khoản lại.")


_manager = None
_manager_lock = threading.Lock()


def get_manager():
    global _manager
    with _manager_lock:
        if _manager is None:
            from services.config import DATA_DIR
            _manager = OAuthManager(OAuthStore(DATA_DIR / "mcp_oauth"))
        return _manager
