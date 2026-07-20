"""
Lightweight usage tracker — logs per-request token/cost to JSONL file.
Aggregated by /api/v1/usage/stats and /api/v1/usage/recent.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from services.config import DATA_DIR

USAGE_LOG_PATH = DATA_DIR / "usage_log.jsonl"


def log_usage(
    model: str = "",
    endpoint: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    duration_ms: int = 0,
    status: str = "success",
    error: str = "",
    started_at: str = "",
) -> None:
    """Log a single API request's usage data."""
    entry = {
        "ts": time.time(),
        "model": model,
        "endpoint": endpoint,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "duration_ms": duration_ms,
        "status": status,
        "error": error,
        "started_at": started_at or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    try:
        USAGE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # non-critical


def get_usage_stats(period: str = "30d") -> dict:
    """Aggregate usage stats from log file."""
    if not USAGE_LOG_PATH.exists():
        return {
            "totalRequests": 0, "totalPromptTokens": 0, "totalCompletionTokens": 0,
            "totalTokens": 0, "totalCost": 0, "successRate": 0,
            "activeAccounts": 0, "totalAccounts": 0,
        }

    now = time.time()
    if period == "today":
        cutoff = now - 86400
    elif period == "24h":
        cutoff = now - 86400
    elif period == "7d":
        cutoff = now - 7 * 86400
    elif period == "30d":
        cutoff = now - 30 * 86400
    elif period == "60d":
        cutoff = now - 60 * 86400
    else:
        cutoff = now - 30 * 86400

    total_requests = 0
    total_success = 0
    total_prompt = 0
    total_completion = 0
    recent_models: dict[str, int] = {}

    try:
        lines = USAGE_LOG_PATH.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("ts", 0) < cutoff:
                continue
            total_requests += 1
            if entry.get("status") == "success":
                total_success += 1
            total_prompt += entry.get("prompt_tokens", 0)
            total_completion += entry.get("completion_tokens", 0)
            model = entry.get("model", "unknown")
            recent_models[model] = (recent_models.get(model, 0) + 1)
    except Exception:
        pass

    total_tokens = total_prompt + total_completion
    # Estimate cost (same rates as before)
    total_cost = (total_prompt / 1000) * 0.002 + (total_completion / 1000) * 0.006

    # Also include account-based stats
    from services.account_service import account_service
    accounts = account_service.list_accounts()

    return {
        "totalRequests": total_requests,
        "totalPromptTokens": total_prompt,
        "totalCompletionTokens": total_completion,
        "totalTokens": total_tokens,
        "totalCost": round(total_cost, 2),
        "successRate": round((total_success / total_requests * 100), 1) if total_requests > 0 else 0,
        "activeAccounts": sum(1 for a in accounts if a.get("status") == "active"),
        "totalAccounts": len(accounts),
        "topModels": dict(sorted(recent_models.items(), key=lambda x: -x[1])[:5]),
    }


def get_recent_requests(limit: int = 25) -> list[dict]:
    """Get recent request entries for the Recent Requests table."""
    if not USAGE_LOG_PATH.exists():
        return []

    result: list[dict] = []
    try:
        lines = USAGE_LOG_PATH.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            result.append({
                "model": entry.get("model", "unknown"),
                "promptTokens": entry.get("prompt_tokens", 0),
                "completionTokens": entry.get("completion_tokens", 0),
                "duration_ms": entry.get("duration_ms", 0),
                "status": entry.get("status", "success"),
                "started_at": entry.get("started_at", ""),
                "error": entry.get("error", ""),
            })
            if len(result) >= limit:
                break
    except Exception:
        pass
    return result


def _bucket_key(dt: datetime, granularity: str) -> str:
    """Map a datetime to its bucket key for the given granularity."""
    if granularity == "week":
        monday = dt - timedelta(days=dt.weekday())
        return monday.strftime("%Y-%m-%d")
    if granularity == "month":
        return dt.strftime("%Y-%m")
    return dt.strftime("%Y-%m-%d")


_PERIOD_DAYS = {"today": 1, "24h": 1, "7d": 7, "30d": 30, "60d": 60}


def get_usage_timeseries(granularity: str = "day", period: str = "30d") -> dict:
    """Per-provider token usage bucketed over time for the dashboard chart.

    period: time range ("today"/"24h"/"7d"/"30d"/"60d").
    granularity: bucket size within that range ("day" | "week" | "month").
    Provider is the model prefix (e.g. "gemini/gemini-2.5-pro" -> "gemini").
    Returns: {granularity, period, providers: [...], series: [{label, <provider>: tokens, ...}]}.
    """
    if granularity not in {"day", "week", "month"}:
        granularity = "day"
    range_days = _PERIOD_DAYS.get(period, 30)

    now = datetime.now()
    cutoff_dt = now - timedelta(days=range_days)  # rolling cutoff — matches get_usage_stats
    cutoff_ts = cutoff_dt.timestamp()
    start = cutoff_dt
    buckets: list[tuple[str, str]] = []  # (key, label) ordered oldest -> newest
    if granularity == "day":
        cur = datetime(start.year, start.month, start.day)
        end = datetime(now.year, now.month, now.day)
        while cur <= end:
            buckets.append((cur.strftime("%Y-%m-%d"), cur.strftime("%b %d")))
            cur += timedelta(days=1)
    elif granularity == "week":
        cur = start - timedelta(days=start.weekday())  # Monday of the start week
        cur = datetime(cur.year, cur.month, cur.day)
        end = now - timedelta(days=now.weekday())
        end = datetime(end.year, end.month, end.day)
        while cur <= end:
            buckets.append((cur.strftime("%Y-%m-%d"), cur.strftime("%b %d")))
            cur += timedelta(weeks=1)
    else:  # month — one bucket per calendar month touched by the range
        year, month = start.year, start.month
        while (year, month) <= (now.year, now.month):
            d = datetime(year, month, 1)
            buckets.append((d.strftime("%Y-%m"), d.strftime("%b %y")))
            month += 1
            if month > 12:
                month = 1
                year += 1

    key_to_idx = {key: idx for idx, (key, _) in enumerate(buckets)}
    totals: list[dict[str, int]] = [{} for _ in buckets]
    agg_prompt = [0] * len(buckets)
    agg_completion = [0] * len(buckets)
    providers_set: set[str] = set()

    if USAGE_LOG_PATH.exists():
        try:
            lines = USAGE_LOG_PATH.read_text(encoding="utf-8").splitlines()
            for line in lines:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = entry.get("ts", 0)
                if not ts or ts < cutoff_ts:
                    continue
                idx = key_to_idx.get(_bucket_key(datetime.fromtimestamp(ts), granularity))
                if idx is None:
                    continue
                model = entry.get("model", "") or "unknown"
                provider = (model.split("/")[0] if "/" in model else model) or "unknown"
                prompt = entry.get("prompt_tokens", 0)
                completion = entry.get("completion_tokens", 0)
                tokens = entry.get("total_tokens", 0) or (prompt + completion)
                providers_set.add(provider)
                totals[idx][provider] = totals[idx].get(provider, 0) + tokens
                agg_prompt[idx] += prompt
                agg_completion[idx] += completion
        except Exception:
            pass

    providers = sorted(providers_set)
    series: list[dict[str, object]] = []
    for idx, (_, label) in enumerate(buckets):
        row: dict[str, object] = {"label": label}
        for provider in providers:
            row[provider] = totals[idx].get(provider, 0)
        # Aggregate fields (same cost formula as get_usage_stats) — drives the Usage Trend chart.
        row["__tokens"] = agg_prompt[idx] + agg_completion[idx]
        row["__cost"] = round((agg_prompt[idx] / 1000) * 0.002 + (agg_completion[idx] / 1000) * 0.006, 4)
        series.append(row)

    return {"granularity": granularity, "period": period, "providers": providers, "series": series}


def get_usage_daily(days: int = 14) -> dict:
    """Per-day totals for the last N calendar days (inclusive of today).

    Fills empty days with zeros so chart axes stay continuous.
    Returns::

        {
          "days": 14,
          "series": [
            {"date": "2026-07-05", "label": "Jul 05",
             "requests": 0, "tokens": 0, "prompt_tokens": 0,
             "completion_tokens": 0, "cost": 0.0, "success": 0},
            ...
          ],
          "totals": {"requests": …, "tokens": …, "cost": …}
        }
    """
    try:
        days = max(1, min(int(days or 14), 90))
    except (TypeError, ValueError):
        days = 14

    now = datetime.now()
    # Oldest day at index 0
    day_list: list[datetime] = []
    for i in range(days - 1, -1, -1):
        d = now - timedelta(days=i)
        day_list.append(datetime(d.year, d.month, d.day))

    keys = [d.strftime("%Y-%m-%d") for d in day_list]
    key_to_idx = {k: i for i, k in enumerate(keys)}
    reqs = [0] * days
    prompt = [0] * days
    completion = [0] * days
    success = [0] * days

    cutoff_ts = day_list[0].timestamp()
    if USAGE_LOG_PATH.exists():
        try:
            for line in USAGE_LOG_PATH.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = entry.get("ts", 0)
                if not ts or ts < cutoff_ts:
                    continue
                key = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                idx = key_to_idx.get(key)
                if idx is None:
                    continue
                reqs[idx] += 1
                p = int(entry.get("prompt_tokens", 0) or 0)
                c = int(entry.get("completion_tokens", 0) or 0)
                prompt[idx] += p
                completion[idx] += c
                if entry.get("status") == "success":
                    success[idx] += 1
        except Exception:
            pass

    series: list[dict] = []
    tot_req = tot_tok = 0
    tot_cost = 0.0
    for i, d in enumerate(day_list):
        tok = prompt[i] + completion[i]
        cost = round((prompt[i] / 1000) * 0.002 + (completion[i] / 1000) * 0.006, 4)
        tot_req += reqs[i]
        tot_tok += tok
        tot_cost += cost
        series.append({
            "date": keys[i],
            "label": d.strftime("%b %d"),
            "requests": reqs[i],
            "tokens": tok,
            "prompt_tokens": prompt[i],
            "completion_tokens": completion[i],
            "cost": cost,
            "success": success[i],
        })

    return {
        "days": days,
        "series": series,
        "totals": {
            "requests": tot_req,
            "tokens": tot_tok,
            "cost": round(tot_cost, 2),
        },
    }


def get_active_providers(hours: int = 24) -> list[str]:
    """Return list of model prefixes that have been used in the last N hours.
    Used to filter topology to show only actively used providers."""
    if not USAGE_LOG_PATH.exists():
        return []

    cutoff = time.time() - hours * 3600
    used_models: set[str] = set()
    try:
        lines = USAGE_LOG_PATH.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("ts", 0) < cutoff:
                continue
            model = entry.get("model", "")
            if not model:
                continue
            # Extract provider prefix (e.g., "chatgpt/auto" → "chatgpt")
            prefix = model.split("/")[0] if "/" in model else model
            used_models.add(prefix)
    except Exception:
        pass
    return sorted(used_models)
