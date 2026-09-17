# Facilitator Checklist

Run this checklist on the workshop hardware before the event. Keep the resulting
`captures/<SWEEP_ID>/` directories as the reference outputs for the session.

## Prepare the host

1. Use native Linux or WSL2 on amd64 with Docker Compose v2, at least 16 GB RAM,
   and roughly 15 GB free disk space.
2. Start Docker, then preload the main-stack images and build the Lab 1
   operator view reused by Lab 3:

   ```bash
   cd docker
   docker compose pull ubuntu-headless
   docker compose -f netdata/netdata.yml --profile netdata build netdata
   # Rebuild when the checkout's Dockerfile changed, or when GHCR is unavailable:
   docker compose build ubuntu-headless
   cd lichtblick
   docker compose -f lichtblick.yml build lichtblick
   cd ..
   ```

3. Load the modules required for live netem and AP shaping, then verify the host:

   ```bash
   sudo modprobe -a sch_netem ifb act_mirred sch_htb
   bash scripts/preflight.sh
   ```

4. Verify the published benchmark asset before attendees arrive:

   ```bash
   rm -rf bags/benchmark
   cd "$(git rev-parse --show-toplevel)"
   scripts/workshop fetch-bag
   test -f docker/bags/benchmark/metadata.yaml
   ```

   `workshop-bags` publication and later release edits trigger CI that runs this
   fetch and checks both `metadata.yaml` and an MCAP file. Generate `synth`
   locally only as the documented fallback when the published asset is
   intentionally unavailable.

5. Rebuild Webshark if necessary:

   ```
   cd docker/webshark/
   docker compose -f webshark.yml up -d --build
   cd ../..
   ```
## Smoke the live paths

Run everything below from the repo root:

```bash
cd "$(git rev-parse --show-toplevel)"
```

Start the core stack, run preflight, then verify the bundled ROS toolset inside
the observer:

```bash
bash scripts/workshop up
bash scripts/workshop preflight
docker exec -i observer bash -s < docker/ubuntu-headless/tool_check.sh
```

Verify the two-robot routed/AP path and clean it up:

```bash
scripts/workshop -t routed up 2
bash docker/scripts/host_forwarding.sh check
bash lab3-stress-testing/scripts/routed_test.sh --verbose
scripts/workshop -t routed netem good
scripts/workshop -t routed netem list
docker exec wifi-ap bash -lc \
  'timeout 5 tshark -q -i any -f "net 172.40.0.0/16" -z io,stat,5 || test $? -eq 124'
scripts/workshop -t routed down
```

Run one Lab 4 bridge bag cell. This proves the controlled benchmark path, capture
pipeline, and report output work on this hardware:

```bash
scripts/workshop run --template B \
   --scenario S2 --rmw cyclone --scale 1 --duration 10
```

Confirm browser access to Netdata at `http://localhost:19999` and Lichtblick at
`http://localhost:8080`. In Netdata, navigate to **Metrics > Search charts > Lab
3 Fleet**, then open **lab3 > Config comparison**. Start the live operator path
when validating Lichtblick:

```bash
scripts/workshop -t routed up 2
scripts/workshop -t routed down
```

## Rehearse the full matrices

Run these exact commands on the workshop hardware before the event. Durations
vary with image cache, CPU, and Docker backend; reserve the stated windows rather
than treating the per-cell measurement duration as total wall clock.

| Lab | Command | Expected wall clock |
| --- | --- | --- |
| Lab 3, live diagnosis | `scripts/workshop -t routed up 15 cyclone`, then `scripts/workshop -t routed netem bad` | 10-15 minutes |
| Lab 4, Template A | `scripts/workshop run --template A --scenario S0 --rmw cyclone,fastdds,zenoh --duration 20` | 5-15 minutes |
| Lab 4, Template B | `scripts/workshop run --template B --scenario S0,S2,constrained --bag /bags/benchmark --rmw cyclone,fastdds,zenoh --scale 3 --duration 30` | 15-25 minutes |

Each finished sweep prints an exact `cat .../comparison.md` command. Preserve its
whole capture directory, including `results.jsonl`, `comparison.md`, `pugh.md`,
and routed AP queue artifacts. Use those outputs as workshop reference data; do
not make cross-RMW performance claims from only the smoke cells.
