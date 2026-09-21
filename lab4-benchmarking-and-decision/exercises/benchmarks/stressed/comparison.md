# Cross-RMW comparison

Raw observed values are shown first. A dash means missing evidence, never zero.

## Group 1: Template B — Fleet MCAP Replay — bridge — Scenario S0

Settings: scale=3; workload=bag; duration=30; repeated cells are listed separately.

| Metric | Cyclone DDS | Fast DDS | Zenoh | Notes / interpretation |
|---|---|---|---|---|
| Control arrival-gap p99 (ms) | 51.81 | 51.09 | 51.73 | observed arrival gap; not source-timestamp latency |
| State maximum silence (ms) | 101.66 | 101.86 | 101.71 | longest observed silence, including window boundaries |
| Estimated delivery shortfall (%) | 0 | 0 | 0.34 | metadata-based estimate; not packet loss |
| Behaviour under loss/jitter | — | — | — |  |
| Throughput (Mb/s) | 9.01 | 9.01 | 9.01 | received sensor payload rate |
| Receiver workload CPU (%) | 12.21 | 11.55 | 9.89 | receiver workload CPU; not isolated middleware overhead |
| Ease of config & debugging | — | — | — |  |
| Discovery / connectivity robustness | — | — | — |  |

### Cells and coverage

| Repeat | RMW | Status | Control arrival-gap p99 (ms) | State maximum silence (ms) | Estimated delivery shortfall (%) | Behaviour under loss/jitter | Throughput (Mb/s) | Receiver workload CPU (%) | Ease of config & debugging | Discovery / connectivity robustness |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | cyclone | ok | 51.81 (available) | 101.66 (available) | 0 (available) | — (missing) | 9.01 (available) | 12.21 (available) | — (missing) | — (missing) |
| 2 | fastdds | ok | 51.09 (available) | 101.86 (available) | 0 (available) | — (missing) | 9.01 (available) | 11.55 (available) | — (missing) | — (missing) |
| 3 | zenoh | ok | 51.73 (available) | 101.71 (available) | 0.34 (available) | — (missing) | 9.01 (available) | 9.89 (available) | — (missing) | — (missing) |

Missing evidence is not favourable performance. Legacy rows are historical and unverified; no statistical-significance claim is made.

## Group 2: Template B — Fleet MCAP Replay — bridge — Scenario S2

Settings: scale=3; workload=bag; duration=30; repeated cells are listed separately.

| Metric | Cyclone DDS | Fast DDS | Zenoh | Notes / interpretation |
|---|---|---|---|---|
| Control arrival-gap p99 (ms) | 187.17 | 546.82 | 1516.68 | observed arrival gap; not source-timestamp latency |
| State maximum silence (ms) | 224.41 | 133.61 | 1502.36 | longest observed silence, including window boundaries |
| Estimated delivery shortfall (%) | 97.12 | 97.45 | 65.34 | metadata-based estimate; not packet loss |
| Behaviour under loss/jitter | — | — | — |  |
| Throughput (Mb/s) | 0.26 | 0.23 | 3.08 | received sensor payload rate |
| Receiver workload CPU (%) | 16 | 11.06 | 3.06 | receiver workload CPU; not isolated middleware overhead |
| Ease of config & debugging | — | — | — |  |
| Discovery / connectivity robustness | — | — | — |  |

### Cells and coverage

| Repeat | RMW | Status | Control arrival-gap p99 (ms) | State maximum silence (ms) | Estimated delivery shortfall (%) | Behaviour under loss/jitter | Throughput (Mb/s) | Receiver workload CPU (%) | Ease of config & debugging | Discovery / connectivity robustness |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | cyclone | ok | 187.17 (available) | 224.41 (available) | 97.12 (available) | — (missing) | 0.26 (available) | 16 (available) | — (missing) | — (missing) |
| 2 | fastdds | ok | 546.82 (available) | 133.61 (available) | 97.45 (available) | — (missing) | 0.23 (available) | 11.06 (available) | — (missing) | — (missing) |
| 3 | zenoh | ok | 1516.68 (available) | 1502.36 (available) | 65.34 (available) | — (missing) | 3.08 (available) | 3.06 (available) | — (missing) | — (missing) |

Missing evidence is not favourable performance. Legacy rows are historical and unverified; no statistical-significance claim is made.

