from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from services.auth_service import auth_service

from api.support import (
    require_admin,
    sanitize_cpa_pool,
    sanitize_cpa_pools,
    sanitize_sub2api_server,
    sanitize_sub2api_servers,
)
from services.account_service import account_service, account_group, WEB_SESSION_GROUPS
from services.config import config
from services.cpa_service import cpa_config, cpa_import_service, list_remote_files
from services.sub2api_service import (
    list_remote_accounts as sub2api_list_remote_accounts,
    list_remote_groups as sub2api_list_remote_groups,
    sub2api_config,
    sub2api_import_service,
)
from utils.log import logger


def _profile_for_email(email: str) -> str:
    """google-<email-localpart> — account-centric, provider-neutral convention
    (matches jwt_refresh_scheduler + the onboard cards) so we target the right
    captcha-solver profile. One Google account = one profile across providers."""
    local = (email.split("@", 1)[0] or "default")
    safe = "".join(c if c.isalnum() or c == "-" else "-" for c in local)
    return f"google-{safe}"


def _is_placeholder_profile(profile: str) -> bool:
    """True for the legacy single-`profile` config placeholders (chatgpt-default,
    gemini-web-default, claude-web-default, ...). These are NOT real onboarded
    Google accounts — they only exist because the Settings card defaults the
    field. The provider-tree must not surface them, otherwise the user can never
    "delete" chatgpt-default from the Accounts UI (it isn't in accounts[]).
    Mirrors the web reuse-profile-picker filter /(^|[-_])default$/i."""
    import re
    return bool(re.search(r"(^|[-_])default$", str(profile or "").strip(), re.IGNORECASE))


_WEB_PROVIDER_KEYS = ("claude", "gemini_web", "gemini_web_api", "chatgpt_web", "flow")


def _strip_web_profiles_from_config(profiles: set[str]) -> None:
    """Remove the given profile names from every web provider's accounts[] /
    profiles[] / legacy `profile` field.

    A web-session account is dual-sourced: the account_service pool AND
    providers.<web>.accounts[]. Deleting only the pool entry leaves the config
    entry, which the provider-tree re-injects, so the account reappears (this is
    the "chatgpt-default keeps coming back" / "Claude won't delete" bug). Wiping
    the config entry makes the delete stick. The on-disk captcha-solver browser
    profile (a shared Google session) is intentionally left untouched — that is
    a separate, explicit action."""
    if not profiles:
        return
    from services.config import config
    providers = config.data.get("providers")
    if not isinstance(providers, dict):
        return
    changed = False
    for key in _WEB_PROVIDER_KEYS:
        cfg = providers.get(key)
        if not isinstance(cfg, dict):
            continue
        accs = cfg.get("accounts")
        if isinstance(accs, list):
            kept = [a for a in accs if not (isinstance(a, dict) and str(a.get("profile") or "").strip() in profiles)]
            if len(kept) != len(accs):
                cfg["accounts"] = kept
                changed = True
        profs = cfg.get("profiles")
        if isinstance(profs, list):
            kept_p = [p for p in profs if str(p or "").strip() not in profiles]
            if len(kept_p) != len(profs):
                cfg["profiles"] = kept_p
                changed = True
        if str(cfg.get("profile") or "").strip() in profiles:
            cfg["profile"] = ""
            changed = True
    if changed:
        config._save()


def _cleanup_captcha_profiles(accounts: list[dict]) -> None:
    """Best-effort: delete each account's captcha-solver browser profile when
    the account is removed, so the on-disk profile doesn't linger (orphan).
    Skips accounts with no email (sk-/standard/codex-token accounts have no
    browser profile). Never raises — account deletion already succeeded."""
    import httpx
    flow = (config.data.get("providers") or {}).get("flow") or {}
    from services.captcha import captcha_base
    _raw_cs = str(flow.get("captcha_solver_url") or "").strip()
    cs_url = captcha_base(_raw_cs) if _raw_cs else ""
    cs_key = str(flow.get("captcha_solver_api_key") or "")
    if not cs_url:
        return
    headers = {"Authorization": f"Bearer {cs_key}"} if cs_key else {}
    seen: set[str] = set()
    for acc in accounts:
        email = str((acc or {}).get("email") or "").strip()
        if not email or "@" not in email:
            continue
        profile = _profile_for_email(email)
        if profile in seen:
            continue
        seen.add(profile)
        try:
            r = httpx.delete(f"{cs_url}/v1/profiles/{profile}", headers=headers, timeout=30)
            logger.info({"event": "captcha_profile_delete", "profile": profile, "status": r.status_code})
        except Exception as exc:
            logger.warning({"event": "captcha_profile_delete_failed", "profile": profile, "error": str(exc)[:120]})
        try:
            # Also delete from captcha-solver accounts.db so auto-refresh loop doesn't revive it
            r2 = httpx.delete(f"{cs_url}/v1/accounts/saved/{email}", headers=headers, timeout=10)
            logger.info({"event": "captcha_account_db_delete", "email": email, "status": r2.status_code})
        except Exception as exc:
            logger.warning({"event": "captcha_account_db_delete_failed", "email": email, "error": str(exc)[:120]})



class UserKeyCreateRequest(BaseModel):
    name: str = ""


class UserKeyUpdateRequest(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    key: str | None = None


class AccountCreateRequest(BaseModel):
    tokens: list[str] = Field(default_factory=list)


class AccountDeleteRequest(BaseModel):
    tokens: list[str] = Field(default_factory=list)


class AccountRefreshRequest(BaseModel):
    access_tokens: list[str] = Field(default_factory=list)


class AccountUpdateRequest(BaseModel):
    access_token: str = ""
    type: str | None = None
    status: str | None = None
    quota: int | None = None
    notes: str | None = None


class CPAPoolCreateRequest(BaseModel):
    name: str = ""
    base_url: str = ""
    secret_key: str = ""


class CPAPoolUpdateRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    secret_key: str | None = None


class CPAImportRequest(BaseModel):
    names: list[str] = Field(default_factory=list)


class Sub2APIServerCreateRequest(BaseModel):
    name: str = ""
    base_url: str = ""
    email: str = ""
    password: str = ""
    api_key: str = ""
    group_id: str = ""


class Sub2APIServerUpdateRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    email: str | None = None
    password: str | None = None
    api_key: str | None = None
    group_id: str | None = None


class Sub2APIImportRequest(BaseModel):
    account_ids: list[str] = Field(default_factory=list)


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/auth/users")
    async def list_user_keys(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"items": auth_service.list_keys(role="user")}

    @router.post("/api/auth/users")
    async def create_user_key(body: UserKeyCreateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            item, raw_key = auth_service.create_key(role="user", name=body.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"item": item, "key": raw_key, "items": auth_service.list_keys(role="user")}

    @router.post("/api/auth/users/{key_id}")
    async def update_user_key(
            key_id: str,
            body: UserKeyUpdateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        updates = {
            key: value
            for key, value in {
                "name": body.name,
                "enabled": body.enabled,
                "key": body.key,
            }.items()
            if value is not None
        }
        if not updates:
            raise HTTPException(status_code=400, detail={"error": "还没有检测到改动，请修改后再保存"})
        try:
            item = auth_service.update_key(key_id, updates, role="user")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "这条用户密钥不存在，可能已经被删除"})
        return {"item": item, "items": auth_service.list_keys(role="user")}

    @router.delete("/api/auth/users/{key_id}")
    async def delete_user_key(key_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if not auth_service.delete_key(key_id, role="user"):
            raise HTTPException(status_code=404, detail={"error": "这条用户密钥不存在，可能已经被删除"})
        return {"items": auth_service.list_keys(role="user")}

    @router.get("/api/accounts")
    async def get_accounts(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        excluded_types = {"claude", "gemini_web", "gemini_web_api", "chatgpt_web"}
        items = [
            a for a in account_service.list_accounts()
            if a.get("type") not in excluded_types
        ]
        return {"items": items}

    @router.get("/api/v1/provider-tree")
    async def get_provider_tree(authorization: str | None = Header(default=None)):
        """Return hierarchical tree: Provider → Sub-type/API → Accounts/Status."""
        require_admin(authorization)
        from services.config import config
        from services.providers.custom_openai import get_custom_providers
        import requests as req

        accounts = account_service.list_accounts()
        providers_cfg = config.data.get("providers") or {}
        custom_providers = get_custom_providers()

        tree: list[dict] = []

        # ── ChatGPT branch ──
        # Exclude web-session pools (gemini_web_api / gemini_web / chatgpt_web /
        # claude): their pool entries carry a non-"" type so the raw type check
        # would leak them into the ChatGPT branch, but each is its OWN provider
        # branch below. Filter by canonical group, not the raw type string.
        chatgpt_accounts = [
            a for a in accounts
            if str(a.get("type") or "").lower() not in ("", "custom")
            and account_group(a) not in WEB_SESSION_GROUPS
        ]
        if chatgpt_accounts:
            # Group by canonical pool (account_group): free / codex / openai /
            # antigravity. Paid plans (plus/go/business…) land in `codex` — `go`
            # is NOT merged into free (that old behavior leaked paid accounts
            # into the free-tier view). The plan badge stays on each account.
            type_groups: dict[str, list] = {}
            for acc in chatgpt_accounts:
                acc_type = account_group(acc)
                type_groups.setdefault(acc_type, []).append(acc)
            groups = []
            for acc_type, accs in sorted(type_groups.items()):
                groups.append({
                    "key": acc_type,
                    "label": acc_type,
                    "count": len(accs),
                    "active": sum(1 for a in accs if a.get("status") == "active"),
                    "limited": sum(1 for a in accs if a.get("status") == "limited"),
                    "error": sum(1 for a in accs if a.get("status") in ("error", "disabled")),
                    "accounts": accs,
                })
            tree.append({
                "provider": "ChatGPT",
                "icon": "chatgpt",
                "type": "accounts",
                "groups": groups,
                "total": len(chatgpt_accounts),
            })

        # ── Built-in providers branch (Gemini, NVIDIA, etc.) ──
        # For each provider we expand the `api_keys` array into one row per
        # key with an ordinal (#1, #2, ...) — same priority-FIFO concept as
        # ChatGPT accounts but for API-key providers. Falls back to the
        # single `api_key` field if `api_keys` is missing.
        builtin_list = []
        for p_id, p_cfg in providers_cfg.items():
            if not isinstance(p_cfg, dict) or not p_cfg.get("enabled", False):
                continue
            base_url = p_cfg.get("base_url") or ""
            keys_arr = p_cfg.get("api_keys") if isinstance(p_cfg.get("api_keys"), list) else []
            single = p_cfg.get("api_key") or ""
            # De-dup while preserving order: api_keys first, then single if not in.
            ordered_keys = [k for k in keys_arr if isinstance(k, str) and k.strip()]
            if single and single not in ordered_keys:
                ordered_keys.insert(0, single)
            keys_payload = []
            for idx, k in enumerate(ordered_keys):
                k_info = {
                    "ordinal": idx + 1,
                    "preview": (k[:12] + "..." + k[-4:]) if len(k) > 16 else k,
                    "is_primary": idx == 0,
                    "status": "configured",
                }
                if p_id == "agnes":
                    try:
                        from services.providers.agnes import agnes_provider
                        ainfo = agnes_provider.get_account_info(api_key=k)
                        if "plan" in ainfo:
                            k_info["plan"] = ainfo["plan"]
                        if "quota" in ainfo:
                            k_info["quota"] = ainfo["quota"]
                        if "used_quota" in ainfo:
                            k_info["used_quota"] = ainfo["used_quota"]
                        if "hard_limit_usd" in ainfo:
                            k_info["hard_limit_usd"] = ainfo["hard_limit_usd"]
                        if "username" in ainfo:
                            k_info["username"] = ainfo["username"]
                        k_info["status"] = ainfo.get("status") or ("active" if ainfo.get("active") else "error")
                    except Exception as exc:
                        k_info["status"] = "error"
                        k_info["error"] = str(exc)
                keys_payload.append(k_info)
            builtin_list.append({
                "id": p_id,
                "name": p_cfg.get("name") or p_id,
                "has_key": bool(ordered_keys),
                "key_count": len(ordered_keys),
                "keys": keys_payload,
                # Back-compat for older UI builds:
                "key_preview": keys_payload[0]["preview"] if keys_payload else "—",
                "base_url": base_url or "—",
                "status": "configured",
            })
        if builtin_list:
            tree.append({
                "provider": "Providers",
                "icon": "cpu",
                "type": "providers",
                "instances": builtin_list,
                "total": len(builtin_list),
            })

        def _collect_web_accounts(cfg: dict, provider_type: str) -> list[dict]:
            """Build a Flow-style instances list from any of the three config
            shapes a web provider may use, so an onboarded/reused profile always
            shows regardless of which flow wrote it:
              - `accounts: [{profile,label,plan}]`  (account-import dialog)
              - `profiles: [profile, ...]`          (reuse picker / gemini_web_api)
              - legacy single `profile`             (Settings card reuseOnboard)
            All three are merged and de-duplicated by profile name.

            It also enriches the profiles with status and quota exhaustion stats
            from the account_service pool (which persist via record_profile_quota_failure).
            """
            out: list[dict] = []
            ordered = []
            accounts_field = cfg.get("accounts") if isinstance(cfg.get("accounts"), list) else []
            for a in accounts_field:
                if isinstance(a, dict) and a.get("profile"):
                    ordered.append({
                        "profile": str(a.get("profile") or ""),
                        "label": str(a.get("label") or a.get("profile") or ""),
                        "plan": str(a.get("plan") or "") or None,
                    })
            # `profiles: [name, ...]` — string array shape (gemini_web_api, reuse picker)
            profiles_field = cfg.get("profiles") if isinstance(cfg.get("profiles"), list) else []
            for p in profiles_field:
                name = str(p or "").strip()
                if name and not _is_placeholder_profile(name) and not any(x["profile"] == name for x in ordered):
                    ordered.append({"profile": name, "label": name, "plan": None})
            legacy = str(cfg.get("profile") or "").strip()
            if legacy and not _is_placeholder_profile(legacy) and not any(x["profile"] == legacy for x in ordered):
                ordered.insert(0, {"profile": legacy, "label": legacy, "plan": None})
            
            # Lookup in account_service
            pool_accs = {a.get("access_token"): a for a in accounts if str(a.get("type")) == provider_type}

            for idx, item in enumerate(ordered):
                prof = item["profile"]
                pool_data = pool_accs.get(prof) or {}
                out.append({
                    "ordinal": idx + 1,
                    "is_primary": idx == 0,
                    "profile": prof,
                    "access_token": prof,  # needed for UI delete tokens / matching
                    "label": item["label"],
                    "plan": item.get("plan"),
                    "enabled": item.get("enabled") is not False,
                    "status": pool_data.get("status") or "active",
                    "success": int(pool_data.get("success") or 0),
                    "fail": int(pool_data.get("fail") or 0),
                    "last_used_at": pool_data.get("last_used_at") or "",
                    "last_quota_exhausted": pool_data.get("last_quota_exhausted") or "",
                    "last_quota_exhausted_at": pool_data.get("last_quota_exhausted_at") or "",
                    "last_image_failed_at": pool_data.get("last_image_failed_at") or "",
                    "last_analysis_failed_at": pool_data.get("last_analysis_failed_at") or "",
                    "notes": pool_data.get("notes") or "",
                })
            return out

        # ── Gemini Web profile branch ──
        # gemini.google.com lives behind a Google session in a captcha-solver
        # profile. Multi-account: `providers.gemini_web.accounts = [{profile,
        # label}]` lists every onboarded Google identity so the user can
        # round-robin between them. Falls back to the legacy single
        # `profile` field for backward compatibility.
        gw_cfg = providers_cfg.get("gemini_web") or {}
        if gw_cfg.get("enabled"):
            gw_items = _collect_web_accounts(gw_cfg, "gemini_web")
            if gw_items:
                tree.append({
                    "provider": "Gemini Web",
                    "icon": "gemini",
                    "type": "gemini_web",
                    "instances": gw_items,
                    "total": len(gw_items),
                    "captcha_solver_url": gw_cfg.get("captcha_solver_url") or "",
                })

        # ── ChatGPT Web profile branch ──
        cgw_cfg = providers_cfg.get("chatgpt_web") or {}
        if cgw_cfg.get("enabled"):
            cgw_items = _collect_web_accounts(cgw_cfg, "chatgpt_web")
            if cgw_items:
                tree.append({
                    "provider": "ChatGPT Web",
                    "icon": "chatgpt",
                    "type": "chatgpt_web",
                    "instances": cgw_items,
                    "total": len(cgw_items),
                    "captcha_solver_url": cgw_cfg.get("captcha_solver_url") or "",
                })

        # ── Gemini Web API profile branch ──
        gmwa_cfg = providers_cfg.get("gemini_web_api") or {}
        if gmwa_cfg.get("enabled"):
            gmwa_items = _collect_web_accounts(gmwa_cfg, "gemini_web_api")
            if gmwa_items:
                tree.append({
                    "provider": "Gemini Web API",
                    "icon": "gemini",
                    "type": "gemini_web_api",
                    "instances": gmwa_items,
                    "total": len(gmwa_items),
                    "captcha_solver_url": gmwa_cfg.get("captcha_solver_url") or "",
                })

        # ── Google Labs Flow accounts branch ──
        flow_cfg = providers_cfg.get("flow") or {}
        flow_accounts = flow_cfg.get("accounts") if isinstance(flow_cfg.get("accounts"), list) else []
        items = []
        for idx, acc in enumerate(flow_accounts):
            if not isinstance(acc, dict):
                continue
            project_id = str(acc.get("project_id") or "")
            items.append({
                "ordinal": idx + 1,
                "is_primary": idx == 0,
                "profile": str(acc.get("profile") or ""),
                "label": str(acc.get("label") or acc.get("name") or acc.get("profile") or "—"),
                "project_id": project_id,
                "project_preview": (project_id[:8] + "..." + project_id[-4:]) if len(project_id) > 12 else project_id,
                "enabled": acc.get("enabled") is not False,
            })
        tree.append({
            "provider": "Google Labs Flow",
            "icon": "flow",
            "type": "flow",
            "instances": items,
            "total": len(items),
            "captcha_solver_url": flow_cfg.get("captcha_solver_url") or "",
        })

        # ── Claude accounts branch ──
        # Read from the account_service pool (type="claude") so accounts
        # added via the Accounts UI are visible here with ordinals + quota badges,
        # exactly like ChatGPT Free accounts. Falls back to config profiles for
        # backward compatibility when the pool is empty.
        from services.account_service import GROUP_CLAUDE
        claude_accounts = [a for a in accounts if account_group(a) == GROUP_CLAUDE]
        claude_cfg = providers_cfg.get("claude") or {}
        pool_profs = {a.get("access_token") for a in claude_accounts if a.get("access_token")}
        
        c_profs: list[str] = []
        for entry in (claude_cfg.get("accounts") or []):
            if isinstance(entry, dict) and entry.get("profile"):
                c_profs.append(str(entry.get("profile")))
        if isinstance(claude_cfg.get("profiles"), list):
            for p in claude_cfg.get("profiles"):
                if isinstance(p, str) and p and p not in c_profs:
                    c_profs.append(p)
        legacy_c = str(claude_cfg.get("profile") or "").strip()
        if legacy_c and not _is_placeholder_profile(legacy_c) and legacy_c not in c_profs:
            c_profs.append(legacy_c)
            
        for p in c_profs:
            if p not in pool_profs:
                claude_accounts.append({
                    "access_token": p,
                    "email": p,
                    "status": "active",
                })
                pool_profs.add(p)
        claude_instances = []
        for idx, acc in enumerate(claude_accounts):
            last_quota = acc.get("last_quota_exhausted") or ""
            last_quota_at = acc.get("last_quota_exhausted_at") or ""
            last_img_fail = acc.get("last_image_failed_at") or ""
            last_ana_fail = acc.get("last_analysis_failed_at") or ""
            claude_instances.append({
                "ordinal": idx + 1,
                "is_primary": idx == 0,
                "access_token": acc.get("access_token") or "",
                "email": acc.get("email") or "",
                "label": acc.get("email") or acc.get("access_token", "")[:24],
                "status": acc.get("status") or "active",
                "success": int(acc.get("success") or 0),
                "fail": int(acc.get("fail") or 0),
                "last_used_at": acc.get("last_used_at") or "",
                "last_quota_exhausted": last_quota,
                "last_quota_exhausted_at": last_quota_at,
                "last_image_failed_at": last_img_fail,
                "last_analysis_failed_at": last_ana_fail,
                "notes": acc.get("notes") or "",
            })
        tree.append({
            "provider": "Claude Web",
            "icon": "bot",
            "type": "claude",
            "instances": claude_instances,
            "total": len(claude_instances),
            "captcha_solver_url": claude_cfg.get("captcha_solver_url") or "",
        })

        # ── Custom providers branch ──
        custom_list = []
        for cp_id, cp_cfg in custom_providers.items():
            base_url = cp_cfg.get("base_url") or ""
            port = base_url.split(":")[-1].rstrip("/") if ":" in base_url else "—"
            # Quick health check
            status = "unknown"
            error_msg = None
            models_count = 0
            if base_url:
                try:
                    resp = req.get(f"{base_url}/health", timeout=4)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("ok"):
                            status = "available"
                            models_count = len(data.get("clients") or {})
                        else:
                            status = "error"
                            error_msg = data.get("error", "unknown")
                    else:
                        # Try /v1/models
                        try:
                            resp2 = req.get(f"{base_url}/v1/models", timeout=4)
                            if resp2.status_code == 200:
                                data2 = resp2.json()
                                models_list = data2.get("data") or data2.get("models") or []
                                status = "available"
                                models_count = len(models_list)
                            else:
                                status = f"http_{resp.status_code}"
                        except Exception:
                            status = f"http_{resp.status_code}"
                except Exception as e:
                    status = "offline"
                    error_msg = str(e)[:60]
            # Multi-endpoint support — providers can pool several base_urls
            # (e.g. 4 Gemini Custom instances on different ports/IPs). Show
            # each as a sub-row with ordinal so the user sees the rotation.
            extras = cp_cfg.get("base_urls") if isinstance(cp_cfg.get("base_urls"), list) else []
            all_urls = []
            if base_url:
                all_urls.append(base_url)
            for u in extras:
                u = str(u or "").strip().rstrip("/")
                if u and u not in all_urls:
                    all_urls.append(u)
            endpoints_payload = [
                {"ordinal": i + 1, "url": u, "is_primary": i == 0}
                for i, u in enumerate(all_urls)
            ]
            custom_list.append({
                "id": cp_id,
                "name": cp_cfg.get("name") or cp_id,
                "prefix": cp_cfg.get("prefix") or cp_id,
                "base_url": base_url,
                "base_urls": all_urls,
                "endpoints": endpoints_payload,
                "endpoint_count": len(all_urls),
                "port": port,
                "status": status,
                "models": models_count,
                "error": error_msg,
            })
        if custom_list:
            tree.append({
                "provider": "Custom APIs",
                "icon": "server",
                "type": "custom",
                "instances": custom_list,
                "total": len(custom_list),
            })

        return {"tree": tree}

    @router.post("/api/accounts")
    async def create_accounts(body: AccountCreateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        tokens = [str(token or "").strip() for token in body.tokens if str(token or "").strip()]
        if not tokens:
            raise HTTPException(status_code=400, detail={"error": "tokens is required"})
        result = account_service.add_accounts(tokens)
        refresh_result = account_service.refresh_accounts(tokens)
        return {
            **result,
            "refreshed": refresh_result.get("refreshed", 0),
            "errors": refresh_result.get("errors", []),
            "items": refresh_result.get("items", result.get("items", [])),
        }

    @router.post("/api/accounts/oauth")
    async def create_oauth_accounts(body: dict, authorization: str | None = Header(default=None)):
        """Add OAuth tokens (Codex from 9router) with custom type.

        For codex-type accounts: decodes JWT to extract email/plan,
        sets image_quota_unknown for image generation support.
        """
        require_admin(authorization)
        tokens = [str(t or "").strip() for t in (body.get("tokens") or []) if str(t or "").strip()]
        if not tokens:
            raise HTTPException(status_code=400, detail={"error": "tokens is required"})
        account_type = str(body.get("type") or "codex").strip()

        # For codex JWT tokens: decode metadata before adding so the UI
        # shows email / plan immediately without waiting for a refresh.
        if "codex" in account_type:
            import base64, json
            for token in tokens:
                if not token.startswith("eyJ"):
                    continue
                try:
                    parts = token.split(".")
                    if len(parts) != 3:
                        continue
                    payload_b64 = parts[1].replace("-", "+").replace("_", "/")
                    missing = (4 - (len(payload_b64) % 4)) % 4
                    payload_b64 += "=" * missing
                    payload = json.loads(base64.b64decode(payload_b64).decode("utf-8"))
                except Exception:
                    continue
                auth = payload.get("https://api.openai.com/auth") or {}
                profile = payload.get("https://api.openai.com/profile") or {}
                email = profile.get("email") or payload.get("email")
                plan = auth.get("chatgpt_plan_type")
                if email or plan:
                    account_service.update_account(token, {
                        "email": email,
                        "plan": plan or "",
                        "image_quota_unknown": True,
                        "quota": 10,
                        "status": "active",
                    })

        result = account_service.add_accounts_with_type(tokens, account_type)
        return {"items": result.get("items", []), "added": result.get("added", 0), "skipped": result.get("skipped", 0)}

    @router.delete("/api/accounts")
    async def delete_accounts(body: AccountDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        tokens = [str(token or "").strip() for token in body.tokens if str(token or "").strip()]
        if not tokens:
            raise HTTPException(status_code=400, detail={"error": "tokens is required"})
        # Lookup accounts to delete before actually removing them so we have emails for captcha-solver
        accounts_to_delete = [a for a in account_service.list_accounts() if a.get("access_token") in tokens]

        # Wiping a profile or a saved credential is its own explicit action...
        # Update: Per user request, deleting in ChatGPT UI MUST also delete from captcha-solver.
        result = account_service.delete_accounts(tokens)
        
        # Now actually delete from captcha-solver
        try:
            from fastapi.concurrency import run_in_threadpool
            import threading
            threading.Thread(target=_cleanup_captcha_profiles, args=(accounts_to_delete,), daemon=True).start()
        except Exception:
            pass
        # Web-session accounts also live in providers.<web>.accounts[]; strip
        # them there too so the delete sticks (otherwise the provider-tree
        # re-injects them from config). Browser profile on disk is left intact.
        try:
            _strip_web_profiles_from_config(set(tokens))
        except Exception:
            pass
        return result

    @router.post("/api/accounts/refresh")
    async def refresh_accounts(body: AccountRefreshRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        access_tokens = [str(token or "").strip() for token in body.access_tokens if str(token or "").strip()]
        if not access_tokens:
            access_tokens = account_service.list_tokens()
        if not access_tokens:
            raise HTTPException(status_code=400, detail={"error": "access_tokens is required"})
        return account_service.refresh_accounts(access_tokens)

    @router.post("/api/accounts/update")
    async def update_account(body: AccountUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        access_token = str(body.access_token or "").strip()
        if not access_token:
            raise HTTPException(status_code=400, detail={"error": "access_token is required"})
        updates = {key: value for key, value in {"type": body.type, "status": body.status, "quota": body.quota, "notes": body.notes}.items() if value is not None}
        if not updates:
            raise HTTPException(status_code=400, detail={"error": "还没有检测到改动，请修改后再保存"})
        account = account_service.update_account(access_token, updates)
        if account is None:
            raise HTTPException(status_code=404, detail={"error": "account not found"})
        return {"item": account, "items": account_service.list_accounts()}

    @router.post("/api/accounts/promote")
    async def promote_account(body: AccountRefreshRequest, authorization: str | None = Header(default=None)):
        """Move an account to position #1 in its type's priority queue.

        Backend will try this account first on the next request. Useful when
        you've added a fresh paid account and want it used before older ones.
        """
        require_admin(authorization)
        tokens = [str(t or "").strip() for t in body.access_tokens if str(t or "").strip()]
        if not tokens:
            raise HTTPException(status_code=400, detail={"error": "access_tokens is required"})
        # Reverse so the final element is at the very front after the loop.
        for token in reversed(tokens):
            account_service.promote_account(token)
        return {"promoted": tokens, "items": account_service.list_accounts()}

    @router.post("/api/accounts/demote")
    async def demote_account(body: AccountRefreshRequest, authorization: str | None = Header(default=None)):
        """Move an account to the BACK of its type's priority queue."""
        require_admin(authorization)
        tokens = [str(t or "").strip() for t in body.access_tokens if str(t or "").strip()]
        if not tokens:
            raise HTTPException(status_code=400, detail={"error": "access_tokens is required"})
        for token in tokens:
            account_service.demote_account(token)
        return {"demoted": tokens, "items": account_service.list_accounts()}

    @router.get("/api/cpa/pools")
    async def list_cpa_pools(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"pools": sanitize_cpa_pools(cpa_config.list_pools())}

    @router.post("/api/cpa/pools")
    async def create_cpa_pool(body: CPAPoolCreateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if not body.base_url.strip():
            raise HTTPException(status_code=400, detail={"error": "base_url is required"})
        if not body.secret_key.strip():
            raise HTTPException(status_code=400, detail={"error": "secret_key is required"})
        pool = cpa_config.add_pool(name=body.name, base_url=body.base_url, secret_key=body.secret_key)
        return {"pool": sanitize_cpa_pool(pool), "pools": sanitize_cpa_pools(cpa_config.list_pools())}

    @router.post("/api/cpa/pools/{pool_id}")
    async def update_cpa_pool(pool_id: str, body: CPAPoolUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        pool = cpa_config.update_pool(pool_id, body.model_dump(exclude_none=True))
        if pool is None:
            raise HTTPException(status_code=404, detail={"error": "pool not found"})
        return {"pool": sanitize_cpa_pool(pool), "pools": sanitize_cpa_pools(cpa_config.list_pools())}

    @router.delete("/api/cpa/pools/{pool_id}")
    async def delete_cpa_pool(pool_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if not cpa_config.delete_pool(pool_id):
            raise HTTPException(status_code=404, detail={"error": "pool not found"})
        return {"pools": sanitize_cpa_pools(cpa_config.list_pools())}

    @router.get("/api/cpa/pools/{pool_id}/files")
    async def cpa_pool_files(pool_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        pool = cpa_config.get_pool(pool_id)
        if pool is None:
            raise HTTPException(status_code=404, detail={"error": "pool not found"})
        return {"pool_id": pool_id, "files": await run_in_threadpool(list_remote_files, pool)}

    @router.post("/api/cpa/pools/{pool_id}/import")
    async def cpa_pool_import(pool_id: str, body: CPAImportRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        pool = cpa_config.get_pool(pool_id)
        if pool is None:
            raise HTTPException(status_code=404, detail={"error": "pool not found"})
        try:
            job = cpa_import_service.start_import(pool, body.names)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"import_job": job}

    @router.get("/api/cpa/pools/{pool_id}/import")
    async def cpa_pool_import_progress(pool_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        pool = cpa_config.get_pool(pool_id)
        if pool is None:
            raise HTTPException(status_code=404, detail={"error": "pool not found"})
        return {"import_job": pool.get("import_job")}

    @router.get("/api/sub2api/servers")
    async def list_sub2api_servers(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"servers": sanitize_sub2api_servers(sub2api_config.list_servers())}

    @router.post("/api/sub2api/servers")
    async def create_sub2api_server(body: Sub2APIServerCreateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if not body.base_url.strip():
            raise HTTPException(status_code=400, detail={"error": "base_url is required"})
        has_login = body.email.strip() and body.password.strip()
        has_api_key = bool(body.api_key.strip())
        if not has_login and not has_api_key:
            raise HTTPException(status_code=400, detail={"error": "email+password or api_key is required"})
        server = sub2api_config.add_server(
            name=body.name,
            base_url=body.base_url,
            email=body.email,
            password=body.password,
            api_key=body.api_key,
            group_id=body.group_id,
        )
        return {"server": sanitize_sub2api_server(server), "servers": sanitize_sub2api_servers(sub2api_config.list_servers())}

    @router.post("/api/sub2api/servers/{server_id}")
    async def update_sub2api_server(server_id: str, body: Sub2APIServerUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        server = sub2api_config.update_server(server_id, body.model_dump(exclude_none=True))
        if server is None:
            raise HTTPException(status_code=404, detail={"error": "server not found"})
        return {"server": sanitize_sub2api_server(server), "servers": sanitize_sub2api_servers(sub2api_config.list_servers())}

    @router.delete("/api/sub2api/servers/{server_id}")
    async def delete_sub2api_server(server_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if not sub2api_config.delete_server(server_id):
            raise HTTPException(status_code=404, detail={"error": "server not found"})
        return {"servers": sanitize_sub2api_servers(sub2api_config.list_servers())}

    @router.get("/api/sub2api/servers/{server_id}/groups")
    async def sub2api_server_groups(server_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        server = sub2api_config.get_server(server_id)
        if server is None:
            raise HTTPException(status_code=404, detail={"error": "server not found"})
        try:
            groups = await run_in_threadpool(sub2api_list_remote_groups, server)
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
        return {"server_id": server_id, "groups": groups}

    @router.get("/api/sub2api/servers/{server_id}/accounts")
    async def sub2api_server_accounts(server_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        server = sub2api_config.get_server(server_id)
        if server is None:
            raise HTTPException(status_code=404, detail={"error": "server not found"})
        try:
            accounts = await run_in_threadpool(sub2api_list_remote_accounts, server)
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
        return {"server_id": server_id, "accounts": accounts}

    @router.post("/api/sub2api/servers/{server_id}/import")
    async def sub2api_server_import(server_id: str, body: Sub2APIImportRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        server = sub2api_config.get_server(server_id)
        if server is None:
            raise HTTPException(status_code=404, detail={"error": "server not found"})
        try:
            job = sub2api_import_service.start_import(server, body.account_ids)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"import_job": job}

    @router.get("/api/sub2api/servers/{server_id}/import")
    async def sub2api_server_import_progress(server_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        server = sub2api_config.get_server(server_id)
        if server is None:
            raise HTTPException(status_code=404, detail={"error": "server not found"})
        return {"import_job": server.get("import_job")}

    @router.get("/api/accounts/status")
    async def account_status(authorization: str | None = Header(default=None)):
        """Rich account pool status — codext-style status header.

        Returns account health, rate-limit snapshots, parked tasks,
        and overall pool statistics in one call.
        """
        require_admin(authorization)
        accounts = account_service.list_accounts()
        # Count by status
        status_counts = {"active": 0, "limited": 0, "error": 0, "disabled": 0}
        detailed = []
        for acc in accounts:
            status = str(acc.get("status") or "active")
            status_counts[status] = status_counts.get(status, 0) + 1
            detailed.append({
                "token_preview": (str(acc.get("access_token") or ""))[:20] + "...",
                "email": acc.get("email") or None,
                "plan": acc.get("plan") or str(acc.get("type") or ""),
                "status": status,
                "quota": int(acc.get("quota") or 0),
                "success": int(acc.get("success") or 0),
                "fail": int(acc.get("fail") or 0),
                "last_used_at": str(acc.get("last_used_at") or ""),
                "restore_at": str(acc.get("restore_at") or ""),
                "health_score": round(account_service.get_health_score(acc.get("access_token") or ""), 2),
            })

        # Usage snapshot data if poller is active
        snapshots = {}
        try:
            from services.usage_snapshot_poller import usage_snapshot_poller
            snapshots = usage_snapshot_poller.get_status_summary()
        except Exception:
            snapshots = {"status": "poller_not_active"}

        # Parked task data
        parked = []
        try:
            from services.account_switch_resume import account_switch_resume
            parked = account_switch_resume.list_parked()
        except Exception:
            pass

        # Backoff stats
        backoff_stats = {}
        try:
            from services.rate_limit_backoff import rate_limit_backoff as rlb
            backoff_stats = rlb.get_stats()
        except Exception:
            pass

        # Cooldown summary
        cooldown_summary = {}
        try:
            from services.model_cooldown import model_cooldown_manager
            cooldown_summary = model_cooldown_manager.get_summary()
        except Exception:
            pass

        return {
            "pool": {
                "total": len(accounts),
                "by_status": status_counts,
                "accounts": detailed,
            },
            "usage_snapshots": snapshots,
            "parked_tasks": parked,
            "backoff": backoff_stats,
            "cooldown": cooldown_summary,
        }

    return router
