# 3. Stressed vs. clean

This exercise runs its own controlled stressed sweep with the same MCAP, scale,
duration, RMWs, and metrics as the clean Template B baseline. It asks: **does the
recommendation change when only the network condition changes?** Lab 3's live incident
observations are useful context, but are not a prerequisite or benchmark input.

## Steps

Run the commands from any directory inside
the repository:

1. Run the same supplied MCAP under two fixed bridge conditions. `S0` is the clean
   reference. `S2` applies the complete `heavy` profile: 30 ms +/- 10 ms delay and 5%
   bursty loss. Every RMW receives the same controlled replay workload for the same
   duration:

   ```bash
   cd "$(git rev-parse --show-toplevel)"
   scripts/workshop run \
      --template B --bag /bags/benchmark \
       --scenario S0,S2 --rmw cyclone,fastdds,zenoh --scale 3 --duration 30
   ```

   If Exercise 1 used the local synthetic fallback, replace `--bag /bags/benchmark`
   with `--bag /bags/synth`. Use the same bag for both `S0` and `S2`, so the network
   condition remains the only intended difference. The synthetic bag is a valid
   controlled workload, but its smaller, more regular traffic is less representative
   than the workshop recording.

   **Optional: add `constrained` as a third scenario** when time permits. Change the
   scenario list to `--scenario S0,S2,constrained`; the runner performs one cell for
   each RMW under each of the three conditions and writes a separate **Scenario
   constrained** section to the same report. `constrained` is not an extra setting on
   `S2`: it is its own per-replica link profile with 50 ms +/- 15 ms delay, 1% bursty
   loss, and a 50 Mbit/s cap. Keep the bag, scale, duration, and RMW list unchanged so
   you can compare the RMWs within that scenario, or compare one RMW's `S0`, `S2`, and
   `constrained` results as only the link condition changes.

2. Open the exact `pugh.md` path printed at the end of the sweep. It has separate
   **Scenario S0** and **Scenario S2** sections. Do not compare a blended score.

3. Confirm the two sections contain the same RMWs and criteria, then compare their
   scores and rankings. Use `comparison.md` to inspect the raw metric values behind a
   changed score.

4. Find the criterion that moved the most. Is it metric-backed (`reliability`,
   `latency_p99`, or `data_freshness`) or manual? Explain why the fixed impairment
   changed that criterion while the replay settings remained controlled.

5. **Optional: inspect Netdata during a repeat run or at home.** Use it as supporting
   runtime context to ask whether the bottleneck is in the shaped network or host CPU.
   In **Apps CPU**, Template B appears as `lab4_replay` and `lab4_probe`. Template A
   appears as `lab4_synthetic`. `lab4_zenoh_router` appears only for the router-based
   Zenoh variant. This does not replace the recorded benchmark metrics, but it can
   reveal a run invalidated by machine saturation.

<details>
<summary>Answer: what clean and stressed evidence show</summary>

The clean section compares baseline measurements under a controlled replay workload.
The stressed section shows how those same candidates behave under a named, repeatable
network condition. Use `S0` to choose among RMWs when the deployment normally has a
clean, well-provisioned link. Use `S2` when delay and bursty loss are credible normal
operating risks, such as a robot using busy or unreliable Wi-Fi. Use `constrained` when
the deployment also has a plausible per-robot bandwidth limit.

Do not select an RMW merely because it ranks highest in a scenario you do not expect to
operate in. Instead, start with the link condition the system must tolerate, then check
the raw `comparison.md` values behind that scenario's ranking: are delivery shortfall,
control arrival gaps, and state silence acceptable for the robot's job? A fleet that can
briefly drop a camera frame may tolerate a different outcome from one whose control or
state traffic must remain timely. If both clean and stressed links are realistic, record
both rankings and make the decision against the more consequential operating risk rather
than averaging them.

Lab 3's live exercise makes the operator consequence visible and helps score qualitative
criteria such as debugging or loss/jitter behaviour. Lab 4 supplies the repeatable
measurements needed to defend the final decision.
</details>

## When it does not work

**The S2 report looks identical to S0.** Open the cell's `.shaping.jsonl` artifact and
inspect the recorded `pre_measurement` and `post_measurement` validity for every fleet
replica. Do not treat an "applied netem" log line as proof. A missing or mismatched
profile makes the cell invalid. Missing host shaping modules are one possible cause.

**The report contains only one scenario.** Confirm `--scenario S0,S2` was passed without
spaces and that both scenarios are allowed for Template B in `benchmark.yaml`.

This is the last mandatory Lab 4 exercise. [Exercise 4](4_generate_your_own_data.md) is
optional (bring or generate your own data instead of the workshop-provided bag), and
[Exercise 5](5_after_the_workshop.md) is for after the workshop.
