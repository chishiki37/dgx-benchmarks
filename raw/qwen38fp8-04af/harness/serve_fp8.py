#!/usr/bin/env python3
"""Launch Qwen3.8-27B-Uncensored-FP8 on the keys-vllm GB10 image (04af)."""
import argparse, json, subprocess, sys, time, urllib.request

IMAGE = "ghcr.io/drowzeys/keys-vllm-027-gb10-qwen38:mtp3-20260813"
MODELS_HOST = "/home/vikassridhar/models-local-qwen38fp8"
MODEL_PATH = "/models/Qwen3.8-27B-Uncensored-FP8"
SERVED = "qwen38-fp8"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="qwen38fp8")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--k", type=int, default=1, help="MTP num_speculative_tokens (0=off)")
    ap.add_argument("--kv", default="fp8", help="kv-cache-dtype: fp8|auto")
    ap.add_argument("--util", type=float, default=0.90)
    ap.add_argument("--maxlen", type=int, default=262144)
    ap.add_argument("--wait", type=int, default=1500, help="seconds to wait for health; 0=no wait")
    a = ap.parse_args()

    subprocess.run(["docker", "rm", "-f", a.name], capture_output=True)
    cmd = ["docker", "run", "-d", "--name", a.name, "--gpus", "all",
           "--ipc=host", "--network", "host",
           "-v", MODELS_HOST + ":/models",
           "-e", "FLASHINFER_CUDA_ARCH_LIST=12.1a",
           "-e", "FLASHINFER_DISABLE_VERSION_CHECK=1",
           "-e", "VLLM_ALLOW_LONG_MAX_MODEL_LEN=1",
           IMAGE,
           "vllm", "serve", MODEL_PATH, "--served-model-name", SERVED,
           "--host", "0.0.0.0", "--port", str(a.port),
           "--kv-cache-dtype", a.kv,
           "--enable-flashinfer-autotune",
           "--enable-auto-tool-choice", "--tool-call-parser", "qwen3_xml",
           "--reasoning-parser", "qwen3",
           "--max-model-len", str(a.maxlen),
           "--gpu-memory-utilization", str(a.util)]
    if a.k > 0:
        cmd += ["--speculative-config",
                json.dumps({"method": "mtp", "num_speculative_tokens": a.k})]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("LAUNCH-FAIL:", (r.stderr or r.stdout)[-800:], flush=True)
        sys.exit(1)
    print("launched %s port=%d k=%d kv=%s util=%.2f maxlen=%d" %
          (a.name, a.port, a.k, a.kv, a.util, a.maxlen), flush=True)
    if a.wait <= 0:
        return

    url = "http://127.0.0.1:%d/v1/models" % a.port
    t0 = time.time()
    while time.time() - t0 < a.wait:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    print("HEALTHY after %.0fs" % (time.time() - t0), flush=True)
                    return
        except Exception:
            pass
        st = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", a.name],
                            capture_output=True, text=True)
        if st.stdout.strip() == "false":
            print("CONTAINER-DIED — last logs:", flush=True)
            lg = subprocess.run(["docker", "logs", "--tail", "60", a.name],
                                capture_output=True, text=True)
            print((lg.stderr or lg.stdout)[-3500:], flush=True)
            sys.exit(2)
        time.sleep(5)
    print("HEALTH-TIMEOUT after %ds — last logs:" % a.wait, flush=True)
    lg = subprocess.run(["docker", "logs", "--tail", "40", a.name],
                        capture_output=True, text=True)
    print((lg.stderr or lg.stdout)[-2500:], flush=True)
    sys.exit(3)


if __name__ == "__main__":
    main()
