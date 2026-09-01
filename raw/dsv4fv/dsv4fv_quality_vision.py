#!/usr/bin/env python3
"""Report-06 quality benchmark — post-Mia-hotfix k=3 ablit deployment.

Faithful reproduction of the Aug 12 baseline harnesses (verbatim prompts,
params, extraction, scoring) so results are directly comparable:

- GSM8K harness = ~/gsm8k_benchmark.py (Aug 12):
  prompt prefix "Solve this math problem step by step. At the end, write
  '#### X' where X is your final numerical answer.", temp=0.2,
  max_tokens=8192, 3-strategy extraction, float comparison (tol 0.01)
- HumanEval harness = ~/humaneval_chat_benchmark.py (Aug 12):
  prompt "Complete this Python function. Return ONLY the function
  implementation as Python code (you may include the full function).
  No explanation, no markdown.", temp=0.0, max_tokens=1024 (Report 05
  methodology), </think> split + fence strip + import prepend, exec test

Stdlib only (no requests dependency). Saves per-item results for
failure-set diffing (pitfall #34).
"""
import json, time, re, urllib.request, subprocess, os, tempfile, sys

BASE = "http://localhost:8888/v1/chat/completions"
MODEL = "deepseek-v4-flash-vision-exp"
OUTDIR = "/home/vikassridhar/dsv4fv-results"

def chat(messages, max_tokens, temperature):
    payload = {"model": MODEL, "messages": messages, "max_tokens": max_tokens,
               "temperature": temperature,
               "chat_template_kwargs": {"thinking": False}}
    req = urllib.request.Request(BASE, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())

# --- GSM8K (baseline extraction, verbatim from gsm8k_benchmark.py) ---
def extract_gsm8k(text):
    m = re.findall(r'####\s*(-?[\d,.]+)', text)
    if m:
        return m[-1].replace(',', '').strip()
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    for line in reversed(lines[-8:]):
        if re.search(r'\bkm\b|\bper\b|inciden|for reference', line, re.I):
            continue
        matches = re.findall(r'(?:=|answer is|total is|change is|profit is|interest is|left is)\s*\$?\s*(-?[\d,.]+)', line, re.I)
        if matches:
            return matches[-1].replace(',', '').replace('$', '').strip()
    m = re.findall(r'-?\d+(?:\.\d+)?', text.replace(',', ''))
    if m:
        return m[-1]
    return ""

def run_gsm8k():
    lines = open("/tmp/gsm8k_test.jsonl").read().strip().split("\n")[:50]
    questions = []
    for line in lines:
        d = json.loads(line)
        m = re.search(r'####\s*(-?[\d,.]+)', d['answer'])
        questions.append({"question": d['question'],
                          "expected": m.group(1).replace(',', '') if m else ''})
    correct = 0
    results = []
    t_start = time.time()
    for i, q in enumerate(questions):
        t0 = time.time()
        try:
            resp = chat([{"role": "user", "content":
                "Solve this math problem step by step. At the end, write '#### X' "
                "where X is your final numerical answer.\n\n" + q["question"]}],
                max_tokens=8192, temperature=0.2)
            content = resp["choices"][0]["message"].get("content", "") or ""
            toks = resp.get("usage", {}).get("completion_tokens", 0)
        except Exception as e:
            content, toks = f"ERROR: {e}", 0
        elapsed = time.time() - t0
        got = extract_gsm8k(content)
        try:
            ok = abs(float(got) - float(q["expected"])) < 0.01 if got else False
        except Exception:
            ok = False
        if ok:
            correct += 1
        status = "OK" if ok else ("TIMEOUT" if toks == 0 else "WRONG")
        if not ok:
            print(f"  [{i+1}/50] {status} exp={q['expected']} got={got} ({elapsed:.1f}s, {toks}t)", flush=True)
        results.append({"i": i, "expected": q["expected"], "got": got, "correct": ok,
                        "time_s": round(elapsed, 1), "tokens": toks,
                        "answer_tail": content[-300:] if content else ""})
        if (i + 1) % 10 == 0:
            print(f"  Progress: {i+1}/50, correct={correct}", flush=True)
    out = {"benchmark": "GSM8K", "model": MODEL, "date": "2026-09-01",
           "post_hotfix": True, "harness": "gsm8k_benchmark.py-verbatim",
           "correct": correct, "total": 50, "accuracy": correct * 2.0,
           "total_wall_s": round(time.time() - t_start, 1), "results": results}
    with open(os.path.join(OUTDIR, "dsv4fv-gsm8k.json"), "w") as f:
        json.dump(out, f, indent=2)
    print(f"=== GSM8K: {correct}/50 = {correct*2}% ===", flush=True)

# --- HumanEval (baseline extraction, verbatim from humaneval_chat_benchmark.py) ---
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

def run_humaneval():
    problems = [json.loads(l) for l in open("/tmp/humaneval.jsonl")][:50]
    print(f"Loaded {len(problems)} HumanEval problems", flush=True)
    passed = 0
    results = []
    for i, p in enumerate(problems):
        try:
            resp = chat([{"role": "user", "content":
                "Complete this Python function. Return ONLY the function implementation "
                "as Python code (you may include the full function). No explanation, no markdown.\n\n" + p["prompt"]}],
                max_tokens=1024, temperature=0.0)
            msg = resp["choices"][0]["message"]
            out_txt = msg.get("content") or ""
            fr = resp["choices"][0].get("finish_reason")
        except Exception as e:
            out_txt, fr = f"ERROR: {e}", "error"
        code = extract_code(out_txt, p["prompt"])
        ok = run_test(code, p["test"], p["entry_point"])
        if ok:
            passed += 1
        status = "PASS" if ok else ("TRUNC" if fr == "length" else "BUG")
        print(f"  [{i+1}/50] {status} {p['task_id']} ({fr})", flush=True)
        results.append({"task_id": p["task_id"], "pass": ok, "status": status,
                        "finish": fr, "code_tail": code[-200:], "raw_tail": out_txt[-200:]})
    out = {"benchmark": "HumanEval-chat", "model": MODEL, "date": "2026-08-14",
           "post_hotfix": True, "harness": "humaneval_chat_benchmark.py-verbatim",
           "passed": passed, "total": 50, "pass_at_1": passed * 2.0, "results": results}
    with open(os.path.join(OUTDIR, "report06-humaneval-v2.json"), "w") as f:
        json.dump(out, f, indent=2)
    print(f"=== HumanEval: {passed}/50 = {passed*2}% ===", flush=True)

print("--- GSM8K (baseline harness) ---", flush=True)
run_gsm8k()
print("--- HumanEval (baseline harness) ---", flush=True)
run_humaneval()
print("QUALITY-V2-DONE")
