# Weighted Pugh decision matrix

## Template B — Fleet MCAP Replay — Scenario S0

| Criterion | W | Cyclone DDS | Fast DDS | Zenoh |
|---|---:|---|---|---|
| Latency (p99) — Control arrival-gap p99 (ms) | 5 | 1.0 | 5.0 | 3.3 |
| Data Freshness — State maximum silence (ms) | 5 | 1.0 | 3.8 | 5.0 |
| Reliability (delivery) — Estimated delivery shortfall (%) | 5 | 5.0 | 5.0 | 1.0 |
| Behaviour under loss/jitter *(manual)* | 5 | 3.0† | 3.0† | 3.0† |
| Throughput / bandwidth efficiency — Throughput (Mb/s) | 4 | 3.0 | 3.0 | 3.0 |
| CPU overhead — Receiver workload CPU (%) | 3 | 2.8 | 5.0 | 1.0 |
| Ease of config & debugging *(manual)* | 3 | 3.0† | 3.0† | 3.0† |
| Discovery / connectivity robustness *(manual)* | 4 | 3.0† | 3.0† | 3.0† |
| **Weighted total** | | **91.5** | **132.2** | **97.6** |

**Ranking:** Fast DDS (132.2), Zenoh (97.6), Cyclone DDS (91.5)

† provisional neutral manual score; ‡ inherited legacy template-wide manual score.
> Raw measurements belong in comparison.md first. Ties and singletons receive neutral normalization and provide no ordering; this report makes no statistical-significance claim.

