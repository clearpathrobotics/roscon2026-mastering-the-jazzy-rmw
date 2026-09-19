# 2. Read the matrix

A Pugh matrix is only as defensible as the weights behind it. This exercise teaches you
to read `pugh.md`, distinguish measured from manually scored criteria, and explain the
recommendation rather than simply naming a winner.

## How the matrix works

A Pugh matrix compares options against the criteria that matter for one decision. Here,
the options are the RMWs and the criteria are the rows in `pugh.md`. The harness creates
one matrix for each template, topology, and scenario. A clean result and an impaired
result are separate decisions, never averaged into one ranking.

For each measured row, the harness compares only the RMWs present in that matrix. The
best value receives $5$, the worst receives $1$, and values between them are scaled
linearly. A tied row, a row with only one usable value, or a missing value is neutral at
$3$. This workshop deliberately uses a normalized $1$–$5$ score scale, not the
traditional Pugh $-1/0/+1$ comparison-to-a-baseline scale: $5$ means best in this
matrix, $3$ means neutral, and $1$ means worst. The `W` column is the importance weight
from `benchmark.yaml`. The weighted total is:

$$
\mathrm{total\ for\ an\ RMW} = \sum_{\text{criteria}} \text{weight} \times \text{score}
$$

The highest valid total ranks first. The report suppresses the overall ranking if a
requested candidate lacks required valid measurements. It is a decision aid, not a universal statement that one
RMW is best: change the workload, scenario, or weights and the recommendation can
change.

### Where the weights come from

The weights are declared in [`benchmark.yaml`](../scripts/benchmark.yaml) under
`decision.weights`: `A:` applies to the local synthetic baseline and `B:` applies to
the fleet replay. Each criterion has a weight from 1 (least important) to 5 (most
important). For example, **Template A** gives `cpu_overhead: 5`, while **Template B** gives
`reliability: 5`; that encodes different deployment priorities, not a measurement.

### What the measured rows mean

| Pugh row | Backing metric | What it answers |
|---|---|---|
| **Reliability (delivery)** | `pubsub_latency_max_ms` (A); `sensor_estimated_delivery_shortfall_pct` (B) | A reports the generated stream's maximum pub/sub latency. B estimates the shortfall against MCAP metadata counts. Neither is a packet-loss measurement. Lower is better. |
| **Latency (p99)** | `service_rtt_p99_ms` (A); `control_arrival_gap_p99_ms` (B) | A measures `AddTwoInts` service round-trip time. B measures the p99 gap between received control messages. Arrival gaps are not source-timestamp latency. Lower is better. |
| **Data Freshness** | `pubsub_latency_mean_ms` (A); `state_max_silence_ms` (B) | A reports mean generated pub/sub latency. B reports the longest observed state silence, including window boundaries. Neither is source-timestamp age. Lower is better. |
| **Throughput / bandwidth efficiency** | `pubsub_received_hz` (A); `throughput_mbps` (B) | A reports received generated messages per second. B reports received sensor payload per second. Higher is better. |
| **CPU overhead** | `cpu_pct` | Receiver workload CPU sampled during the active measurement window. It is not isolated middleware overhead. Lower is better. |

### The manual loss-and-jitter assessment

`loss_jitter_behaviour` does **not** measure jitter directly. Lab 4 records the
consequences of an injected loss-and-jitter profile, not a jitter time series. It is an
operational assessment of whether the system remains usable and predictable under the
same named impairment. Do not score it from the clean `S0` matrix, and do not simply
copy the numeric rows into this criterion: those rows are already weighted separately.

After [Exercise 3](3_stressed_vs_clean.md), compare the same RMW's clean `S0` result
with `S2` (`heavy`: 5% bursty loss and 30 ms +/- 10 ms delay) and, when available,
`constrained` (1% loss, 50 ms +/- 15 ms delay, 50 Mbit/s per-link cap). Use the
following evidence together:

- estimated delivery shortfall, control arrival-gap p99, state maximum silence, and throughput: whether degradation is bounded and consistent with the known impairment.
- ROS logs and graph checks: whether participants remain connected or require manual
intervention to rediscover peers.
- The Lab 3 live incident: whether the operator-facing fleet behaviour remained
understandable and recovered when the impairment was cleared.

- Use $5$ when the RMW stays connected and degrades predictably without operator action.
- Use $3$ when communication remains usable but has material, manageable degradation or
  requires documented tuning.
- Use $1$ when it fails to maintain useful communication, requires repeated manual
  recovery, or exhibits unexplained behaviour.

Scores of $2$ and
$4$ represent the corresponding intermediate evidence. Record a one-sentence rationale
beside each score in your experiment notes.

The other manual rows, `ease_config` and `discovery_robust`, also begin at neutral $3$
to avoid inventing evidence. After using the workshop, record justified $1$–$5$
assessments in `manual_scores.yaml` and rerun the scorer as shown in
[Exercise 5](5_after_the_workshop.md).

## Steps

1. Open the `pugh.md` from [Exercise 1](1_same_traffic_different_rmw.md)'s **Template A**
   sweep and its clean **Template B** sweep, and the criteria table in
   [`benchmark.yaml`](../scripts/benchmark.yaml) (`decision.criteria` and
   `decision.weights`).

2. For each criterion, identify whether it is `metric:`-scored (from a measured number) or
   `manual: true` (defaults to a neutral 3/5 until someone scores it by hand). Which
   criteria in **Template A**'s row are still sitting at the default?

3. Compare **Template A**'s weights against **Template B**'s for the same criteria (e.g.
   `cpu_overhead`, `loss_jitter_behaviour`). Which criteria matter more for the minimal
   two-container baseline than for a distributed fleet, and does the weighting reflect
   that?

4. Before accepting a ranking, check whether `pugh.md` says **Ranking suppressed** and
   whether any cells carry a `†`. A suppressed ranking means a requested RMW lacks valid
   measured evidence. `†` means a manual criterion still has its provisional neutral
   score of $3$; it is not an observed RMW result.

5. After completing [Exercise 3](3_stressed_vs_clean.md), compare the clean and stressed
   **Template B** sections in its `pugh.md`. The headings include the scenario. Do not read
   a blended score. Pick the criterion that moves most and trace it to its backing raw
   metric in `comparison.md`.

6. **Optional: test priorities for your own deployment.** Edit only the relevant `A:`
   or `B:` values under `decision.weights` in `benchmark.yaml`, keeping weights in the
   1-5 range. Then regenerate an existing matrix without rerunning the benchmark:

   ```bash
   docker exec --user "$(id -u):$(id -g)" -e HOME=/tmp ubuntu-headless \
     python3 /scripts/lab4/pugh.py /captures/<SWEEP_ID>
   ```

   Compare the new `pugh.md` with the earlier one and identify which changed weight
   changed the ranking. Keep the workshop defaults for the required exercise; use
   alternate weights to make a deployment-specific decision, not to manufacture a
   preferred winner.

7. **Optional: score the manual criteria.** Create `manual_scores.yaml` beside the
    sweep's `pugh.md`. Scores are $1$–$5$ assessments, not measurements; give every RMW
    a score only when your observations justify it. For example:

    ```yaml
    B:
       S0:
          cyclone: { ease_config: 4, discovery_robust: 4, loss_jitter_behaviour: 3 }
          fastdds: { ease_config: 3, discovery_robust: 3, loss_jitter_behaviour: 3 }
          zenoh: { ease_config: 4, discovery_robust: 4, loss_jitter_behaviour: 4 }
    ```

    Regenerate the matrix with the command in Step 6. The `†` marker disappears only for
    criteria you scored. [Exercise 5](5_after_the_workshop.md) has the same workflow for
    applying your own deployment evidence.

<details>
<summary>Answer: what the matrix is telling you</summary>

**Template A** (`Local Robot / Single System`) weighs `cpu_overhead` and `ease_config`
highest. In its minimal two-container baseline, the RMW's resource cost and configuration
effort are the main differentiators because no impairment is applied. **Template B**
(`Distributed Robot + Fleet Manager`) weighs `reliability`, `loss_jitter_behaviour`,
`latency_p99`, and `data_freshness` highest: once the system is distributed, behaviour when a link degrades
dominates whether it stays usable.

The outcome is not one universal RMW winner. First, reject a suppressed ranking: it has
missing required measurements. Next, treat `†` manual scores as provisional $3$s, not
evidence that candidates are equal. Then use the valid matrix for the deployment it
models: Template A informs a simple local robot; Template B informs the fleet replay.
Those matrices can legitimately rank the same RMWs differently because their workloads,
measurements, and priorities differ.

After Exercise 3, use the Template B scenario that resembles the deployment's actual
risk. The clean `S0` matrix answers baseline fleet behaviour; the impaired matrix answers
behaviour on the specified bad link. Do not average their rankings. A defensible decision
names the relevant deployment and scenario, checks that its evidence is valid, and states
which priorities produced the recommendation.

The manual criteria (`loss_jitter_behaviour`, `ease_config`, `discovery_robust`) are
manual because they resist a clean single-number metric. "Ease of
configuration" is a judgement call informed by how much time you personally spent on
Lab 1's configs, not something `class_probe.py` can measure. Leaving them at the
neutral default is honest when nobody has scored them yet, but it also means the matrix
has only provisional evidence for that dimension.
</details>

## When it does not work

**Every criterion in a row is neutral (3/5) and the ranking looks meaningless.** That
means none of the metric-backed criteria produced a clear winner (check the sweep
actually ran enough cells) or the manual ones dominate the weights and nobody's scored
them yet. See [Exercise 5](5_after_the_workshop.md) for how to do that.

Move on to [Exercise 3](3_stressed_vs_clean.md), which creates Lab 4's own controlled
stressed matrix alongside the clean baseline.
