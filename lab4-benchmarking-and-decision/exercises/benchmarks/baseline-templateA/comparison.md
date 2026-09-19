# Cross-RMW comparison

Raw observed values are shown first. A dash means missing evidence, never zero.

## Group 1: Template A — Two-Container Synthetic Baseline — bridge — Scenario S0

Settings: scale=2; workload=synthetic; duration=20; repeated cells are listed separately.

| Metric | Cyclone DDS | Fast DDS | Zenoh | Notes / interpretation |
|---|---|---|---|---|
| Service RTT p99 (ms) | 0.44 | 0.71 | 2.05 | service round-trip time |
| Pub/sub mean latency (ms) | 0.12 | 0.14 | 0.2 | generated pub/sub latency; not source-timestamp age |
| Pub/sub maximum latency (ms) | 1.48 | 1.87 | 2.18 | worst observed generated pub/sub latency |
| Behaviour under loss/jitter | — | — | — |  |
| Received rate (Hz) | 950 | 950 | 950 | received generated rate |
| Receiver workload CPU (%) | 5.35 | 9.36 | 11.68 | receiver workload CPU; not isolated middleware overhead |
| Ease of config & debugging | — | — | — |  |
| Discovery / connectivity robustness | — | — | — |  |

### Cells and coverage

| Repeat | RMW | Status | Service RTT p99 (ms) | Pub/sub mean latency (ms) | Pub/sub maximum latency (ms) | Behaviour under loss/jitter | Received rate (Hz) | Receiver workload CPU (%) | Ease of config & debugging | Discovery / connectivity robustness |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | cyclone | ok | 0.44 (available) | 0.12 (available) | 1.48 (available) | — (missing) | 950 (available) | 5.35 (available) | — (missing) | — (missing) |
| 2 | fastdds | ok | 0.71 (available) | 0.14 (available) | 1.87 (available) | — (missing) | 950 (available) | 9.36 (available) | — (missing) | — (missing) |
| 3 | zenoh | ok | 2.05 (available) | 0.2 (available) | 2.18 (available) | — (missing) | 950 (available) | 11.68 (available) | — (missing) | — (missing) |

Missing evidence is not favourable performance. Legacy rows are historical and unverified; no statistical-significance claim is made.

