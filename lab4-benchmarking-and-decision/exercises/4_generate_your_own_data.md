# 4. Generate and run your own synthetic data (optional)

**This exercise is optional and time permitting.** Exercises 1-3 use the supplied
pre-recorded benchmark reports. This exercise is separate: generate a synthetic bag and
run your own benchmark so you can inspect the complete workflow. Do not treat it as a
comparison against the supplied benchmark results or as a replacement for them.

## Steps

Run the commands from any directory inside
the repository:

1. Generate a small synthetic bag with one topic per topic class
   (`/camera/image_raw` sensor, `/cmd_vel` control, `/tf` state):

   ```bash
   cd "$(git rev-parse --show-toplevel)"
   scripts/workshop gen-bag synth 30
   ```

   The command runs [`lab4-benchmarking-and-decision/scripts/gen_bag.py`](../scripts/gen_bag.py) (a live publisher) and `ros2
   bag record` together for 30 seconds, then stops both for you.

2. Run a fresh Template A synthetic baseline. Template A does not consume the bag; it
   generates its controlled pub/sub and service workload itself:

   ```bash
   scripts/workshop run \
      --template A --scenario S0 --rmw cyclone,fastdds,zenoh --duration 20
   ```

3. Run a fresh Template B benchmark against your synthetic bag:

   ```bash
   scripts/workshop run \
      --template B --bag /bags/synth \
         --scenario S0 --rmw cyclone,fastdds,zenoh --scale 3 --duration 30
   ```

4. Run the same synthetic bag under clean and stressed conditions:

   ```bash
   scripts/workshop run \
      --template B --bag /bags/synth \
         --scenario S0,S2 --rmw cyclone,fastdds,zenoh \
         --scale 3 --duration 30
   ```

   `S2` applies 30 ms +/- 10 ms delay and 5% bursty loss. Keep the bag, scale, duration,
   and RMW list unchanged so only the network condition changes. This is an experiment
   on your generated workload, not a comparison against the supplied benchmark
   directories.

5. **Optional: add the constrained scenario.** If time allows, rerun the same synthetic
   bag with `S0`, `S2`, and `constrained`:

   ```bash
   scripts/workshop run \
      --template B --bag /bags/synth \
         --scenario S0,S2,constrained --rmw cyclone,fastdds,zenoh \
         --scale 3 --duration 30
   ```

   `constrained` applies 50 ms +/- 15 ms delay, 1% bursty loss, and a 50 Mbit/s
   per-link cap. Keep the bag, scale, duration, and RMW list unchanged so only the
   network condition changes.

6. Read the new Template A and Template B `comparison.md`, `comparison.csv`, and
   `pugh.md` reports as standalone experiments. Check coverage and raw values before
   interpreting either ranking. Describe the workload you generated and what the results
   suggest about that workload; do not claim that it confirms or overturns the supplied
   benchmark.

7. **Optional: test priorities for your own deployment.** Edit only the relevant `A:`
   or `B:` values under `decision.weights` in `benchmark.yaml`, keeping weights in the
   1-5 range. Then regenerate your new matrix without rerunning the benchmark:

   ```bash
   docker exec --user "$(id -u):$(id -g)" -e HOME=/tmp ubuntu-headless \
     python3 /scripts/lab4/pugh.py /captures/<SWEEP_ID>
   ```

   Compare the new `pugh.md` with the earlier one and identify which changed weight
   changed the ranking. Use alternate weights to make a deployment-specific decision,
   not to manufacture a preferred winner.

8. **Optional: score the manual criteria.** Create `manual_scores.yaml` beside your
   sweep's `pugh.md`. Scores are $1$-$5$ assessments, not measurements; give every RMW
   a score only when your observations justify it. For example:

   ```yaml
   B:
      S0:
         cyclone: { ease_config: 4, discovery_robust: 4, loss_jitter_behaviour: 3 }
         fastdds: { ease_config: 3, discovery_robust: 3, loss_jitter_behaviour: 3 }
         zenoh: { ease_config: 4, discovery_robust: 4, loss_jitter_behaviour: 4 }
   ```

   If you ran `S2` or `constrained`, add a corresponding scenario section and score the
   manual behaviour criteria from that scenario's observations rather than copying the
   `S0` scores.

   Regenerate the matrix with the command in Step 7. The `†` marker disappears only for
   criteria you scored. [Exercise 5](5_after_the_workshop.md) has the same workflow for
   applying your own deployment evidence.

9. **Optional: inspect Netdata during a repeat run or at home.** Use it as supporting
   runtime context to ask whether the bottleneck is in the shaped network or host CPU.
   In **Apps CPU**, Template B appears as `lab4_replay` and `lab4_probe`. Template A
   appears as `lab4_synthetic`. `lab4_zenoh_router` appears only for the router-based
   Zenoh variant. This does not replace the recorded benchmark metrics, but it can
   reveal a run invalidated by machine saturation.

<details>
<summary>Answer: synthetic data is a separate experiment</summary>

`gen_bag.py`'s three topics are picked to exercise the same taxonomy
(`sensor`/`control`/`state`) as a real robot's traffic, but they're synthetic in the
literal sense: fixed size, fixed rate, no bursts, and no correlated load across topics the
way a real robot's sensor stack produces. It may produce different absolute values or a
different ordering because the workload shape is different. Treat the result as evidence
about this generated workload, not as a general claim about an RMW. Check the raw values,
coverage, and validity before explaining the result. A recording from your own deployment
is more relevant than either workshop workload; Exercise 5 shows how to use one.
</details>

## When it does not work

**`gen-bag` finishes but `bags/synth/metadata.yaml` is missing.** Check
`docker compose logs ubuntu-headless` for a publisher or recording error. The publisher
needs to actually be running when `ros2 bag record` starts.

Also see [Exercise 5](5_after_the_workshop.md) for bringing a *real* MCAP from your own
deployment instead of a synthetic one. That is the version of this exercise worth doing
at home with your actual data.
