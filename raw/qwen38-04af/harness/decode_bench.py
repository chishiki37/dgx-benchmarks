#!/usr/bin/env python3
"""Streaming decode-speed measurement for vLLM endpoint. Stdlib only."""
import json, sys, time, urllib.request

import os
URL = os.environ.get("BENCH_URL", "http://127.0.0.1:8888/v1/chat/completions")
MODEL = os.environ.get("BENCH_MODEL", "qwen38-27b-unsloth-nvfp4")

def run(prompt, max_tokens, thinking, label):
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": 0.7,
        "top_p": 0.8,
        "chat_template_kwargs": {"enable_thinking": thinking},
    }
    req = urllib.request.Request(
        URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    first = None
    chunks = 0
    usage = None
    with urllib.request.urlopen(req, timeout=600) as r:
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
            if ch:
                delta = ch[0].get("delta") or {}
                if (delta.get("content") or delta.get("reasoning")):
                    if first is None:
                        first = time.perf_counter() - t0
                    chunks += 1
    total = time.perf_counter() - t0
    toks = usage["completion_tokens"] if usage else chunks
    ttft = first if first is not None else float("nan")
    decode = (toks - 1) / (total - ttft) if toks > 1 and total > ttft else float("nan")
    print(f"[{label}] tokens={toks} total={total:.2f}s TTFT={ttft:.2f}s "
          f"e2e={toks/total:.2f} tok/s decode~={decode:.2f} tok/s", flush=True)

if __name__ == "__main__":
    prompt = sys.argv[1] if len(sys.argv) > 1 else (
        "Write a detailed one-page essay on the history of the transistor, "
        "from its invention at Bell Labs through modern FinFET technology.")
    run(prompt, 512, False, "thinking-off 512tok")
    run(prompt, 512, True, "thinking-on  512tok")
    run(prompt, 1024, False, "thinking-off 1024tok")
