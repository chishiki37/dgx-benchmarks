#!/usr/bin/env python3
"""Quality + speed battery for Qwen3.8-27B-Uncensored-FP8 on 04af.

Mirrors the stage8 campaign battery exactly (order, limits, flags):
  GSM8K(50) -> HumanEval(50) -> IFEval(100) -> GPQA-diamond(100) -> HLE(100)
  -> decode_bench -> arena ladder (quality FIRST, speed LAST — arena can kill servers).

Gates on /tmp/fp8bench/SWEEP_DONE. Markers: BATTERY_DONE / BATTERY_FAILED.
"""
import os, subprocess, sys, time, urllib.request

PORT = 8090
SERVED = "qwen38-fp8"
LABEL = "fp8_uncensored"
OUT = "/tmp/fp8bench"
PY = "/tmp/benchvenv/bin/python"
LMEVAL = "/tmp/benchvenv/bin/lm_eval"
TOK = "/home/vikassridhar/models-local-qwen38fp8/Qwen3.8-27B-Uncensored-FP8"
CHAT = "http://127.0.0.1:%d/v1/chat/completions" % PORT
COMP = "http://127.0.0.1:%d/v1/completions" % PORT
BASE = "http://127.0.0.1:%d/v1" % PORT
LOG = OUT + "/battery_%s.log" % LABEL
BENCH_ENV = dict(os.environ, BENCH_URL=CHAT, BENCH_MODEL=SERVED)


def log(msg):
    line = time.strftime("%H:%M:%S") + " " + msg
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def run(cmd, tag, timeout, env=None):
    log("=== %s ===" % tag)
    t0 = time.time()
    with open(OUT + "/%s_%s.run.log" % (tag.lower(), LABEL), "w") as f:
        try:
            p = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT,
                               env=env or BENCH_ENV, timeout=timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = 124
    log("%s_RC=%d (%.0fs)" % (tag, rc, time.time() - t0))
    return rc


def healthy():
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/v1/models" % PORT, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def main():
    os.makedirs(OUT, exist_ok=True)
    open(LOG, "w").write("battery start %s\n" % time.strftime("%Y-%m-%dT%H:%M:%S%z"))

    # gate: sweep finished (up to 5h)
    for i in range(3600):
        if os.path.exists(OUT + "/SWEEP_DONE"):
            break
        if os.path.exists(OUT + "/SWEEP_FAILED"):
            log("SWEEP_FAILED present — battery aborting")
            open(OUT + "/BATTERY_FAILED", "w").write("sweep failed\n")
            sys.exit(1)
        time.sleep(5)
    if not os.path.exists(OUT + "/SWEEP_DONE"):
        log("sweep gate TIMEOUT — battery aborting")
        open(OUT + "/BATTERY_FAILED", "w").write("sweep gate timeout\n")
        sys.exit(1)
    winner = open(OUT + "/SWEEP_DONE").read().strip()
    log("sweep gate passed (winner=%s)" % winner)

    # gate: server up (up to 20 min)
    for i in range(240):
        if healthy():
            break
        time.sleep(5)
    if not healthy():
        log("server never came up — battery aborting")
        open(OUT + "/BATTERY_FAILED", "w").write("server down\n")
        sys.exit(1)
    log("server healthy")

    # capture server info for the report
    lg = subprocess.run(["docker", "logs", "--tail", "300", "qwen38fp8"],
                        capture_output=True, text=True)
    keep = [l for l in (lg.stderr or lg.stdout).splitlines()
            if any(x in l for x in ("MTP model", "KV cache size", "Maximum concurrency",
                                    "gpu_memory_utilization", "Speculative", "model loading took",
                                    "Capturing CUDA graph"))]
    open(OUT + "/server_info.txt", "w").write("\n".join(keep[-25:]) + "\n")

    # warmup
    for prompt in ("Write one short sentence about the sea.",
                   "Write one short sentence about mountains."):
        try:
            subprocess.run(["curl", "-s", "-m", "300", CHAT,
                            "-H", "Content-Type: application/json",
                            "-d", '{"model":"%s","messages":[{"role":"user","content":"%s"}],'
                                  '"max_tokens":256,"temperature":0}' % (SERVED, prompt)],
                           capture_output=True, timeout=320)
        except Exception:
            pass
    log("warmup done")

    rcs = {}
    rcs["gsm8k"] = run([PY, "/tmp/qbench/gsm8k_fp8.py", "--url", CHAT,
                        "--limit", "50", "--output", OUT + "/gsm8k_%s.json" % LABEL],
                       "GSM8K", 7200)
    rcs["humaneval"] = run([PY, "/tmp/qbench/humaneval_chat_benchmark.py",
                            "--base-url", BASE, "--model", SERVED, "--limit", "50",
                            "--data", "/tmp/qbench/HumanEval.jsonl",
                            "--output", OUT + "/humaneval_%s.json" % LABEL],
                           "HUMANEVAL", 7200)
    rcs["ifeval"] = run([LMEVAL, "--model", "local-chat-completions",
                         "--model_args", "model=%s,base_url=%s,tokenizer=%s,num_concurrent=8,"
                                         "max_retries=3,tokenized_requests=False" % (SERVED, CHAT, TOK),
                         "--apply_chat_template", "--tasks", "ifeval",
                         "--gen_kwargs", "temperature=0,max_tokens=4096", "--limit", "100",
                         "--output_path", OUT + "/ifeval_%s.json" % LABEL],
                        "IFEVAL", 7200)
    rcs["gpqa"] = run([LMEVAL, "--model", "local-completions",
                       "--model_args", "model=%s,base_url=%s,tokenizer=%s,num_concurrent=8,"
                                       "max_retries=3,tokenized_requests=False" % (SERVED, COMP, TOK),
                       "--tasks", "gpqa_diamond_zeroshot", "--limit", "100",
                       "--output_path", OUT + "/gpqa_%s.json" % LABEL],
                      "GPQA", 7200)
    rcs["hle"] = run([PY, "/tmp/qbench/hle_eval2.py", "--base-url", BASE,
                      "--model", SERVED, "--limit", "100", "--concurrency", "4",
                      "--output", OUT + "/hle_%s.json" % LABEL],
                     "HLE", 9000)
    if not healthy():
        log("server died during quality stages — speed stage skipped")
        open(OUT + "/BATTERY_FAILED", "w").write("server died in quality: %s\n" % str(rcs))
        sys.exit(2)
    rcs["decode"] = run(["python3", "/tmp/decode_bench.py"], "DECODE", 2400)
    rcs["arena"] = run(["python3", "/tmp/arena_ladder.py",
                        "2048,4096,8192,16384,32768,51200"], "ARENA", 7200)

    log("battery end; RCs: %s" % str(rcs))
    open(OUT + "/BATTERY_DONE", "w").write(str(rcs))
    log("BATTERY-DONE")


if __name__ == "__main__":
    main()
