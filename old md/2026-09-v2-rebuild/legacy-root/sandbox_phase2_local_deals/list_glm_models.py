#!/usr/bin/env python3
"""List GLM models on OpenRouter and whether they accept image input."""
import os
import sys

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

for parent in [".", "..", "../..", "../../.."]:
    if os.path.exists(os.path.join(parent, ".env")):
        with open(os.path.join(parent, ".env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())
        break

key = os.getenv("OPENROUTER_API_KEY", "")
resp = requests.get("https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {key}"}, timeout=30)
models = resp.json()["data"]
for m in models:
    mid = m["id"]
    if "glm" in mid.lower():
        modality = m.get("architecture", {}).get("input_modalities", [])
        price_in = float(m["pricing"]["prompt"]) * 1_000_000
        print(f"{mid:45} input={modality} prompt=${price_in:.2f}/M")
