#!/usr/bin/env python3
"""Autoresearch sweep: FP8 serving configs on 04af.

For each config: launch -> health -> warmup (incl 26K prefill) -> decode_bench ->
short arena ladder. Ranks by mean decode tok/s, restarts the winner fresh,
leaves it serving on PORT for the quality battery.

Marker files in /tmp/fp8bench/: SWEEP_DONE / SWEEP_FAILED
"""
import json, os, re, subprocess, sys, time, urllib.request

PORT = 8090
SERVED = "qwen38-fp8"
OUT = "/tmp/fp8bench"
BENCH_ENV = dict(os.environ,
                 BENCH_URL="http://127.0.0.1:%d/v1/chat/completions" % PORT,
                 BENCH_MODEL=SERVED)
CONFIGS = [
    # (name, k, kv, util)
    ("mtp1_kvfp8_u90",  1, "fp8",  0.90),
    ("mtp0_kvfp8_u90",  0, "fp8",  0.90),
    ("mtp1_kvauto_u90", 1, "auto", 0.90),
    ("mtp1_kvfp8_u92",  1, "fp8",  0.92),
]
MODEL_DIR = "/home/vikassridhar/models-local-qwen38fp8/Qwen3.8-27B-Uncensored-FP8"


def log(msg):
    print(time.strftime("%H:%M:%S") + " " + msg, flush=True)


def chat(prompt, max_tokens=64, thinking=False, timeout=600):
    body = json.dumps({
        "model": SERVED,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": thinking}}).encode()
    req = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % PORT,
                                 data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    return d["choices"][0]["message"]["content"]


def warmup():
    t0 = time.time()
    chat("Write one short sentence about the sea.", 128)
    chat("Write one short sentence about mountains.", 128)
    big = ("Unified memory bandwidth bounds decode throughput on edge accelerators today. "
           * 2200) + "\nReply with exactly: READY"
    out = chat(big, 16, timeout=900)
    log("warmup done in %.0fs (big-prefill reply: %s)" % (time.time() - t0, out.strip()[:40]))


def run_script(cmd, logfile, timeout):
    with open(logfile, "w") as f:
        p = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=BENCH_ENV,
                           timeout=timeout)
    return p.returncode


def parse_decode(logfile):
    txt = open(logfile).read()
    runs = re.findall(r"\[(.*?)\] tokens=(\d+) total=([\d.]+)s TTFT=([\d.]+)s "
                      r"e2e=([\d.]+) tok/s decode~=([\d.]+) tok/s", txt)
    return [{"label": r[0].strip(), "tokens": int(r[1]), "total": float(r[2]),
             "ttft": float(r[3]), "e2e": float(r[4]), "decode": float(r[5])} for r in runs]


def main():
    os.makedirs(OUT, exist_ok=True)
    # gate: model must be fully downloaded
    shards = [f for f in os.listdir(MODEL_DIR) if f.endswith(".safetensors")] if os.path.isdir(MODEL_DIR) else []
    if len(shards) < 7 or not os.path.exists(os.path.join(MODEL_DIR, "config.json")):
        log("DOWNLOAD-NOT-READY (shards=%d) — aborting" % len(shards))
        open(OUT + "/SWEEP_FAILED", "w").write("download not ready\n")
        sys.exit(1)

    results = []
    for name, k, kv, util in CONFIGS:
        log("=== CONFIG %s (k=%d kv=%s util=%.2f) ===" % (name, k, kv, util))
        t0 = time.time()
        r = subprocess.run([sys.executable, "/tmp/serve_fp8.py", "--name", "qwen38fp8",
                            "--port", str(PORT), "--k", str(k), "--kv", kv,
                            "--util", str(util), "--wait", "1500"],
                           capture_output=True, text=True)
        launch_log = r.stdout + r.stderr
        open(OUT + "/launch_%s.log" % name, "w").write(launch_log)
        if r.returncode != 0:
            log("LAUNCH FAILED rc=%d — skipping" % r.returncode)
            results.append({"config": name, "k": k, "kv": kv, "util": util,
                            "status": "launch-fail"})
            continue
        boot = time.time() - t0
        try:
            warmup()
        except Exception as e:
            log("WARMUP FAILED: %s — skipping config" % e)
            results.append({"config": name, "k": k, "kv": kv, "util": util,
                            "status": "warmup-fail", "boot_s": round(boot)})
            continue
        rc_d = run_script(["python3", "/tmp/decode_bench.py"],
                          OUT + "/decode_%s.log" % name, 1200)
        rc_a = run_script(["python3", "/tmp/arena_ladder.py", "2048,4096,8192"],
                          OUT + "/arena_%s.log" % name, 2400)
        runs = parse_decode(OUT + "/decode_%s.log" % name)
        mean_dec = sum(x["decode"] for x in runs) / len(runs) if runs else 0.0
        results.append({"config": name, "k": k, "kv": kv, "util": util,
                        "status": "ok", "boot_s": round(boot),
                        "decode_rc": rc_d, "arena_rc": rc_a,
                        "decode_runs": runs, "mean_decode": round(mean_dec, 2)})
        log("CONFIG %s done: mean decode %.2f tok/s (boot %.0fs)" % (name, mean_dec, boot))

    ok = [r for r in results if r["status"] == "ok" and r["mean_decode"] > 0]
    if not ok:
        log("NO CONFIG WORKED")
        open(OUT + "/SWEEP_FAILED", "w").write(json.dumps(results, indent=1))
        sys.exit(2)

    winner = max(ok, key=lambda r: r["mean_decode"])
    log("WINNER: %s (%.2f tok/s) — restarting fresh for battery" %
        (winner["config"], winner["mean_decode"]))
    subprocess.run([sys.executable, "/tmp/serve_fp8.py", "--name", "qwen38fp8",
                    "--port", str(PORT), "--k", str(winner["k"]), "--kv", winner["kv"],
                    "--util", str(winner["util"]), "--wait", "1500"],
                   capture_output=True, text=True)
    try:
        warmup()
    except Exception as e:
        log("WINNER WARMUP FAILED: %s" % e)
        open(OUT + "/SWEEP_FAILED", "w").write("winner warmup fail: " + str(e))
        sys.exit(3)

    summary = {"port": PORT, "served_model": SERVED, "winner": winner,
               "all": results,
               "ranking": [r["config"] for r in sorted(ok, key=lambda x: -x["mean_decode"])]}
    with open(OUT + "/sweep_summary.json", "w") as f:
        json.dump(summary, f, indent=1)
    open(OUT + "/SWEEP_DONE", "w").write(winner["config"])
    log("SWEEP-DONE winner=%s" % winner["config"])


if __name__ == "__main__":
    main()
