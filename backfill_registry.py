#!/usr/bin/env python3
"""
backfill_registry.py
--------------------
Populates downloaded.json by walking the downloaded/ directory and
reconstructing each file's original URL from its local path.

Registry format: { "<domain>": { "<url>": { url, date_downloaded, local_filename } } }

If an existing downloaded.json is in the old flat format it is migrated
automatically. Safe to run multiple times — existing entries are preserved.
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


def load_existing() -> dict:
    """Load and migrate existing registry if present."""
    if not REGISTRY_FILE.exists():
        return {}
    with REGISTRY_FILE.open() as fh:
        data = json.load(fh)
    # Detect old flat format: top-level keys are URLs, not domain names
    if data and next(iter(data)).startswith("http"):
        print("Migrating existing registry to domain-grouped format...")
        migrated: dict = {}
        for url, entry in data.items():
            domain = entry.get("website") or url.split("/")[2]
            new_entry = {k: v for k, v in entry.items() if k != "website"}
            migrated.setdefault(domain, {})[url] = new_entry
        return migrated
    return data


registry = load_existing()
pre_existing = sum(len(v) for v in registry.values())
added = 0

for pdf_path in sorted(OUTPUT_DIR.rglob("*.pdf")):
    # Reconstruct URL: downloaded/<domain>/<path> -> https://<domain>/<path>
    rel = pdf_path.relative_to(OUTPUT_DIR)
    parts = rel.parts
    domain = parts[0]
    url_path = "/".join(parts[1:])
    url = f"https://{domain}/{url_path}"

    if url in registry.get(domain, {}):
        continue  # preserve existing entry

    mtime = datetime.fromtimestamp(pdf_path.stat().st_mtime, tz=timezone.utc)
    registry.setdefault(domain, {})[url] = {
        "url": url,
        "date_downloaded": mtime.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "local_filename": str(rel),
    }
    added += 1

# Atomic write
tmp = REGISTRY_FILE.with_suffix(".tmp")
with tmp.open("w") as fh:
    json.dump(registry, fh, indent=2)
tmp.replace(REGISTRY_FILE)

total = sum(len(v) for v in registry.values())
print(f"Registry saved to {REGISTRY_FILE}")
print(f"  Domains              : {len(registry)}")
print(f"  Pre-existing entries : {pre_existing}")
print(f"  Newly added          : {added}")
print(f"  Total entries        : {total}")
