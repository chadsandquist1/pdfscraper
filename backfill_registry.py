#!/usr/bin/env python3
"""
backfill_registry.py
--------------------
Populates downloaded.json by walking the downloaded/ directory and
reconstructing each file's original URL from its local path.

Safe to run multiple times — existing registry entries are preserved.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

CONFIG_FILE = Path("config.json")
REGISTRY_FILE = Path("downloaded.json")

if not CONFIG_FILE.exists():
    sys.exit(f"Error: '{CONFIG_FILE}' not found. Run from the project root.")

with CONFIG_FILE.open() as fh:
    config = json.load(fh)

OUTPUT_DIR = Path(config.get("output_dir", "downloaded"))

if not OUTPUT_DIR.exists():
    sys.exit(f"Error: output directory '{OUTPUT_DIR}' does not exist.")

# Load existing registry so we don't overwrite entries that have real dates
registry: dict = {}
if REGISTRY_FILE.exists():
    with REGISTRY_FILE.open() as fh:
        registry = json.load(fh)

existing = len(registry)
added = 0

for pdf_path in sorted(OUTPUT_DIR.rglob("*.pdf")):
    # Reconstruct URL: downloaded/<domain>/<path> -> https://<domain>/<path>
    rel = pdf_path.relative_to(OUTPUT_DIR)
    parts = rel.parts
    domain = parts[0]
    url_path = "/".join(parts[1:])
    url = f"https://{domain}/{url_path}"

    if url in registry:
        continue  # preserve existing entry

    mtime = datetime.fromtimestamp(pdf_path.stat().st_mtime, tz=timezone.utc)
    registry[url] = {
        "url": url,
        "website": domain,
        "date_downloaded": mtime.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "local_filename": str(rel),
    }
    added += 1

# Atomic write
tmp = REGISTRY_FILE.with_suffix(".tmp")
with tmp.open("w") as fh:
    json.dump(registry, fh, indent=2)
tmp.replace(REGISTRY_FILE)

print(f"Registry saved to {REGISTRY_FILE}")
print(f"  Pre-existing entries : {existing}")
print(f"  Newly added          : {added}")
print(f"  Total                : {len(registry)}")
