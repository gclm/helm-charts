#!/usr/bin/env python3
"""
Resolve :latest-only appstore apps to their newest semver image tag.

Reads upstream checkout, finds apps/*/latest dirs, queries the registry v2
tags API (docker.io via auth.docker.io, ghcr.io via its token endpoint),
picks the newest semver tag, and writes converter/auto-tags.yaml:

    teable: "1.13.1"
    excalidraw: "0.17.6"

That file is a converter input (committed to the repo): same file + same
upstream => identical charts (idempotency gate unaffected). A resolved tag
that no longer matches upstream keeps working until the next successful run.

Network failures on individual apps are tolerated (app left out of the map,
kept skipped); total failure (bad args) exits non-zero.
"""
import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

import yaml

UA = {"Accept": "application/json", "User-Agent": "helm-charts-converter/1"}


def http_json(url, token=None):
    headers = dict(UA)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def registry_of(image):
    """image without tag -> (auth_url, registry_url, repo)."""
    if image.startswith("ghcr.io/"):
        repo = image[len("ghcr.io/"):]
        return (f"https://ghcr.io/token?scope=repository:{repo}:pull",
                f"https://ghcr.io/v2/{repo}/tags/list?n=1000")
    repo = image if "/" in image else f"library/{image}"
    return (f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull",
            f"https://registry-1.docker.io/v2/{repo}/tags/list?n=1000")


def get_tags(image):
    auth_url, tags_url = registry_of(image)
    token = http_json(auth_url).get("token", "")
    return http_json(tags_url, token).get("tags") or []


def newest_semver(tags):
    """Newest x.y(.z) tag; bare integers (build numbers / sha-ish numerics) don't count."""
    best, best_key = None, None
    for t in tags:
        m = re.fullmatch(r"v?(\d+\.\d+(?:\.\d+)?)", str(t))
        if not m:
            continue
        key = tuple(int(x) for x in m.group(1).split("."))
        if best_key is None or key > best_key:
            best, best_key = t, key
    return best


def main_image(app_dir: Path):
    compose = app_dir / "latest" / "docker-compose.yml"
    if not compose.exists():
        return None
    try:
        data = yaml.safe_load(compose.read_text()) or {}
    except Exception:
        return None
    for svc in (data.get("services") or {}).values():
        if isinstance(svc, dict) and svc.get("image"):
            img = str(svc["image"]).strip()
            if img.startswith("${"):
                return None  # variable image, unresolvable
            return img.rsplit(":", 1)[0] if ":" in img and not img.rsplit(":", 1)[1].isdigit() else img
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default="converter/auto-tags.yaml")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    apps_root = Path(args.src) / "apps"
    results, failures = {}, []
    for app_dir in sorted(apps_root.glob("*/latest")):
        app = app_dir.parent.name
        image = main_image(app_dir.parent)
        if not image:
            print(f"  {app}: no static image, skip")
            continue
        try:
            tag = newest_semver(get_tags(image))
        except Exception as e:  # noqa: BLE001 - per-app network tolerance
            failures.append(f"{app}: {type(e).__name__}: {e}")
            print(f"  {app}: LOOKUP FAILED ({e})")
            continue
        if tag:
            results[app] = tag
            print(f"  {app}: {image}:{tag}")
        else:
            print(f"  {app}: no semver tag on {image} (latest-only upstream)")

    if args.dry_run:
        return

    out = Path(args.out)
    old = {}
    if out.exists():
        old = yaml.safe_load(out.read_text()) or {}
    if old == results:
        print("auto-tags unchanged")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(results, sort_keys=True, default_flow_style=False))
    print(f"wrote {out} ({len(results)} resolved, {len(failures)} lookup failures)")
    for f in failures:
        print(f"  warn: {f}", file=sys.stderr)


if __name__ == "__main__":
    main()
