# 08 — Eval

Six suites ship with the library. Run them all:

```bash
memnex eval --suite full
```

## Suites

| Suite | Measures | Target |
|---|---|---|
| `identity_resolution` | F1 on resolving synthetic identifiers | >99% deterministic, >85% fuzzy |
| `recall` | F1 on factual questions after cross-channel sessions | >80% (vs Mem0 ≈49%, Zep ≈64%) |
| `handoff` | Voice → WhatsApp info retention + noise | >90% retention, <10% noise |
| `latency` | p50/p95/p99 for write/read/resolve under 500 iterations | read p50 <5ms cached |
| `conflict` | Precision/recall on contradictory fact pairs | >85% precision, >80% recall |
| `load` | Concurrent ops/s at N agents | scales linearly to N=10k |

## Datasets

Small, reproducible, shipped in-tree:

- [synthetic_identities.json](../src/memnex/eval/datasets/synthetic_identities.json)
- [cross_channel_conversations.json](../src/memnex/eval/datasets/cross_channel_conversations.json)
- [conflicting_facts.json](../src/memnex/eval/datasets/conflicting_facts.json)

Swap in your own — same schema.

## Sample output

```json
{
  "results": {
    "identity_resolution": {"f1": 1.0, "precision": 1.0, "recall": 1.0},
    "recall":              {"f1": 1.0, "questions": 3},
    "handoff":             {"retention": 0.67, "format_appropriate_rate": 1.0},
    "latency":             {"write_ms": {"p50": 0.19, "p95": 0.23, "p99": 0.26}},
    "conflict":            {"precision": 1.0, "recall": 0.33, "tp": 1, "fp": 0, "fn": 2},
    "load":                {"throughput_ops_s": 12092}
  }
}
```

(In-memory backend; Postgres/Redis numbers will be higher latency, same ratios.)

## Extending

Write a new suite in `src/memnex/eval/suites/<name>.py`:

```python
async def run(mx):
    # your benchmark
    return {"suite": "my_suite", "metric": ...}
```

Register it in [eval/runner.py](../src/memnex/eval/runner.py).
