#!/usr/bin/env python3
"""Spark Arena-style ladder: ctx_pp (prefill) and ctx_tg (decode under context).
Single request (c1), depths 4K..100K. Stdlib only. Reports TTFT + tok/s."""
import json, time, urllib.request, sys

import os
URL = os.environ.get("BENCH_URL", "http://127.0.0.1:8888/v1/chat/completions")
MODEL = os.environ.get("BENCH_MODEL", "qwen38-27b-unsloth-nvfp4")
BASE = ("The quick brown fox jumps over the lazy dog. " * 3)

def post(payload, stream=False):
    req = urllib.request.Request(
        URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=1200)

def make_prompt(target_tokens):
    """Build a chat prompt with ~target_tokens prompt tokens (calibrated)."""
    reps = max(1, target_tokens // 60)
    text = (BASE * reps)[:reps * len(BASE)]
    for _ in range(3):
        p = {"model": MODEL, "messages": [{"role": "user", "content": text + "\n\nSummarize."}],
             "max_tokens": 1, "temperature": 0}
        with post(p) as r:
            d = json.loads(r.read())
        got = d["usage"]["prompt_tokens"]
        if abs(got - target_tokens) / target_tokens < 0.03:
            break
        text = text[:int(len(text) * target_tokens / got)] if got > 0 else text
        if not text:
            text = BASE
    return text + "\n\nSummarize.", got

def ctx_pp(depth):
    text, ptoks = make_prompt(depth)
    t0 = time.perf_counter()
    with post({"model": MODEL, "messages": [{"role": "user", "content": text}],
               "max_tokens": 16, "temperature": 0}) as r:
        json.loads(r.read())
    ttft = time.perf_counter() - t0
    print(f"ctx_pp @ d{depth}: prompt_tokens={ptoks} e2e={ttft*1000:.0f}ms "
          f"prefill~={ptoks/ttft:.0f} tok/s", flush=True)

def ctx_tg(depth, gen=256):
    text, ptoks = make_prompt(depth)
    payload = {"model": MODEL, "messages": [{"role": "user", "content": text + " Write one paragraph."}],
               "max_tokens": gen, "temperature": 0.7, "stream": True,
               "stream_options": {"include_usage": True},
               "chat_template_kwargs": {"enable_thinking": False}}
    t0 = time.perf_counter()
    first = None
    usage = None
    with post(payload, stream=True) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                d = json.loads(data)
            except Exception:
                continue
            if d.get("usage"):
                usage = d["usage"]
            ch = d.get("choices") or []
            if ch and (ch[0].get("delta") or {}).get("content"):
                if first is None:
                    first = time.perf_counter() - t0
    total = time.perf_counter() - t0
    toks = usage["completion_tokens"] if usage else 0
    ttft = first if first else float("nan")
    dec = (toks - 1) / (total - ttft) if toks > 1 else float("nan")
    print(f"ctx_tg @ d{depth}: prompt_tokens={ptoks} TTFT={ttft*1000:.0f}ms "
          f"gen={toks}tok decode~={dec:.2f} tok/s", flush=True)

if __name__ == "__main__":
    depths = [4096, 8192, 16384, 32768, 65535, 100000]
    if len(sys.argv) > 1:
        depths = [int(x) for x in sys.argv[1].split(",")]
    for d in depths:
        ctx_pp(d)
    for d in depths:
        ctx_tg(d)
