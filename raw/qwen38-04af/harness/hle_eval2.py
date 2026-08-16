#!/usr/bin/env python3
"""HLE-text v2: thinking OFF per request, concurrent (ThreadPool), same grading as v1."""
import argparse, glob, json, os, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

def load_hle():
    pats = [
        os.path.expanduser("~/.cache/huggingface/hub/datasets--cais--hle/snapshots/*/data/*.parquet"),
        os.path.expanduser("~/.cache/huggingface/datasets/cais/hle/**/*.parquet"),
    ]
    files = []
    for p in pats:
        files = glob.glob(p, recursive=True)
        if files:
            break
    if not files:
        sys.exit("HLE parquet not found in HF cache")
    import pyarrow.parquet as pq
    rows = []
    for f in files:
        rows.extend(pq.read_table(f).to_pylist())
    return rows

def normalize(s):
    if s is None:
        return ""
    s = str(s).strip().lower()
    s = re.sub("[" + chr(34) + chr(39) + chr(96) + "*_]+", "", s)
    s = s.rstrip(".")
    s = re.sub(r"\s+", " ", s)
    return s

def ask(base_url, model, question, max_tokens):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": question + "\n\nAnswer the question directly. Return ONLY the final answer, with no explanation."}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            d = json.loads(resp.read())
        content = d["choices"][0]["message"].get("content") or ""
        finish = d["choices"][0].get("finish_reason")
        toks = d.get("usage", {}).get("completion_tokens", 0)
        return content.strip(), finish, toks, time.time() - t0
    except Exception as e:
        return "", f"ERROR:{e}", 0, time.time() - t0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--output", default="/tmp/hle.json")
    a = ap.parse_args()

    rows = load_hle()
    text_rows = [r for r in rows if not r.get("image")]
    subset = text_rows[: a.limit]
    print(f"HLE: {len(rows)} total, {len(text_rows)} text-only, using {len(subset)}, concurrency {a.concurrency}", flush=True)

    results = [None] * len(subset)
    correct = 0
    done = 0
    t_start = time.time()

    def work(i, r):
        pred, finish, toks, dt = ask(a.base_url, a.model, r["question"], a.max_tokens)
        gt = r["answer"]
        ok = normalize(pred) == normalize(gt) or normalize(gt) in normalize(pred)
        return i, r, gt, pred, finish, toks, dt, ok

    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        futs = [ex.submit(work, i, r) for i, r in enumerate(subset)]
        for fut in as_completed(futs):
            i, r, gt, pred, finish, toks, dt, ok = fut.result()
            results[i] = {
                "id": r.get("id", i), "category": r.get("category", ""),
                "gt": gt, "pred_tail": pred[-300:], "correct": ok,
                "finish": finish, "tokens": toks, "time_s": round(dt, 1),
            }
            done += 1
            if ok:
                correct += 1
            acc = correct / done
            eta = (time.time() - t_start) / done * (len(subset) - done)
            print(f"[{done}/{len(subset)}] {'OK ' if ok else 'BAD'} gt={gt!r} finish={finish} toks={toks} acc={acc:.3f} ETA {eta/60:.1f}m", flush=True)

    summary = {
        "benchmark": "HLE-text", "n": len(subset), "correct": correct,
        "accuracy": round(correct / len(subset), 4) if subset else 0,
        "model": a.model, "total_time_s": round(time.time() - t_start, 1),
        "mode": "thinking-off, direct-answer, exact-match",
    }
    json.dump({"summary": summary, "results": results}, open(a.output, "w"), indent=2)
    print(json.dumps(summary))

if __name__ == "__main__":
    main()
