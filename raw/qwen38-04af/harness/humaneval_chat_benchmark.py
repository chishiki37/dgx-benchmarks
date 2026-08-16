#!/usr/bin/env python3
"""HumanEval runner for CHAT-NATIVE REASONING models (Nemotron, GLM, DeepSeek-R1
chat variants) served over an OpenAI-compatible API.

Why this exists: base/completion models (Muse-Glimmer) use raw /v1/completions,
but chat-tuned reasoning models wrap code in markdown fences, put reasoning in a
separate field, and drop the prompt's import lines. Naive harnesses then report
38-58% when the model is actually ~92%. This script applies the 3 fixes:
  1. use /v1/chat/completions (reasoning lands in `reasoning`, code in `content`)
  2. strip markdown fences + anything after </think>
  3. prepend the prompt's import/from lines (avoids NameError on List/Optional)

Usage:
  python3 humaneval_chat_benchmark.py --base-url http://NODE:8001/v1 \
      --model my-model --limit 50 --output /tmp/humaneval.json
"""
import json, sys, os, re, argparse, urllib.request, tempfile, subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", required=True)
parser.add_argument("--model", required=True)
parser.add_argument("--data", default="", help="path to HumanEval.jsonl (else downloads)")
parser.add_argument("--limit", type=int, default=50)
parser.add_argument("--max-tokens", type=int, default=8192)
parser.add_argument("--output", default="/tmp/humaneval-chat.json")
args = parser.parse_args()

if args.data and os.path.exists(args.data):
    problems = [json.loads(l) for l in open(args.data)][:args.limit]
else:
    import gzip, io
    url = "https://github.com/openai/human-eval/raw/master/data/HumanEval.jsonl.gz"
    with urllib.request.urlopen(url, timeout=30) as r:
        gz = gzip.GzipFile(fileobj=io.BytesIO(r.read()))
    problems = [json.loads(l) for l in gz.read().decode().splitlines()][:args.limit]
print(f"Loaded {len(problems)} HumanEval problems", flush=True)
BASE = args.base_url.rstrip('/')

def chat(prompt):
    body = json.dumps({
        "model": args.model,
        "messages": [{"role": "user", "content":
            "Complete this Python function. Return ONLY the function implementation "
            "as Python code (you may include the full function). No explanation, no markdown.\n\n" + prompt}],
        "temperature": 0.0,
        "max_tokens": args.max_tokens,
    }).encode()
    req = urllib.request.Request(f"{BASE}/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.loads(r.read())
        m = d["choices"][0]["message"]
        return m.get("content") or "", d["choices"][0].get("finish_reason")
    except Exception as e:
        return f"ERROR: {e}", "error"

def extract_code(text, prompt):
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    m = re.search(r"```(?:python)?\n(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    text = re.sub(r"^```.*$", "", text, flags=re.M).strip()
    if re.search(r"^\s*def\s", text, re.M):
        body = text
    else:
        body = prompt + text
    imports = "\n".join(l for l in prompt.split("\n")
                        if l.strip().startswith(("import ", "from ")))
    if imports and imports not in body:
        body = imports + "\n\n" + body
    return body

def run_test(code, test, entry_point):
    prog = code + "\n\n" + test + f"\ncheck({entry_point})\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(prog); path = f.name
    try:
        return subprocess.run([sys.executable, path], capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False
    finally:
        os.unlink(path)

passed = 0
results = []
for i, p in enumerate(problems):
    out, fr = chat(p["prompt"])
    code = extract_code(out, p["prompt"])
    ok = run_test(code, p["test"], p["entry_point"])
    if ok: passed += 1
    status = "PASS" if ok else ("TRUNC" if fr == "length" else "BUG")
    print(f"  [{i+1}/{len(problems)}] {status} {p['task_id']} ({fr})", flush=True)
    results.append({"task_id": p["task_id"], "pass": ok, "status": status,
                    "finish": fr, "code_tail": code[-200:], "raw_tail": out[-200:]})

acc = passed / len(problems) * 100
print(f"\n{'='*50}\n  HumanEval(chat): {passed}/{len(problems)} pass@1 ({acc:.1f}%)\n{'='*50}")
json.dump({"benchmark": "HumanEval-chat", "model": args.model, "passed": passed,
           "total": len(problems), "pass_at_1": acc, "results": results},
          open(args.output, 'w'), indent=2)
print(f"Saved to {args.output}")
