#!/usr/bin/env python3
"""Test 4 — timing & concurrency + carousel (multi-image) vision calls.

Answers two review red flags with measurements instead of assumptions:

  RF3: 4 stores x up to 3 images sequential over one tool call WILL
       blow a 90-180s gateway timeout? -> measure sequential wall time
       vs ThreadPoolExecutor(4) wall time on the user's Coding Plan.

  EC1: butchers split one weekly price list across 2-3 images in ONE
       post. Guard: pass the post's images TOGETHER in a single vision
       call -> the model returns one merged deal list. Verify the
       merged parse works (no duplicated/conflicting items).

All calls go to the user's zlm_url Coding Plan endpoint (glm-5.3-flash,
$0 marginal cost). Keys are never printed.

Run: uv run --with requests --with pillow python test4_concurrency.py
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test2_vision_json import (  # noqa: E402
    _load_env, extract_json, validate_response, SCHEMA_PROMPT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CANDIDATES = HERE / "flyer_candidates"
IMAGES = [
    CANDIDATES / "793000563_974519488990445_958412622832487626_n.jpg",
    CANDIDATES / "791684067_974519485657112_1146670893586121599_n.jpg",
    CANDIDATES / "627810811_799423749833354_6126125786713901760_n.jpg",
    CANDIDATES / "590397717_849844164074664_5305031435323808517_n.jpg",
]


def _endpoint_and_key() -> tuple[str, str]:
    for parent in [HERE, *HERE.parents]:
        if (parent / ".env").exists():
            with open(parent / ".env", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        import os
                        os.environ.setdefault(k.strip(), v.strip("\"' "))
            break
    import os
    url = os.getenv("zlm_url") or os.getenv("ZLM_URL")
    key = os.getenv("zlm_claw") or os.getenv("ZLM_CLAW")
    if not url or not key:
        raise SystemExit("zlm_url / zlm_claw missing from .env")
    if not url.rstrip("/").endswith("chat/completions"):
        url = url.rstrip("/") + "/chat/completions"
    return url, key


def _content_part(path: Path) -> dict:
    b64 = Path(path).read_bytes()
    import base64
    return {"type": "image_url",
            "image_url": {"url":
                          f"data:image/jpeg;base64,"
                          f"{base64.b64encode(b64).decode()}"}}


def vision_call(url: str, key: str, images: list[Path],
                model: str = "glm-5.3-flash",
                max_tokens: int = 2200) -> tuple[int, str, dict]:
    """One vision call with 1..n images. Returns (status, body, usage)."""
    content = [{"type": "text", "text": SCHEMA_PROMPT}]
    content += [_content_part(p) for p in images]
    resp = requests.post(
        url, headers={"Authorization": f"Bearer {key}",
                      "Content-Type": "application/json"},
        json={"model": model, "max_tokens": max_tokens,
              "messages": [{"role": "user", "content": content}]},
        timeout=120)
    try:
        data = resp.json()
    except ValueError:
        return resp.status_code, resp.text[:200], {}
    if resp.status_code != 200:
        body = resp.text[:200].replace(key, "***")
        return resp.status_code, body, {}
    return (resp.status_code,
            data["choices"][0]["message"]["content"],
            {"usage": data.get("usage", {}),
             "finish_reason": data["choices"][0].get("finish_reason")})


def main() -> int:
    url, key = _endpoint_and_key()
    print(f"endpoint: {url}")
    images = [p for p in IMAGES if p.exists()]
    print(f"images: {len(images)}\n")

    # ---- 1. sequential baseline (also verifies each image parses) ----
    seq_times = []
    for p in images:
        t0 = time.monotonic()
        status, body, meta = vision_call(url, key, [p])
        dt = time.monotonic() - t0
        seq_times.append(dt)
        deals, errs = ([], []) if status != 200 else validate_response(
            extract_json(body))
        print(f"single  {p.name[:20]:22} {dt:5.1f}s  status={status}  "
              f"deals={len(deals)}  errs={len(errs)}  "
              f"finish={meta.get('finish_reason')}")
    seq_total = sum(seq_times)
    print(f"sequential total: {seq_total:.1f}s\n")

    # ---- 2. concurrent run (ThreadPoolExecutor, 4 workers) ----
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {p: pool.submit(vision_call, url, key, [p])
                   for p in images}
        conc_results = {p: f.result() for p, f in futures.items()}
    conc_total = time.monotonic() - t0
    for p, (status, body, meta) in conc_results.items():
        deals, errs = ([], []) if status != 200 else validate_response(
            extract_json(body))
        print(f"parallel {p.name[:20]:21} status={status}  "
              f"deals={len(deals)}  errs={len(errs)}")
    print(f"concurrent total (4 workers): {conc_total:.1f}s  "
          f"-> speedup x{seq_total / conc_total:.1f}\n")

    # ---- 3. carousel guard: two images in ONE call ----
    t0 = time.monotonic()
    status, body, meta = vision_call(url, key, images[:2], max_tokens=3000)
    dt = time.monotonic() - t0
    if status != 200:
        print(f"multi-image call FAILED: {status} {body}")
        return 1
    payload = extract_json(body)
    deals, errs = validate_response(payload)
    print(f"multi-image (2 imgs, 1 call): {dt:.1f}s  status={status}  "
          f"deals={len(deals)}  errs={len(errs)}  "
          f"finish={meta.get('finish_reason')}")
    for d in deals:
        print(f"  {d['item']!r:32} ${d['price']:>7} [{d['price_kind']}] "
              f"({d.get('category')})")
    names = [d["item"].lower() for d in deals]
    dupes = {n for n in names if names.count(n) > 1}
    print(f"exact duplicate items across merged images: "
          f"{sorted(dupes) if dupes else 'none'}")

    # ---- verdict ----
    worst_single = max(seq_times)
    print("\nVERDICT")
    print(f"  sequential 4-store worst case: {seq_total:.0f}s "
          f"{'EXCEEDS' if seq_total > 90 else 'under'} a 90s gateway "
          f"timeout")
    print(f"  concurrent (4 workers):        {conc_total:.0f}s "
          f"{'EXCEEDS' if conc_total > 90 else 'under'} a 90s gateway "
          f"timeout")
    print(f"  single-call latency ceiling:   {worst_single:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
