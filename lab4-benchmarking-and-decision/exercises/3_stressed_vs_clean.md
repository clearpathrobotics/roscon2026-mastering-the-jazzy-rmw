# 3. Stressed vs. clean

## Workshop strategy

Use the supplied stressed benchmark report for the required analysis. The
[`lab4-benchmarking-and-decision/exercises/benchmarks/stressed/`](benchmarks/stressed/) directory already contains both the clean
`S0` reference and the stressed `S2` results side by side in `comparison.md` and
`pugh.md`. This keeps the same MCAP, scale, duration, RMWs, and metrics available
without requiring a live sweep. It asks: **does the recommendation change when only the
network condition changes?**
Lab 3's live incident observations are useful context, but are not a prerequisite or
benchmark input.

## Steps

1. Open `comparison.md` and `pugh.md` in
   [`lab4-benchmarking-and-decision/exercises/benchmarks/stressed/`](benchmarks/stressed/). Use the **Scenario S0** section as
   the clean reference and the **Scenario S2** section as the impaired result. Do not
   compare a blended score.

2. Confirm the two scenario sections contain the same RMWs and criteria, then compare
   their scores and rankings. Use the matching sections in `comparison.md` to inspect
   the raw metric values behind a changed score.

3. Find the metric-backed criterion that moved the most (`reliability`, `latency_p99`,
   or `data_freshness`). Explain why the fixed impairment changed that criterion while
   the replay settings remained controlled. The manual criteria are unchanged
   provisional scores in the supplied reports; they are not evidence for this exercise.
   Changing or adding manual scores is left as an optional activity in
   [Exercise 4](4_generate_your_own_data.md).

<details>
<summary>Answer: what clean and stressed evidence show</summary>

The `S0` section compares baseline measurements under a controlled replay workload. The
`S2` section shows how those same candidates behave under a named, repeatable network
condition. The measured criteria reveal the effect of the impairment; the manual rows
remain neutral because no new manual assessment was made. Changing those manual scores
is left as an optional activity in [Exercise 4](4_generate_your_own_data.md). Use `S0`
to choose among RMWs when the deployment normally has a clean,
well-provisioned link. Use `S2` when delay and bursty loss are credible normal
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

This is the last mandatory Lab 4 exercise. [Exercise 4](4_generate_your_own_data.md) is
optional and is the hands-on path for generating and running your own synthetic data;
it is not a comparison against the supplied benchmark reports. [Exercise 5](5_after_the_workshop.md)
is for after the workshop.
