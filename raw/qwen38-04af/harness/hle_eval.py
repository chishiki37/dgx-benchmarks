#!/usr/bin/env python3
"""HLE (Humanity's Last Exam) text-only subset — direct chat API eval.
Exact-match grading, thinking mode on (server default). Stdlib + pyarrow."""
import argparse, glob, json, os, re, sys, time, urllib.request

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
        sys.exit("HLE parquet not found in HF cache — run: hf download cais/hle --repo-type dataset")
    import pyarrow.parquet as pq
    rows = []
    for f in files:
        t = pq.read_table(f)
        rows.extend(t.to_pylist())
    return rows

def normalize(s):
    if s is None:
        return ""
    s = str(s).strip().lower()
    s = re.sub(r"[\"'`*_]+", "", s)
    s = s.rstrip(".")
    s = re.sub(r"\s+", " ", s)
    return s

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--output", default="/tmp/hle.json")
    a = ap.parse_args()

    rows = load_hle()
    # text-only entries only (skip multimodal rows with images)
    text_rows = []
    for r in rows:
        img = r.get("image")
        if img in (None, "", b"") or (isinstance(img, dict) and not img.get("bytes") and not img.get("path")):
            text_rows.append(r)
    subset = text_rows[: a.limit]
    print(f"HLE: {len(rows)} total rows, {len(text_rows)} text-only, using {len(subset)}", flush=True)

    results = []
    correct = 0
    t_start = time.time()
    for i, r in enumerate(subset):
        q = r["question"]
        gt = r["answer"]
        payload = {
            "model": a.model,
            "messages": [{"role": "user", "content": q + "\n\nAnswer the question directly. Return ONLY the final answer, with no explanation."}],
            "max_tokens": a.max_tokens,
            "temperature": 0.0,
        }
        req = urllib.request.Request(
            a.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=1800) as resp:
                d = json.loads(resp.read())
            msg = d["choices"][0]["message"]
            content = msg.get("content") or ""
            finish = d["choices"][0].get("finish_reason")
            toks = d.get("usage", {}).get("completion_tokens", 0)
        except Exception as e:
            content, finish, toks = "", f"ERROR:{e}", 0
        pred = content.strip()
        ok = normalize(pred) == normalize(gt) or normalize(gt) in normalize(pred)
        if ok:
            correct += 1
        results.append({
            "id": r.get("id", i), "category": r.get("category", ""),
            "gt": gt, "pred_tail": pred[-300:], "correct": ok,
            "finish": finish, "tokens": toks, "time_s": round(time.time() - t0, 1),
        })
        acc = correct / (i + 1)
        eta = (time.time() - t_start) / (i + 1) * (len(subset) - i - 1)
        print(f"[{i+1}/{len(subset)}] {'OK ' if ok else 'BAD'} gt={gt!r} finish={finish} toks={toks} acc={acc:.3f} ETA {eta/60:.1f}m", flush=True)

    summary = {
        "benchmark": "HLE-text", "n": len(subset), "correct": correct,
        "accuracy": round(correct / len(subset), 4) if subset else 0,
        "model": a.model, "total_time_s": round(time.time() - t_start, 1),
    }
    json.dump({"summary": summary, "results": results}, open(a.output, "w"), indent=2)
    print(json.dumps(summary))

if __name__ == "__main__":
    main()
