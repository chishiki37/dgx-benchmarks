#!/usr/bin/env python3
"""HF gated-dataset access check via curl subprocess (curl bounds DNS+IO)."""
import pathlib, subprocess

tok = pathlib.Path.home().joinpath(".cache/huggingface/token").read_text().strip()

def code(url):
    try:
        out = subprocess.run(
            ["curl", "-sI", "-o", "/dev/null", "-w", "%{http_code}",
             "--max-time", "20", "-H", "Authorization: Bearer " + tok, url],
            capture_output=True, text=True, timeout=30)
        return int(out.stdout.strip() or 0)
    except Exception:
        return 0

gpqa = code("https://huggingface.co/datasets/Idavidrein/gpqa/resolve/main/gpqa_diamond.csv")
hle = code("https://huggingface.co/datasets/cais/hle/resolve/main/data/test-00000-of-00001.parquet")
print("gpqa=%d hle=%d" % (gpqa, hle))
