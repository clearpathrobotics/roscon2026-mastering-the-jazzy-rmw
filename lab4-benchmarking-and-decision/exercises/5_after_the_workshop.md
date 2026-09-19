# 5. After the workshop

Like [Lab 3's Exercise 5](../../lab3-stress-testing/exercises/5_after_the_workshop.md),
these activities are intended for independent work after the workshop. Choose the one
that best matches your deployment and run it with your own data where possible.

## Bring your own MCAP

The purpose of Lab 4 is to make this comparison repeatable on your system: drop a
recording from *your* robot into
`docker/bags/` and point `--bag` at it instead of the workshop-provided one or a
synthetic one. From the repository root:

```bash
cp -r /path/to/your/recording docker/bags/my_deployment
cd "$(git rev-parse --show-toplevel)"
scripts/workshop run \
    --template B --bag /bags/my_deployment \
    --rmw cyclone,fastdds,zenoh --scale 3 --duration 30
```

If your bag's topic names don't match the `sensor`/`control`/`state` regexes in
[`lab4-benchmarking-and-decision/scripts/benchmark.yaml`](../scripts/benchmark.yaml), add your own patterns under
`topic_classes.*.match` so `class_probe.py` actually buckets them.

## Score the manual criteria for real

[Exercise 2](2_read_the_matrix.md) pointed out that `ease_config`, `discovery_robust`,
and `loss_jitter_behaviour` default to a neutral 3/5 until someone scores them by hand.
You have real experience to draw on by now: Lab 1's config authoring, Lab 2's capture
debugging, Lab 3's live degradation. Write a `manual_scores.yaml` next to a sweep's
`pugh.md` (see the `decision:` block in `benchmark.yaml` for the expected shape) and
re-run `pugh.py` against that sweep directory. How much does the ranking move once
those criteria reflect actual experience instead of a placeholder?

For example, for a sweep at `docker/captures/<SWEEP_ID>/`, create
`manual_scores.yaml` with the template, RMW, and criterion keys:

```yaml
B:
    S0:
        cyclone: { ease_config: 4, discovery_robust: 4, loss_jitter_behaviour: 3 }
        fastdds: { ease_config: 3, discovery_robust: 3, loss_jitter_behaviour: 3 }
        zenoh: { ease_config: 4, discovery_robust: 4, loss_jitter_behaviour: 4 }
```

Then regenerate the matrix without rerunning the benchmark:

From `docker/`:

```bash
docker exec ubuntu-headless python3 /scripts/lab4/pugh.py /captures/<SWEEP_ID>
```

## Optional: add a fourth contender

`benchmark.yaml` already defines `zenoh-lowlat` (a router-based, low-latency-tuned Zenoh
variant) alongside plain `zenoh`. Run it through the same sweep as a fourth column:

```bash
scripts/workshop run \
    --template B --bag /bags/benchmark \
    --rmw cyclone,fastdds,zenoh,zenoh-lowlat --scale 3 --duration 30
```

Does a fourth, more specifically tuned variant change the recommendation, or only add
another column to the table?

## Optional: automate the whole thing

`scripts/workshop run` prints its comparison/Pugh output paths on stdout. Wire it into a CI
job or a cron task against a fixed reference bag, and you have a regression check for
"did upgrading an RMW version change the answer", which is the same question this lab
answers for a point-in-time comparison, run continuously instead of once.
