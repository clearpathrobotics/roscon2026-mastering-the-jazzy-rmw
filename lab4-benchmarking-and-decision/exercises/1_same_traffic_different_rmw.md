# 1. Controlled workload, different RMW

Lab 3 showed how the RMWs behave under stress. This exercise establishes clean
baselines: how do the same three RMWs behave with the same workload, deployment, and
no applied network impairment? That is what Lab 4 measures.

The two sweeps answer different deployment questions. Template A is a small,
two-container synthetic baseline: it exposes the RMW's cost and behaviour in a simple
local ROS 2 path. Template B is a three-replica fleet replaying the same recorded robot
traffic: it shows what changes when the decision must hold for a distributed deployment.
Compare Cyclone, Fast DDS, and Zenoh **within** each template. Do not compare Template
A values directly with Template B values; they use different workloads and metrics.

## Steps

Run the commands from any directory inside
the repository:

1. Fetch the workshop benchmark bag:

   ```bash
   cd "$(git rev-parse --show-toplevel)"
   scripts/workshop fetch-bag
   ```

   If the release asset is unavailable, use the local fallback and substitute
   `--bag /bags/synth` in step 3:

   ```bash
   scripts/workshop gen-bag synth 20
   ```

2. Run the synthetic baseline (Template A, no bag needed). It uses a minimal
   two-container deployment on Docker's `robots-net` bridge, with no applied network
   impairment. For each RMW, it generates an `Array1k` pub/sub stream at 1000 Hz with
   both best-effort and reliable QoS, then makes 200 `AddTwoInts` service calls. This
   controlled generated workload is why no MCAP bag is needed:

   ```bash
   scripts/workshop run \
      --template A --scenario S0 --rmw cyclone,fastdds,zenoh --duration 20
   ```

   Reserve 5-15 minutes on the workshop hardware.

3. Run the fetched bag across the fleet on a clean network (Template B):

   ```bash
   scripts/workshop run \
      --template B --bag /bags/benchmark \
         --scenario S0 --rmw cyclone,fastdds,zenoh --scale 3 --duration 30
   ```

   Reserve 10-20 minutes on the workshop hardware.

4. Each run prints its sweep directory: `docker/captures/<SWEEP_ID>/`. Keep both paths;
    they are the evidence for this exercise and the input to [Exercise 2](2_read_the_matrix.md).
    In each directory:

    - Open `comparison.md` and look first at **Cells and coverage**. It must list every
       RMW you requested, each with `Status` `ok`; the measured rows must say
       `(available)`. A missing value, `invalid`, or `failed` means do not compare that
       RMW yet. Use the matching cell's `.log`, `.probe.json`, or `.shaping.jsonl` only
       to diagnose a non-`ok` row.
    - Then read the cross-RMW raw-value table at the top. In Template A, find the
       receiver workload CPU row. In Template B, find estimated delivery shortfall,
       state maximum silence, and control arrival-gap p99. These are observed receipts
       and metadata-based estimates, not packet captures.
    - Use `comparison.csv` or `comparison.png` when you want the same raw comparison in
       a spreadsheet or chart.
    - Leave `pugh.md` for [Exercise 2](2_read_the_matrix.md), where you will inspect the
       weighted decision matrix and explain its recommendation.

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

**Template A cells all read `n/a`.** Check the `--profile rmw` A/B pair actually came
up: `docker compose ps ros2-cyclone ros2-cyclone-b`. If they're not there, `--profile
rmw` containers may have failed to build. Check `docker compose logs ros2-cyclone`.

**Template B stops with `missing bag: .../docker/bags/benchmark`.** The runner checks
the host-mounted bag before it starts the fleet. From `docker/`, confirm the download
created `bags/benchmark/metadata.yaml` with `ls bags/benchmark/`. If it is missing,
run `scripts/workshop fetch-bag` again. If the release asset is unavailable,
generate the fallback with `scripts/workshop gen-bag synth 20` and change
the Template B command to `--bag /bags/synth`; see [Exercise 4](4_generate_your_own_data.md)
or [the maintainer runbook](../../docker/RUNNING.md) for more detail.

Leave the core stack up and proceed to [Exercise 2](2_read_the_matrix.md).
