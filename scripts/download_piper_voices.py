#!/usr/bin/env python3
"""Download Piper ONNX voices from this repo's GitHub Release (not git LFS / not image).

Usage:
  python scripts/download_piper_voices.py --pack minimal
  python scripts/download_piper_voices.py --pack full
  python scripts/download_piper_voices.py --voice ngochuyennew --out data/piper

Auth (private repo):
  export GH_TOKEN=...   # or GITHUB_TOKEN
  # or: gh auth login
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "voices" / "piper" / "voices.json"
DEFAULT_OUT = ROOT / "data" / "piper"
API = "https://api.github.com"


def _token() -> str:
    return (
        os.environ.get("GH_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
        or os.environ.get("GH_PAT")
        or ""
    ).strip()


def _load_manifest() -> dict:
    if not MANIFEST.is_file():
        print(f"Missing manifest: {MANIFEST}", file=sys.stderr)
        sys.exit(1)
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _headers(token: str, *, for_asset: bool = False) -> dict[str, str]:
    h = {
        "User-Agent": "chatgpt2api-piper-download",
        "Accept": (
            "application/octet-stream"
            if for_asset
            else "application/vnd.github+json"
        ),
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _get_json(url: str, token: str) -> dict | list:
    req = urllib.request.Request(url, headers=_headers(token))
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def _resolve_assets(repo: str, tag: str, token: str) -> dict[str, int]:
    """filename -> asset_id"""
    url = f"{API}/repos/{repo}/releases/tags/{tag}"
    try:
        rel = _get_json(url, token)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        print(
            f"Cannot read release {tag} of {repo}: HTTP {e.code}\n{body}\n"
            f"Hint: private repo needs GH_TOKEN or `gh auth login`.",
            file=sys.stderr,
        )
        sys.exit(2)
    assets = rel.get("assets") or []
    out: dict[str, int] = {}
    for a in assets:
        name = a.get("name")
        aid = a.get("id")
        if name and aid is not None:
            out[str(name)] = int(aid)
    if not out:
        print(
            f"Release {tag} has no assets yet. Upload voices first "
            f"(gh release upload {tag} ...).",
            file=sys.stderr,
        )
        sys.exit(3)
    return out


def _download_asset(
    repo: str,
    asset_id: int,
    dest: Path,
    token: str,
    *,
    expected_size: int | None = None,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"{API}/repos/{repo}/releases/assets/{asset_id}"
    req = urllib.request.Request(url, headers=_headers(token, for_asset=True))
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(req, timeout=600) as resp, tmp.open("wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        size = tmp.stat().st_size
        if expected_size and size != expected_size:
            print(
                f"WARN {dest.name}: size {size} != expected {expected_size}",
                file=sys.stderr,
            )
        tmp.replace(dest)
    except Exception:
        if tmp.is_file():
            tmp.unlink(missing_ok=True)
        raise


def _select_ids(manifest: dict, pack: str | None, voices: list[str]) -> list[str]:
    if voices:
        return list(dict.fromkeys(voices))
    packs = manifest.get("packs") or {}
    pack = pack or "minimal"
    if pack not in packs:
        print(f"Unknown pack {pack!r}. Known: {', '.join(packs)}", file=sys.stderr)
        sys.exit(1)
    return list(packs[pack])


def main() -> int:
    ap = argparse.ArgumentParser(description="Download Piper voices from GitHub Release")
    ap.add_argument("--pack", choices=["minimal", "full"], help="Voice pack")
    ap.add_argument("--voice", action="append", default=[], help="Voice id (repeatable)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output directory")
    ap.add_argument("--list", action="store_true", help="List voices and exit")
    ap.add_argument("--force", action="store_true", help="Re-download even if exists")
    args = ap.parse_args()

    manifest = _load_manifest()
    by_id = {v["id"]: v for v in manifest.get("voices") or []}

    if args.list:
        for vid, v in sorted(by_id.items()):
            mb = (v.get("size_bytes") or 0) / (1024 * 1024)
            flag = " (default)" if v.get("default") or vid == manifest.get("default_voice") else ""
            print(f"{vid:20} {mb:6.1f} MB  lang={v.get('language')}{flag}")
        return 0

    if not args.pack and not args.voice:
        args.pack = "minimal"

    ids = _select_ids(manifest, args.pack, args.voice)
    for vid in ids:
        if vid not in by_id:
            print(f"Unknown voice id: {vid}", file=sys.stderr)
            return 1

    repo = str(manifest.get("repo") or "TriTue2011/chatgpt2api")
    tag = str(manifest.get("release_tag") or "piper-voices-v1")
    token = _token()
    if not token:
        # try gh
        import subprocess
        try:
            token = subprocess.check_output(
                ["gh", "auth", "token"], text=True, stderr=subprocess.DEVNULL
            ).strip()
        except Exception:
            token = ""
    if not token:
        print(
            "Need auth for private repo: set GH_TOKEN or run `gh auth login`.",
            file=sys.stderr,
        )
        return 2

    print(f"Release {repo}@{tag} -> {args.out}")
    assets = _resolve_assets(repo, tag, token)
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    ok = 0
    for vid in ids:
        v = by_id[vid]
        files = v.get("files") or {}
        for key in ("onnx", "config"):
            name = files.get(key)
            if not name:
                continue
            dest = out / name
            if dest.is_file() and not args.force:
                print(f"skip  {name} (exists)")
                ok += 1
                continue
            if name not in assets:
                print(f"MISSING asset on release: {name}", file=sys.stderr)
                continue
            exp = v.get("size_bytes") if key == "onnx" else v.get("config_size_bytes")
            print(f"get   {name} ...")
            try:
                _download_asset(repo, assets[name], dest, token, expected_size=exp)
                print(f"ok    {name} ({dest.stat().st_size} bytes)")
                ok += 1
            except Exception as e:
                print(f"FAIL  {name}: {e}", file=sys.stderr)

    print(f"Done. {ok} file(s) under {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
