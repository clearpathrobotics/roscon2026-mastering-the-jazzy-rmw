# Weighted Pugh decision matrix

## Template A — Two-Container Synthetic Baseline — Scenario S0

| Criterion | W | Cyclone DDS | Fast DDS | Zenoh |
|---|---:|---|---|---|
| Latency (p99) — Service RTT p99 (ms) | 4 | 5.0 | 4.3 | 1.0 |
| Data Freshness — Pub/sub mean latency (ms) | 4 | 5.0 | 4.0 | 1.0 |
| Reliability (delivery) — Pub/sub maximum latency (ms) | 3 | 5.0 | 2.8 | 1.0 |
| Behaviour under loss/jitter *(manual)* | 1 | 3.0† | 3.0† | 3.0† |
| Throughput / bandwidth efficiency — Received rate (Hz) | 4 | 3.0 | 3.0 | 3.0 |
| CPU overhead — Receiver workload CPU (%) | 5 | 5.0 | 2.5 | 1.0 |
| Ease of config & debugging *(manual)* | 4 | 3.0† | 3.0† | 3.0† |
| Discovery / connectivity robustness *(manual)* | 2 | 3.0† | 3.0† | 3.0† |
| **Weighted total** | | **113.0** | **86.9** | **49.0** |

**Ranking:** Cyclone DDS (113.0), Fast DDS (86.9), Zenoh (49.0)

† provisional neutral manual score; ‡ inherited legacy template-wide manual score.
> Raw measurements belong in comparison.md first. Ties and singletons receive neutral normalization and provide no ordering; this report makes no statistical-significance claim.

