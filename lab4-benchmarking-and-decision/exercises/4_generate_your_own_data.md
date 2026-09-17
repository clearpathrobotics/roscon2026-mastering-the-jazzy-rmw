# 4. Compare synthetic and recorded workloads (optional)

**This exercise is optional.** Its purpose is to show that an RMW recommendation depends
on the workload, not just the RMW. Do it only if Exercise 1 used the workshop-provided
`benchmark` bag. If you used `synth` as the fallback, you have already generated and run
the synthetic workload; continue to [Exercise 5](5_after_the_workshop.md) when ready to
use a recording from your own deployment.

## Steps

Run the commands from the repository's `docker/` directory. From any directory inside
the repository:

1. Generate a small synthetic bag with one topic per topic class
   (`/camera/image_raw` sensor, `/cmd_vel` control, `/tf` state):

   ```bash
   cd "$(git rev-parse --show-toplevel)"
   scripts/workshop gen-bag synth 20
   ```

   If you already generated `synth` as Exercise 1's fallback, do not generate it again;
   this exercise's recorded-versus-synthetic comparison is unavailable without the
   workshop `benchmark` bag. The command runs [`gen_bag.py`](../scripts/gen_bag.py) (a
   live publisher) and `ros2 bag record` together for 20 seconds, then stops both for
   you.

2. Re-run Exercise 1's Template B sweep against your synthetic bag instead of the
   workshop-provided one:

   ```bash
   scripts/workshop run \
      --template B --bag /bags/synth \
         --scenario S0 --rmw cyclone,fastdds,zenoh --scale 3 --duration 30
   ```

3. Compare this sweep's `comparison.md` with the **Template B S0** report from Exercise
   1. Keep the RMW list, scale, and duration the same, so the bag is the only intended
   difference. The synthetic bag's traffic shapes are smaller and more regular than a
   real recording. Does that change the ranking, or only the separation between values?

<details>
<summary>Answer: the recommendation is conditional on the workload</summary>

`gen_bag.py`'s three topics are picked to exercise the same taxonomy
(`sensor`/`control`/`state`) as a real robot's traffic, but they're synthetic in the
literal sense: fixed size, fixed rate, no bursts, and no correlated load across topics the
way a real robot's sensor stack produces. It may produce different absolute values or a
different ordering because the workload shape is different. Treat that as evidence about
workload sensitivity, not as a general claim about an RMW. If the synthetic run and the
workshop recording disagree, inspect the raw values, coverage, and validity before
explaining why. A recording from your own deployment is more relevant than either
workshop workload; Exercise 5 shows how to use one.
</details>

## When it does not work

**`gen-bag` finishes but `bags/synth/metadata.yaml` is missing.** Check
`docker compose logs ubuntu-headless` for a publisher or recording error. The publisher
needs to actually be running when `ros2 bag record` starts.

Also see [Exercise 5](5_after_the_workshop.md) for bringing a *real* MCAP from your own
deployment instead of a synthetic one. That is the version of this exercise worth doing
at home with your actual data.
