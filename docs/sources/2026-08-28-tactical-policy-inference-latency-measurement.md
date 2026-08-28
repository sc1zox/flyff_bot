# Tactical policy inference latency measurement (2026-08-28)

Raw measurement evidence for US-086 acceptance criterion 4.4. `POLICY_LATENCY_BUDGET_SECONDS`
in `src/flyff_bot/features/policy/models.py` cites this document. Immutable after ingestion.

## Why this was measured

The latency budget is a safety threshold, not a performance target: `PolicyRunner.evaluate`
discards a learned decision whose evaluation exceeded it, and `HierarchicalPolicy.evaluate`
reports the same overrun as a fallback. Under unattended autopilot the budget is now graded —
one overrun costs the decision, a run of them demotes learned automation to `HEURISTIC` — so a
threshold that is guessed either fires on every tick or can never fire at all.

## Harness

`scripts/measure_policy_latency.py`, run from the repository root:

```powershell
uv run python scripts/measure_policy_latency.py
```

It evaluates the live `HierarchicalPolicy` (high-level strategic tier plus mid-level tactical
tier) against a farming objective, with a fresh macro-event token each iteration so the
high-level retention shortcut never short-circuits the measurement. Nothing is mocked; this is
the same object the orchestrator serves through `PolicyRunner`.

## Machine

| Property | Value |
| --- | --- |
| Processor | AMD64 Family 25 Model 97 Stepping 2, AuthenticAMD |
| OS | Windows 11 Pro 10.0.26200 |
| Python | 3.14.7 |
| Date | 2026-08-28 |

## Measurements

2 000 evaluations per candidate count. All values in milliseconds.

| Candidates | Median | p95 | p99 | Max |
| --- | --- | --- | --- | --- |
| 1 | 0.0044 | 0.0053 | 0.0101 | 0.0432 |
| 4 | 0.0058 | 0.0061 | 0.0116 | 0.0556 |
| 8 | 0.0076 | 0.0111 | 0.0173 | 0.0698 |
| 16 | 0.0109 | 0.0135 | 0.0208 | 0.0500 |

A second run of the same harness reproduced these figures within noise (worst observed maximum
0.0657 ms).

## What the numbers justify

The worst observed value across every candidate count is **0.070 ms**, and the worst p99 is
**0.021 ms**. The configured budget of `POLICY_LATENCY_BUDGET_SECONDS = 0.005` (5 ms) therefore
sits roughly **70x above the worst observed evaluation** and about **240x above the worst p99**.

That headroom is what the budget is for: it must not fire on ordinary jitter from garbage
collection, thread scheduling, or a busy client, but it must still catch a policy that has
genuinely stopped returning in bounded time. The measurement confirms the existing 5 ms value
is correct for this machine and is kept unchanged; it is now recorded rather than assumed.

A candidate set larger than 16 is not measured because the perception pipeline caps visible
detections well below that, and latency grows sub-linearly across the measured range
(0.0044 ms to 0.0109 ms median for 1 to 16 candidates).

## Caveat

These figures describe the deterministic Python hierarchical policy, which is what the
application serves today. No ONNX-backed learned artifact exists in `models/`; when one is
introduced, this measurement must be repeated against it before the budget is relied upon.
