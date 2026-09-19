# 1. Controlled workload, different RMW

## Workshop strategy

Use the supplied recorded benchmark results first. The runs are already captured in
[`lab4-benchmarking-and-decision/exercises/benchmarks/`](benchmarks/), so workshop time can go to reading evidence and
comparing RMWs instead of waiting for a sweep or debugging a local environment. If time
remains, [Exercise 4](4_generate_your_own_data.md) is the hands-on path for generating
and running a new synthetic bag; it is a separate experiment, not a replacement for
these reference results.

Lab 3 showed how the RMWs behave under stress. This exercise establishes clean
baselines: how do the same three RMWs behave with the same workload, deployment, and
no applied network impairment? That is what Lab 4 measures.

The two benchmark reports answer different deployment questions. Template A is a small,
two-container synthetic baseline: it exposes the RMW's cost and behaviour in a simple
local ROS 2 path. Template B is a three-replica fleet replaying the same recorded robot
traffic: it shows what changes when the decision must hold for a distributed deployment.
Compare Cyclone, Fast DDS, and Zenoh **within** each template. Do not compare Template
A values directly with Template B values; they use different workloads and metrics.

## Steps

1. Open the supplied benchmark directories:

   - [`lab4-benchmarking-and-decision/exercises/benchmarks/baseline-templateA/`](benchmarks/baseline-templateA/) — Template A,
     clean local synthetic baseline.
   - [`lab4-benchmarking-and-decision/exercises/benchmarks/baseline-templateB/`](benchmarks/baseline-templateB/) — Template B,
     clean fleet replay (`S0`).

   Each directory contains `comparison.md`, `comparison.csv`, `comparison.png`,
   `pugh.md`, and sweep metadata. Treat these as the reference evidence for the
   workshop.

2. Read the cross-RMW raw-value tables first. In Template A, inspect receiver workload
   CPU, service RTT, pub/sub latency, and received rate. In Template B, inspect estimated
   delivery shortfall, state maximum silence, control arrival-gap p99, throughput, and
   receiver CPU. These are observed receipts and metadata-based estimates, not packet
   captures.

3. Check the **Cells and coverage** section in each `comparison.md`. It must list every
   RMW with status `ok`; measured rows must say `(available)`. A missing value, invalid
   cell, or failed status is evidence to diagnose, not favourable performance.

4. Use `comparison.csv` or `comparison.png` when you want the same raw comparison in a
   spreadsheet or chart. Leave `pugh.md` for [Exercise 2](2_read_the_matrix.md), where
   you will inspect the weighted decision matrix and explain its recommendation.

<details>
<summary>Answer: what "clean" is supposed to tell you</summary>

Within each template, every RMW receives the same controlled workload on the same
deployment. Template A tells you whether an RMW has a meaningful baseline CPU, latency,
or throughput cost before fleet traffic and network impairment enter the picture.
Template B tells you whether that same RMW delivers the recorded sensor, control, and
state traffic acceptably across a small fleet on a clean network.

The result is two deployment-specific baselines, not one overall winner. An RMW that
looks efficient in Template A but has poorer delivery or control timing in Template B
may be a better fit for a simple local robot than for a robot-plus-fleet-manager system.
If the RMWs are similar in both clean sweeps, later differences in
[Exercise 3](3_stressed_vs_clean.md) are more plausibly caused by the introduced
network condition than by clean baseline overhead.
</details>

## When it does not work

**A supplied report contains missing or invalid cells.** Do not infer a ranking from
that report. Check the matching cell metadata and use the report's recorded logs only to
understand why the evidence is unavailable, then continue with the valid rows and note
the limitation in your analysis.

Proceed to [Exercise 2](2_read_the_matrix.md).
