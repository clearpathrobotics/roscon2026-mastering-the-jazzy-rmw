# docker/

![Build](https://github.com/clearpathrobotics/roscon2026-workshop-mastering-the-jazzy-rmw/actions/workflows/build.yml/badge.svg)

`ubuntu-headless` is the workshop's ROS 2 image: Ubuntu 24.04, ROS 2 Jazzy, all three RMWs,
and the networking and capture tools the labs use. Every lab runs it.

The exercises and the RMW configs live in the labs. The shared image reuses Lab 1's generic
profiles; Lab 3 and Lab 4 add only topology-specific profiles through their own mounts.

```
ubuntu-headless/    the image and its tool check; generic RMW profiles come from Lab 1
webshark/           lab 2's packet viewer, see its own README
scripts/            preflight.sh (host check) and its shared logging helpers
docker-compose.yml  a talker and a listener, the example below
```

## Try it

A talker and a listener in separate containers on a bridge, which is the smallest thing that
crosses the wire:

```bash
docker compose up
COMPOSE_PROFILES=zenoh RMW_IMPLEMENTATION=rmw_zenoh_cpp docker compose up
```

`ROS_DOMAIN_ID` and `RMW_IMPLEMENTATION` come from `.env`. Override either one for a single
run by setting it on the command line, the way the Zenoh example above does. Its profile adds
the router that `rmw_zenoh_cpp` requires; the talker and listener remain separate containers.

## Checks

Run `scripts/preflight.sh` before you start. It tells you whether your host can run the
containers and the network shaping. `ubuntu-headless/tool_check.sh` verifies the image's
toolset from inside a container.

CI builds both arches, runs `tool_check.sh`, and brings the compose file up on each of the
three RMWs, failing if the listener never receives. amd64 is the supported target. Shaping
does not work on the Jetson L4T kernel, which ships without `sch_netem`.

## Building

```bash
docker buildx bake
```
