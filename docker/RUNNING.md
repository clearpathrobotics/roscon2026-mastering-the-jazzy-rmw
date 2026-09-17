# Running the Workshop Harness

**TL;DR: the scripts drive the containers for you.** You run everything from the
**host** (the machine with Docker). You never manually `docker run` a container or
shell into one to execute a test. [`scripts/workshop`](../scripts/workshop) is a
host-side observer that uses `docker compose` and `docker exec` under the hood.

`scripts/workshop` commands below run from the **repo root**; commands that call
`docker compose`/`docker buildx` directly run from **`docker/`**. Each block below
starts with the `cd` it needs.

---

## What runs where

| Runs on the **host** (you invoke) | Runs **inside containers** (scripts invoke for you) |
|---|---|
| `scripts/workshop`, `../lab4-benchmarking-and-decision/scripts/run_sweep.sh` | `../lab4-benchmarking-and-decision/scripts/class_probe.py`, run via `docker exec fleet-1` |
| Lab 4 analysis: `comparison.py`, `pugh.py`, `plot_comparison.py` | `ros2 bag play`, the fleet replicas' entrypoint |
| `docker compose up/down`, `docker exec` | `tc/netem`, applied via `docker exec` into each fleet replica |

So a single `scripts/workshop run …` internally does, per RMW cell:
`docker compose --profile fleet up -d --scale fleet=N` → apply netem inline →
`docker exec fleet-1 python3 /scripts/lab4/class_probe.py` → collect metrics →
tear the fleet down. You just call the one command.

---

## Prerequisites (one-time)

1. **Docker running.** Docker Desktop with WSL integration enabled for this distro,
   or native Linux Docker.
2. **Images available.** Pull from GHCR or build locally, from `docker/`:
   ```bash
   cd docker
   # Option A: pull from GHCR
   docker compose pull ubuntu-headless
   # Option B: build locally (slower, no login needed)
   docker compose build ubuntu-headless
   ```
3. **A bag to replay.** Drop any `*.mcap` file into `docker/bags/`. The `fleet`
   replicas loop the first bag they find there, namespacing topics under
   `/robot_<id>`. During the workshop, fetch the pre-published benchmark bag
   instead of generating one live (no wait), from the repo root:
   ```bash
   cd "$(git rev-parse --show-toplevel)"
   scripts/workshop fetch-bag                   # -> docker/bags/benchmark/
   ```
   No internet, or want your own instead? Generate a small synthetic bag locally:
   ```bash
   scripts/workshop gen-bag synth 20            # -> docker/bags/synth/
   ```
4. **Preflight check.** Confirm your kernel supports network shaping:
   ```bash
   bash docker/scripts/preflight.sh
   ```

Facilitators should complete [the pre-workshop checklist](FACILITATOR_CHECKLIST.md),
including the release-bag check, kernel modules, browser checks, smoke paths, and
full-matrix rehearsal.

---

## Run a test

```bash
cd "$(git rev-parse --show-toplevel)"

# 1. Bring up the core stack (ubuntu-headless + netdata). This runs preflight.
scripts/workshop up

# 2. Run a controlled Lab 4 sweep. The fleet is spun up and torn down automatically per cell.
scripts/workshop run \
    --template B --scenario constrained \
    --rmw cyclone,fastdds,zenoh,zenoh-lowlat \
  --scale 3 --duration 60

# 3. Tear the fleet down when finished.
scripts/workshop down
```

### Run RMWs / configs individually

Each variant is independent. Run one, some, or all, any time:

```bash
scripts/workshop run --rmw zenoh        --template B --scenario constrained --scale 3 --duration 60
scripts/workshop run --rmw zenoh-lowlat --template B --scenario constrained --scale 3 --duration 60
```

### Lab 4 templates

`run` is Lab 4's benchmark command. Template A is a two-container synthetic baseline;
Template B uses fixed MCAP traffic under the selected controlled scenario:

```bash
scripts/workshop run --template A --scenario S0 --rmw cyclone,fastdds,zenoh --duration 20
scripts/workshop run --template B --scenario S0,S2 --rmw cyclone,fastdds,zenoh --scale 3 --duration 30
```

### Lab 3's config-comparison fleet (mixed discovery config at scale)

A third deployment, independent of `run_sweep.sh`: a flat-topology fleet with a
pinned hub-and-spoke cohort plus N robots on the default (multicast) config, so
you can watch the good/bad config trade-off grow live in netdata instead of
only reading about it in Lab 1. See [Lab 3 Exercise 1](../lab3-stress-testing/exercises/1_take_the_fleets_pulse.md)
for the full walkthrough:

```bash
lab3-stress-testing/scripts/ex1_up.sh 6
scripts/workshop netdata up
scripts/workshop -t flat collector up
scripts/workshop -t flat down
```

---

## Where to see results

- **Live system metrics.** `http://localhost:19999` (netdata): host interface charts,
  **Apps CPU** process groups, and the workshop's Lab 3 charts. Bring it up with
  `scripts/workshop up`. Search for **Lab 3 Fleet** for the flat-topology config-comparison
  charts (discovery multicast rate, dropped packets, TCP retransmits) or **Lab 3 AP**
  for the routed shared-medium charts.

### Netdata deployment scope

Netdata runs as a workshop container, rather than being installed on the host. It shares
the host PID and network namespaces so **Apps CPU** can group the workshop processes, but
it deliberately does not receive the host cgroup hierarchy required for detailed
per-container CPU, memory, network, and I/O accounting. Its Docker socket access reports
container state and health only. This keeps the workshop portable and limits host access;
it is not a limitation of Netdata or Docker. A host-installed Netdata agent, or a
containerized agent explicitly granted read-only host cgroup access, can collect those
per-container resource metrics.
- **Files.** `docker/captures/<SWEEP_ID>/`:

  | File | Contents |
  |---|---|
  | `comparison.md` / `.csv` | cross-RMW table per (template, scenario) |
  | `comparison.png` | grouped bar chart rendered in `ubuntu-headless` |
  | `pugh.md` | weighted decision matrix per template |
  | `results.jsonl` | one structured result per cell (the raw data) |
  | `probe_<rmw>_<scenario>.json` | per-class message counts + metrics |
  | `sweep.json` | run metadata |

---

## Publishing a new benchmark bag (maintainers)

Bags are never committed to git (`.gitignore`: `*.mcap` / `*.bag`). The workshop's
canonical benchmark bag ships as a **GitHub Release asset** instead, so attendees
get it with `scripts/workshop fetch-bag` (no generation wait) without bloating the repo
or the clone. Update it independently of software version tags (`v0.1.0`, ...) under
a dedicated `workshop-bags` release:

```bash
cd "$(git rev-parse --show-toplevel)"
scripts/workshop up
scripts/workshop gen-bag benchmark 30          # or replay+re-record real data
tar -czf benchmark.tar.gz -C docker/bags benchmark

# Create a draft release first, so the release check cannot observe it before
# benchmark.tar.gz is attached.
gh release create workshop-bags --repo clearpathrobotics/roscon2026-workshop-mastering-the-jazzy-rmw \
  --draft --title "Workshop benchmark bags" --notes "Pre-generated bags for scripts/workshop fetch-bag."

# Upload or replace the asset while the release is still a draft.
gh release upload workshop-bags benchmark.tar.gz --repo clearpathrobotics/roscon2026-workshop-mastering-the-jazzy-rmw --clobber

# Publish only after the asset is present. Publication and later release edits
# trigger the fetch-bag CI check.
gh release edit workshop-bags --repo clearpathrobotics/roscon2026-workshop-mastering-the-jazzy-rmw --draft=false
```

Verify from a clean checkout: `rm -rf docker/bags/benchmark && scripts/workshop fetch-bag`.

---

## `run` options reference

| Flag | Default | Meaning |
|---|---|---|
| `--template` | `A` | deployment template(s), comma-separated: `A` (local), `B` (fleet/WiFi) |
| `--scenario` | template's set | scenario(s): `S0`, `S1`, `S2`, `S3`, `constrained` (or omit to use the template's list) |
| `--rmw` | `cyclone,fastdds` | RMW(s): `cyclone`, `fastdds`, `zenoh`, `zenoh-lowlat` |
| `--scale` | `3` | Template B fleet replicas |
| `--duration` | `20` | seconds per cell |
| `--bag` | `/bags/benchmark` | Template B MCAP directory (in-container mount) |
| `--rate` / `--msg` | `1000` / `Array1k` | Template A synthetic publish rate / message type |

The full vocabulary (templates, topic classes, scenarios, metrics, RMW variants,
decision weights) lives in [`../lab4-benchmarking-and-decision/scripts/benchmark.yaml`](../lab4-benchmarking-and-decision/scripts/benchmark.yaml).

Lists sweep the matrix, e.g.
`--rmw cyclone,fastdds,zenoh --scenario S0,S1` runs every combination.

---

## Driving a container by hand (optional)

You don't need this for the tests, but for manual exploration/debugging:

```bash
docker compose up -d ubuntu-headless
docker exec -it ubuntu-headless bash
# inside the container:
source /opt/ros/jazzy/setup.bash
ros2 topic list
```

---

## Troubleshooting

- **No per-container resource charts in netdata.** Expected for this workshop
  deployment; see [Netdata deployment scope](#netdata-deployment-scope). Use
  **Apps CPU**, host interface charts, and the Lab 3 dashboards instead.
- **Report generation failed.** Rebuild `ubuntu-headless` after pulling the
  current workshop revision so it includes the report dependencies.
- **netem no-ops.** `tc/netem` needs `sch_netem` (x86_64 only; not in the Jetson
  L4T kernel). Run `bash docker/scripts/preflight.sh` to check.
- **Fleet replicas not finding a bag.** Confirm a `*.mcap` exists under `docker/bags/`.
  Generate one: `scripts/workshop gen-bag`.
