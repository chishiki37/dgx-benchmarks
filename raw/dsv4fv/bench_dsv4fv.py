#!/usr/bin/env python3
"""DeepSeek V4 Flash Vision-Exp — decode benchmark harness (fleet battery).

Clone of ds4-link-impact-study/ds4_bench.py (the August ledger harness) with:
- chat_template_kwargs thinking=false per request (Vision-Exp ships DEFAULT_THINKING=max;
  August 0731 baseline numbers were measured thinking-off — this keeps comparability)
- C=6 step added (the recipe's MAX_NUM_SEQS=6 headline concurrency)
- results saved under ~/dsv4fv-results/

Usage: bench_dsv4fv.py <base_url> <model_id> [--label NAME] [--warmup]
"""
import argparse, json, time, sys, threading, statistics
import urllib.request

def chat(base, model, prompt, max_tokens=256, temp=0.2):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": temp,
        "chat_template_kwargs": {"thinking": False},
    }).encode()
    req = urllib.request.Request(base + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)

def decode_toks(base, model, prompt, max_tokens=256):
    """Return (elapsed_s, completion_tokens, content)."""
    t0 = time.time()
    d = chat(base, model, prompt, max_tokens=max_tokens)
    dt = time.time() - t0
    ct = d["usage"]["completion_tokens"]
    content = d["choices"][0]["message"]["content"] or ""
    return dt, ct, content

def sanity(base, model):
    print("  [sanity] factual check...", flush=True)
    dt, ct, content = decode_toks(base, model, "What is the capital of France? Answer in one short sentence.", 60)
    ok = "paris" in content.lower()
    print(f"  [sanity] {ct} toks in {dt:.1f}s -> {content!r}  {'OK' if ok else 'SUSPICIOUS'}", flush=True)
    return ok

def single_stream(base, model, n=5, max_tokens=256):
    """Sequential decode, report median tok/s."""
    rates = []
    for i in range(n):
        dt, ct, _ = decode_toks(base, model, "Write a detailed technical explanation of how transformer attention works.", max_tokens)
        rates.append(ct / dt)
        print(f"    run {i+1}: {ct} toks / {dt:.1f}s = {ct/dt:.1f} tok/s", flush=True)
    return statistics.median(rates)

def concurrent(base, model, concurrency, n_req=8, max_tokens=256):
    """Aggregate throughput at given concurrency."""
    results = [None] * n_req
    def worker(i):
        results[i] = decode_toks(base, model, "Write a detailed technical explanation of how transformer attention works.", max_tokens)
    threads = []
    t0 = time.time()
    for i in range(n_req):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t); t.start()
        if (i + 1) % concurrency == 0:
            for t in threads: t.join()
            threads = []
    for t in threads: t.join()
    dt = time.time() - t0
    total = sum(r[1] for r in results)
    return total / dt, dt, total

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base"); ap.add_argument("model")
    ap.add_argument("--label", default="")
    ap.add_argument("--warmup", action="store_true")
    ap.add_argument("--max-tokens", type=int, default=256)
    a = ap.parse_args()

    print(f"=== Benchmark: {a.label or a.base} ===", flush=True)
    print(f"  endpoint: {a.base}  model: {a.model}", flush=True)

    if a.warmup:
        print("  [warmup] Triton JIT pre-compile...", flush=True)
        decode_toks(a.base, a.model, "Hello", 20)
        decode_toks(a.base, a.model, "Explain the water cycle in detail.", 200)
        concurrent(a.base, a.model, 4, n_req=4, max_tokens=50)
        print("  [warmup] done", flush=True)

    ok = sanity(a.base, a.model)
    if not ok:
        print("  !! SANITY FAILED — model may be returning garbage. Aborting.", flush=True)
        sys.exit(2)

    print("  [single-stream] 5 runs...", flush=True)
    ss = single_stream(a.base, a.model, n=5, max_tokens=a.max_tokens)

    print("  [C=4] aggregate...", flush=True)
    c4, c4_dt, c4_tok = concurrent(a.base, a.model, 4, n_req=8, max_tokens=a.max_tokens)
    print(f"    {c4_tok} toks / {c4_dt:.1f}s = {c4:.1f} tok/s aggregate", flush=True)

    print("  [C=6] aggregate...", flush=True)
    c6, c6_dt, c6_tok = concurrent(a.base, a.model, 6, n_req=6, max_tokens=a.max_tokens)
    print(f"    {c6_tok} toks / {c6_dt:.1f}s = {c6:.1f} tok/s aggregate", flush=True)

    print("  [C=8] aggregate (seqs cap 6 — measures queueing)...", flush=True)
    c8, c8_dt, c8_tok = concurrent(a.base, a.model, 8, n_req=8, max_tokens=a.max_tokens)
    print(f"    {c8_tok} toks / {c8_dt:.1f}s = {c8:.1f} tok/s aggregate", flush=True)

    result = {
        "label": a.label, "endpoint": a.base, "model": a.model,
        "single_stream_tok_s": round(ss, 1),
        "c4_aggregate_tok_s": round(c4, 1),
        "c6_aggregate_tok_s": round(c6, 1),
        "c8_aggregate_tok_s": round(c8, 1),
        "max_tokens": a.max_tokens,
        "thinking": False,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
    }
    print("\n=== RESULT ===", flush=True)
    print(json.dumps(result, indent=2), flush=True)
    with open(f"/home/vikassridhar/dsv4fv-results/bench_{a.label or 'unnamed'}.json", "w") as f:
        json.dump(result, f, indent=2)
    print(f"  saved: ~/dsv4fv-results/bench_{a.label or 'unnamed'}.json", flush=True)

if __name__ == "__main__":
    main()
