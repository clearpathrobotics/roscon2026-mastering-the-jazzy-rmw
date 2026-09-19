# Weighted Pugh decision matrix

## Template B — Fleet MCAP Replay — Scenario S0

| Criterion | W | Cyclone DDS | Fast DDS | Zenoh |
|---|---:|---|---|---|
| Latency (p99) — Control arrival-gap p99 (ms) | 5 | 1.0 | 5.0 | 1.4 |
| Data Freshness — State maximum silence (ms) | 5 | 5.0 | 1.0 | 4.0 |
| Reliability (delivery) — Estimated delivery shortfall (%) | 5 | 5.0 | 5.0 | 1.0 |
| Behaviour under loss/jitter *(manual)* | 5 | 3.0† | 3.0† | 3.0† |
| Throughput / bandwidth efficiency — Throughput (Mb/s) | 4 | 3.0 | 3.0 | 3.0 |
| CPU overhead — Receiver workload CPU (%) | 3 | 1.0 | 2.1 | 5.0 |
| Ease of config & debugging *(manual)* | 3 | 3.0† | 3.0† | 3.0† |
| Discovery / connectivity robustness *(manual)* | 4 | 3.0† | 3.0† | 3.0† |
| **Weighted total** | | **106.0** | **109.4** | **95.2** |

**Ranking:** Fast DDS (109.4), Cyclone DDS (106.0), Zenoh (95.2)

† provisional neutral manual score; ‡ inherited legacy template-wide manual score.
> Raw measurements belong in comparison.md first. Ties and singletons receive neutral normalization and provide no ordering; this report makes no statistical-significance claim.

## Template B — Fleet MCAP Replay — Scenario S2

| Criterion | W | Cyclone DDS | Fast DDS | Zenoh |
|---|---:|---|---|---|
| Latency (p99) — Control arrival-gap p99 (ms) | 5 | 5.0 | 3.9 | 1.0 |
| Data Freshness — State maximum silence (ms) | 5 | 4.7 | 5.0 | 1.0 |
| Reliability (delivery) — Estimated delivery shortfall (%) | 5 | 1.0 | 1.0 | 5.0 |
| Behaviour under loss/jitter *(manual)* | 5 | 3.0† | 3.0† | 3.0† |
| Throughput / bandwidth efficiency — Throughput (Mb/s) | 4 | 1.0 | 1.0 | 5.0 |
| CPU overhead — Receiver workload CPU (%) | 3 | 1.0 | 2.5 | 5.0 |
| Ease of config & debugging *(manual)* | 3 | 3.0† | 3.0† | 3.0† |
| Discovery / connectivity robustness *(manual)* | 4 | 3.0† | 3.0† | 3.0† |
| **Weighted total** | | **97.0** | **97.2** | **106.0** |

**Ranking:** Zenoh (106.0), Fast DDS (97.2), Cyclone DDS (97.0)

† provisional neutral manual score; ‡ inherited legacy template-wide manual score.
> Raw measurements belong in comparison.md first. Ties and singletons receive neutral normalization and provide no ordering; this report makes no statistical-significance claim.

