# Cross-RMW comparison

Raw observed values are shown first. A dash means missing evidence, never zero.

## Group 1: Template B — Fleet MCAP Replay — bridge — Scenario S0

Settings: scale=3; workload=bag; duration=30; repeated cells are listed separately.

| Metric | Cyclone DDS | Fast DDS | Zenoh | Notes / interpretation |
|---|---|---|---|---|
| Control arrival-gap p99 (ms) | 51.68 | 51.37 | 51.5 | observed arrival gap; not source-timestamp latency |
| State maximum silence (ms) | 102.06 | 101.79 | 101.68 | longest observed silence, including window boundaries |
| Estimated delivery shortfall (%) | 0 | 0 | 0.34 | metadata-based estimate; not packet loss |
| Behaviour under loss/jitter | — | — | — |  |
| Throughput (Mb/s) | 9.01 | 9.01 | 9.01 | received sensor payload rate |
| Receiver workload CPU (%) | 9.67 | 8.13 | 10.98 | receiver workload CPU; not isolated middleware overhead |
| Ease of config & debugging | — | — | — |  |
| Discovery / connectivity robustness | — | — | — |  |

### Cells and coverage

| Repeat | RMW | Status | Control arrival-gap p99 (ms) | State maximum silence (ms) | Estimated delivery shortfall (%) | Behaviour under loss/jitter | Throughput (Mb/s) | Receiver workload CPU (%) | Ease of config & debugging | Discovery / connectivity robustness |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | cyclone | ok | 51.68 (available) | 102.06 (available) | 0 (available) | — (missing) | 9.01 (available) | 9.67 (available) | — (missing) | — (missing) |
| 2 | fastdds | ok | 51.37 (available) | 101.79 (available) | 0 (available) | — (missing) | 9.01 (available) | 8.13 (available) | — (missing) | — (missing) |
| 3 | zenoh | ok | 51.5 (available) | 101.68 (available) | 0.34 (available) | — (missing) | 9.01 (available) | 10.98 (available) | — (missing) | — (missing) |

Missing evidence is not favourable performance. Legacy rows are historical and unverified; no statistical-significance claim is made.

