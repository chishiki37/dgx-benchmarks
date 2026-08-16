#!/usr/bin/env python3
"""GSM8K benchmark via direct chat API — bypasses lm-eval-harness.

Use this when lm-eval-harness returns 0% or suspiciously low scores for a
model with a custom chat template (e.g. Muse-Glimmer's to=self/to=user format).

Tests the first 50 questions from the canonical GSM8K test set, extracts
numerical answers, and reports accuracy + timing.

USAGE:
  python3 gsm8k_direct_benchmark.py --url http://NODE:PORT/v1/chat/completions [--max-tokens 4096] [--limit 50]

PREREQUISITES:
  - A running OpenAI-compatible server (llama-server, vLLM, etc.)
  - Internet access to download the GSM8K test set
"""
import requests, json, time, re, sys, argparse

DEFAULT_URL = "http://localhost:8000/v1/chat/completions"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_LIMIT = 50
GSM8K_URL = "https://raw.githubusercontent.com/openai/grade-school-math/master/grade_school_math/data/test.jsonl"

def main():
    parser = argparse.ArgumentParser(description="GSM8K direct API benchmark")
    parser.add_argument("--url", default=DEFAULT_URL, help="Chat completions endpoint URL")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS, help="Max generation tokens (use >=4096 for reasoning models)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Number of questions to test")
    parser.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature")
    parser.add_argument("--output", default=None, help="Output JSON file path")
    args = parser.parse_args()

    print(f"Downloading GSM8K test set...", flush=True)
    r = requests.get(GSM8K_URL, timeout=30)
    lines = r.text.strip().split('\n')
    questions = []
    for line in lines:
        d = json.loads(line)
        match = re.search(r'####\s*(-?[\d,]+(?:\.\d+)?)', d['answer'])
        gt = match.group(1).replace(',', '') if match else None
        questions.append({'question': d['question'], 'answer': gt})

    subset = questions[:args.limit]
    print(f"Loaded {len(questions)} questions, testing first {len(subset)}", flush=True)
    print(f"Endpoint: {args.url}", flush=True)
    print(f"max_tokens={args.max_tokens}, temperature={args.temperature}", flush=True)

    correct = 0
    total = 0
    errors = 0
    failures = []
    start_time = time.time()

    for i, q in enumerate(subset):
        prompt = q['question'] + "\n\nThink step by step. At the end, write your final numerical answer on a new line starting with ####."

        try:
            r = requests.post(args.url, json={
                "model": "qwen38-nvfp4",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": args.max_tokens,
                "temperature": args.temperature,
            }, timeout=300)
            data = r.json()
            resp = data['choices'][0]['message']['content']
            finish = data['choices'][0].get('finish_reason', '')
            usage = data.get('usage', {})
            timings = data.get('timings', {})

            # Extract answer: look for #### N pattern first, then fallback to last number
            match = re.search(r'####\s*(-?[\d,]+(?:\.\d+)?)', resp)
            if not match:
                nums = re.findall(r'-?[\d,]+(?:\.\d+)?', resp)
                predicted = nums[-1].replace(',', '') if nums else None
            else:
                predicted = match.group(1).replace(',', '')

            gt = q['answer']
            is_correct = predicted is not None and gt is not None and float(predicted) == float(gt)

            if is_correct:
                correct += 1
            else:
                failures.append({
                    'question_num': i + 1,
                    'predicted': predicted,
                    'expected': gt,
                    'finish_reason': finish,
                    'completion_tokens': usage.get('completion_tokens', 0),
                    'response_preview': resp[:300],
                })
            total += 1

            elapsed = time.time() - start_time
            avg = elapsed / (i + 1)
            eta = avg * (len(subset) - i - 1)
            status = "OK" if is_correct else "WRONG"
            decode_tps = timings.get('predicted_per_second', 0)

            print(f"[{i+1}/{len(subset)}] {status} pred={predicted} gt={gt} finish={finish} "
                  f"toks={usage.get('completion_tokens',0)} {decode_tps:.0f}tok/s "
                  f"({avg:.1f}s/q, ETA {eta:.0f}s)", flush=True)
            if not is_correct:
                print(f"    Response: {resp[:200]}", flush=True)

        except Exception as e:
            errors += 1
            total += 1
            print(f"[{i+1}/{len(subset)}] ERROR: {e}", flush=True)
            continue

    elapsed = time.time() - start_time
    accuracy = correct / total * 100 if total > 0 else 0

    print(f"\n{'='*50}", flush=True)
    print(f"GSM8K Results (N={len(subset)})", flush=True)
    print(f"  Accuracy: {accuracy:.1f}% ({correct}/{total})", flush=True)
    print(f"  Errors: {errors}", flush=True)
    print(f"  Time: {elapsed:.0f}s ({elapsed/len(subset):.1f}s/question)", flush=True)
    if failures:
        print(f"\n  Failures ({len(failures)}):", flush=True)
        for f in failures:
            ftype = "TRUNCATION" if f['completion_tokens'] >= args.max_tokens * 0.95 else \
                    "EMPTY" if not f['predicted'] else "REASONING"
            print(f"    Q{f['question_num']}: pred={f['predicted']} gt={f['expected']} [{ftype}] "
                  f"({f['completion_tokens']} tokens, finish={f['finish_reason']})", flush=True)

    if args.output:
        results = {
            "accuracy": accuracy,
            "correct": correct,
            "total": total,
            "errors": errors,
            "elapsed_s": elapsed,
            "avg_per_question_s": elapsed / len(subset),
            "max_tokens": args.max_tokens,
            "failures": failures,
        }
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"Saved to {args.output}", flush=True)

if __name__ == "__main__":
    main()
