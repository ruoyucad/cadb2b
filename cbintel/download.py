"""Download raw CanadaBuys CSVs into data/raw/.

Uses conditional requests (ETag / Last-Modified) so re-running only fetches
files that changed. Writes to a .part file first so an interrupted download
never leaves a corrupt CSV behind.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from .sources import QUICK, SOURCES

RAW = Path("data/raw")
META = RAW / "_meta.json"
UA = "cbintel/0.1 (CanadaBuys open-data research)"


def _load_meta() -> dict:
    return json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}


def download(names: list[str] | None = None, quick: bool = False, force: bool = False) -> list[Path]:
    RAW.mkdir(parents=True, exist_ok=True)
    meta = _load_meta()
    selected = names or (QUICK if quick else list(SOURCES))
    got: list[Path] = []

    for name in selected:
        url, _group = SOURCES[name]
        dest = RAW / f"{name}.csv"
        headers = {"User-Agent": UA}
        prev = meta.get(name, {})
        if dest.exists() and not force:
            if prev.get("etag"):
                headers["If-None-Match"] = prev["etag"]
            if prev.get("last_modified"):
                headers["If-Modified-Since"] = prev["last_modified"]

        t0 = time.time()
        try:
            with requests.get(url, headers=headers, stream=True, timeout=(15, 300)) as r:
                if r.status_code == 304:
                    print(f"[skip] {name}: unchanged")
                    got.append(dest)
                    continue
                r.raise_for_status()
                tmp = dest.with_suffix(".csv.part")
                size = 0
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                        size += len(chunk)
                tmp.replace(dest)
                meta[name] = {
                    "url": url,
                    "etag": r.headers.get("ETag"),
                    "last_modified": r.headers.get("Last-Modified"),
                    "bytes": size,
                    "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                print(f"[ok]   {name}: {size/1e6:.1f} MB in {time.time()-t0:.0f}s")
                got.append(dest)
        except requests.RequestException as e:
            # One missing/renamed file shouldn't kill the run.
            print(f"[fail] {name}: {e}")
        META.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return got
