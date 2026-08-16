#!/usr/bin/env python3
"""curl-based HF downloader (IPv6 on this node hangs; curl happy-eyeballs works).

Downloads orcarouter/Qwen3.8-27B-Uncensored-FP8 -> local dir, parallel, resumable,
size-verified against the HF API.
"""
import json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = "orcarouter/Qwen3.8-27B-Uncensored-FP8"
DEST = "/home/vikassridhar/models-local-qwen38fp8/Qwen3.8-27B-Uncensored-FP8"
TOK = open(os.path.expanduser("~/.cache/huggingface/token")).read().strip()
API = "https://huggingface.co/api/models/" + REPO

os.makedirs(DEST, exist_ok=True)

meta = json.loads(subprocess.run(
    ["curl", "-s", "--max-time", "60", "-H", "Authorization: Bearer " + TOK, API],
    capture_output=True, check=True).stdout)
files = {s["rfilename"]: s.get("size") for s in meta.get("siblings", [])}
print("files listed:", len(files), flush=True)

def fetch(name):
    out = os.path.join(DEST, name.replace("/", os.sep))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    url = "https://huggingface.co/%s/resolve/main/%s" % (REPO, name)
    for attempt in range(6):
        r = subprocess.run(["curl", "-sSL", "-f", "--retry", "3", "--retry-delay", "2",
                            "-C", "-", "--max-time", "3600",
                            "-H", "Authorization: Bearer " + TOK,
                            "-o", out, url], capture_output=True)
        # curl rc 33 = range resume no longer possible (file already complete)
        if r.returncode in (0, 33):
            break
        time.sleep(3 * (attempt + 1))
    size = os.path.getsize(out) if os.path.exists(out) else -1
    return name, size, files.get(name)

t0 = time.time()
ok, bad = 0, []
with ThreadPoolExecutor(max_workers=3) as ex:
    futs = {ex.submit(fetch, n): n for n in files}
    for fut in as_completed(futs):
        name, size, want = fut.result()
        if want is None or size == want:
            ok += 1
            print("OK  %-45s %12.3f GB" % (name, size / 1e9) if size > 1e8 else
                  "OK  %-45s %8d B" % (name, size), flush=True)
        else:
            bad.append((name, size, want))
            print("BAD %-45s got %s want %s" % (name, size, want), flush=True)

dt = time.time() - t0
total = sum(os.path.getsize(os.path.join(DEST, f)) for f in files
            if os.path.exists(os.path.join(DEST, f)))
print("SUMMARY: %d ok, %d bad, %.2f GB on disk, %.1f min (%.0f MB/s)" %
      (ok, len(bad), total / 1e9, dt / 60, total / 1e6 / max(dt, 1)), flush=True)
print("DOWNLOAD-DONE" if not bad else "DOWNLOAD-INCOMPLETE", flush=True)
