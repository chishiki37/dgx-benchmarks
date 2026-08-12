# Staging Summary — SuperDeepSeek-MQ vs Ablit Comparison

**Prepared:** August 12, 2026
**Status:** Staged for review, **not yet pushed** to muse-glimmer-benchmarks repo
**Staging path on 9105:** `/home/vikassridhar/muse-glimmer-benchmarks-staging/`

---

## Files Staged

```
muse-glimmer-benchmarks-staging/
├── 04-superdeepseek-vs-ablit-comparison.md   (26,996 bytes, main report)
├── README.md                                  (2,287 bytes, updated repo index)
├── raw-gsm8k-rescored.json                    (17,578 bytes, GSM8K raw data)
└── raw-humaneval-chat.json                    (21,260 bytes, HumanEval raw data)
```

---

## Headline Numbers (cross-checked against JSONs)

| Metric | Ablit | SuperDeepSeek-MQ | Δ | Source |
|---|---:|---:|---:|---|
| Single-stream tok/s (Q&A) | 26.9 | 36.8 | +1.37× | benchmark.py run |
| Single-stream tok/s (creative) | 26.9 | 32.9 | +1.22× | c8_bench.py run |
| **C=4 aggregate tok/s** | 73.6 | **82.7** | +1.12× | c8_bench.py run |
| **C=8 aggregate tok/s** | 87.3 | **101.6** | +1.16× | c8_bench.py run |
| GSM8K (smart-extract) | 96% (48/50) | 92% (46/50) | −4 pts | raw-gsm8k-rescored.json |
| GSM8K genuine math errors | 2 | 1 | −1 | rescore analysis |
| **HumanEval pass@1 (chat)** | **96% (48/50)** | **96% (48/50)** | TIE | raw-humaneval-chat.json |
| HumanEval real code bugs | 2 | 0 (only 2 TRUNC @1024t) | −2 | raw-humaneval-chat.json |
| DSpark spec decode acceptance | n/a | **85.7%** (20931/24431) | — | /metrics |

---

## What I Want You To Confirm Before Push

1. **The 9-step structure** (Headline, Models, Speed, GSM8K, HumanEval, Comparison, Architecture, Serving, Pitfalls, Recommendations, Methodology, Raw Artifacts) — does it match your house style for reports 01–03?

2. **The 4 GSM8K failures breakdown** — I'm calling:
   - Q8, Q24: extraction artifacts (not real bugs)
   - Q27, Q49: real reasoning errors
   - That leaves only Q49 as a "genuine" real error if you discount the LaTeX fraction (Q27) too
   
   Should I distinguish these more carefully in the report? Currently I call Q49 + Q8 + Q24 as "between extraction and reasoning" and Q27 (LaTeX fraction) + maybe Q49 as genuine errors. The report says "1 genuine math error (Q49)" — verifying that's defensible.

3. **The HumanEval "endpoint mismatch" story** — I attribute the 76% initial number to the raw completions endpoint wrapping responses in chat-mode tags. The 96% re-run via `/v1/chat/completions` is the fair comparison. Some readers may want to know about both — should I keep both in the report or just the 96%?

4. **C=8 with `max-num-seqs=6` cap** — 2 of 8 requests queue per batch, but aggregate still beats ablit. Should I either (a) keep the report honest about this cap or (b) recommend a follow-up retune?

5. **The "Bounded rank-64 BF16 output-head recovery" callout** — this is one of SuperDeepSeek's design features. Am I making too much of it? It's not the biggest factor for speed (DSpark spec decode is), but it's a meaningful architectural difference worth flagging.

---

## Things Intentionally Left Out

- **TTFT measurements** for SuperDeepSeek — not measured yet; tagged as "not measured*" in the report
- **`max-num-seqs=8` retune for SuperDeepSeek** — would likely push C=8 above 110 tok/s but requires a server restart; deferred
- **`reasoning_effort=medium`/`high` quality comparison** — recipe defaults to `low`; not tested
- **Long-context benchmarks** (e.g. needle-in-haystack at 1M tokens) — out of scope for this report

If any of these should be added before push, let me know.

---

## Next Steps

**After your review, the GitHub push would be:**

```bash
ssh 9105
cd ~/muse-glimmer-benchmarks-staging
# Create new repo or update existing? muse-glimmer-benchmarks already exists.

# If pushing to existing chishiki37/muse-glimmer-benchmarks repo:
gh repo clone chishiki37/muse-glimmer-benchmarks ~/muse-glimmer-benchmarks
cp 04-superdeepseek-vs-ablit-comparison.md ~/muse-glimmer-benchmarks/
cp README.md ~/muse-glimmer-benchmarks/README.md
cp raw-*.json ~/muse-glimmer-benchmarks/raw/
cd ~/muse-glimmer-benchmarks
git add . && git commit -m "Add report 04: SuperDeepSeek-MQ vs Ablit comparison"
git push origin main
```

I have not run the push yet. Standing by for your review.

---

## How to Open the Report

**On 9105:**
```bash
cat ~/muse-glimmer-benchmarks-staging/04-superdeepseek-vs-ablit-comparison.md
```

**Or grab a fresh copy via SCP** (works since the file already exists on 9105):
```bash
scp vikassridhar@100.127.212.61:~/muse-glimmer-benchmarks-staging/04-superdeepseek-vs-ablit-comparison.md ./
```

The report is 416 lines / 27 KB. It's readable in one sitting.
