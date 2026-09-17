# ROSCon 2026 Workshop: Mastering the Jazzy RMW

**A performance-driven framework for ROS 2 middleware selection and tuning.**

Default RMW settings can fail as systems scale. Many teams inherit tuning configurations that worked on previous projects but fail under new loads. This workshop replaces guesswork with a repeatable workflow for ROS 2 Jazzy.

The session centers on tuning and benchmarking through hands-on labs. Participants configure and measure Fast DDS, Cyclone DDS, and Zenoh instead of treating middleware as a black box. Using a multi-modal MCAP dataset, attendees run high-scale stress tests on their own hardware to see how middleware behaviour has changed since Humble. The workshop focuses on practical techniques for resolving bottlenecks that only appear at scale.

Attendees leave with a reusable benchmarking workflow and enough data to justify tuning decisions.

## Workshop labs

### Lab 1: Configuration & Tuning

Start from the defaults, see why they fail, and work through the parameters that matter most in practice. The lab also reviews application templates for common use cases and how to apply them to ROS 2 Jazzy systems.

[Lab 1 README](lab1-configuration-tuning/README.md)

### Lab 2: ROS 2 on the Wire

Read the traffic your ROS 2 system actually puts on the network: discovery, QoS negotiation, fragmentation, and where messages are lost. The lab uses Webshark, a browser-based interface for Wireshark, with ROS 2 filter presets for live traffic and recorded captures of specific failures.

[Lab 2 README](lab2-on-the-wire/README.md)

### Lab 3: Stress Testing

Watch a healthy fleet degrade under a shared network bottleneck, then diagnose it with live Netdata metrics and ROS 2 topic behaviour. Compare Cyclone DDS against Zenoh's router-less mesh under that shared load.

[Lab 3 README](lab3-stress-testing/README.md)

### Lab 4: Benchmarking & Decision Matrix

Replay one MCAP workload across Fast DDS, Cyclone DDS, and Zenoh so every stack sees identical traffic, then weigh the results into a decision matrix you can apply to your own system.

[Lab 4 README](lab4-benchmarking-and-decision/README.md)

> [!IMPORTANT]
> **Requirements:** Linux, Docker Compose 2.20+, 16 GB RAM, and 15 GB free.

## Prepare your computer

<details>
<summary><strong>Setup and platform details</strong></summary>

The labs run in Docker in a Linux environment on your own laptop. You'll need to check
your computer's compatibility.

| | |
|---|---|
| **RAM** | 16 GB |
| **Disk** | ~15 GB free. An SSD is recommended. |
| **OS** | A Linux environment. Native Linux, WSL2 and a VM all count. |
| **Docker** | Docker Engine recommended. Docker Desktop is untested. |
| **Docker Compose** | v2.20 or newer, the `docker compose` plugin rather than the old `docker-compose` script |

### 1. Install Docker

Docker Engine plus Compose v2.20 or newer, inside the Linux environment you will use.
[docs.docker.com/engine/install](https://docs.docker.com/engine/install/)

If you are setting up native Linux for the workshop, use Ubuntu on amd64. Ubuntu
22.04, 24.04 and 26.04 are all suitable because the labs run in Docker.

### 2. Check your computer

Run the compatibility script inside your Linux environment:

```bash
curl -fsSLO https://raw.githubusercontent.com/clearpathrobotics/roscon2026-mastering-the-jazzy-rmw/main/compat-check.sh
bash compat-check.sh
```

It reads your system and prints a summary line at the end. Keep that line for step 3.

To check by hand instead:

```bash
docker run --rm hello-world
docker compose version                                  # 2.20 or newer
free -h                                                 # 16 GB RAM
df -h ~                                                 # ~15 GB free (roughly; the script checks where Docker actually stores data)
lsmod | grep -E 'sch_netem|sch_htb|ifb|act_mirred'      # sch_netem is the one that matters; the rest add bidirectional shaping
```

Docker is required for every lab. `sch_netem` drives the network-shaping exercises.
`sch_htb`, `ifb` and `act_mirred` only add bidirectional (ingress) shaping on top, and
the exercises fall back to egress-only impairment without them. If the last command
does not list all four modules, run `sudo modprobe -a sch_netem sch_htb ifb act_mirred`
and check again. If that fails, see "If a check fails" below.

`lsmod` lists only loaded modules and misses ones built into the kernel, so a blank result
is not proof they are missing. The container test below settles it, using the kernel your
containers actually get.

### 3. Fill in the form

Registered attendees get the form link by email from the organizers. It is not posted
in this repository.

Tell us what you are bringing and how the check went. If it did not pass, say whether you
could bring a different computer instead. Please answer either way.

### If ROS 2, Linux or networking are new to you

Not a requirement, but we are unlikely to repeat content from our 2024 networking
workshop, so it is worth a look beforehand:

[Demystifying ROS 2 Networking](https://github.com/clearpathrobotics/roscon2024-workshop-demystifying-ros2-networking).

### Platform and troubleshooting reference

<details>
<summary><strong>Platform support</strong></summary>

The workshop needs a Linux environment with Docker Engine. Native Linux, WSL2 and a VM
all count. Run the script inside whichever one you will use on the day, not on the host
around it.

Prefer a normal desktop or server install. Minimal, cloud and container images may omit
the network degradation modules. Packaging varies by distribution and kernel.

| Your setup | The workshop | Network shaping |
|---|---|---|
| Native Ubuntu 22.04, 24.04 or 26.04 on amd64 | Recommended | Yes |
| Other Linux on amd64 | Expected to work | Depends on your kernel. Run the check. |
| Windows with WSL2 | Works | Yes on a current kernel. Older ones lack it, so run `wsl --update`. |
| Linux VM on an amd64 host | Works | Yes |
| Linux on arm64 | Untested | Depends on your kernel. Run the check. |
| NVIDIA Jetson (L4T) | Not validated | No, the stock L4T kernel ships without the modules. |
| Any Mac | Untested | Untested. Run the script and tell us what you get. |
| Docker Desktop, any OS | Untested | Skip the host checks and run the container test below instead. |

The network-shaping exercises add delay and packet loss to a robot's link so you can see
how each RMW copes with bad Wi-Fi, using Linux `tc`/NetEm from your kernel. `sch_netem`
alone is enough to run them egress-only. If your kernel does not have `sch_netem`, those
exercises are skipped and everything else in the labs still runs.

</details>

<details>
<summary><strong>If a check fails</strong></summary>

Modules present but not loaded, which is the usual case. The `-a` matters here, because
plain `modprobe sch_netem sch_htb ifb act_mirred` treats the last three names as
parameters for `sch_netem` and only loads that one:

```bash
sudo modprobe -a sch_netem sch_htb ifb act_mirred
```

Windows with WSL2, in PowerShell, then reopen your Linux terminal:

```powershell
wsl --update
wsl --shutdown
```

Modules absent on native Linux, common on minimal and cloud images. Some Ubuntu kernels
provide them in a version-matched extra-modules package:

```bash
sudo apt install linux-modules-extra-$(uname -r)
```

If that exact package does not exist, check how your distribution or kernel provides
`sch_netem`, `sch_htb`, `ifb` and `act_mirred`. Package names are not portable.

</details>

<details>
<summary><strong>Docker Desktop and macOS</strong></summary>

On macOS, run the script and put the result in the form.

On Docker Desktop, any OS, the host-side checks may not reflect what containers actually
get, since Docker Desktop can run them on a different kernel. Use this container test
instead, which confirms NetEm works where the labs need it:

```bash
docker run --rm --cap-add NET_ADMIN alpine sh -c '
  apk add -q iproute2 || { echo "no network from inside containers"; exit 2; }
  tc qdisc add dev lo root netem delay 1ms || { echo "no netem"; exit 3; }
  echo "netem works"'
```

Alpine is not a workshop image, just a 4 MB base to run `tc` in. The command installs
`iproute2` inside it, so it fails at the first line if the container cannot reach the
network. Fix that first, because pulling the workshop images needs the same connection.

</details>

### If your computer cannot run it

See whether you can bring a different computer, or borrow one from a colleague.

If that is not possible, say so in the form.

</details>

## Workshop materials

> [!TIP]
> Watch this repository to get notified of updates.

The full lab instructions and content will be published here on
**Tuesday 15 September 2026**.

Clone the repository and pull the Docker images before you travel. The images are
several GB, and conference Wi-Fi will not cope with a room full of people pulling
them at once.

## After the workshop

To take the Lab 2 method to your own hardware, see
[using this on a real robot](docker/webshark/README.md#using-this-on-a-real-robot)
and the field guide it links. A capture is just a file, so the machine that records
it and the machine that reads it need nothing to do with each other.

<details>
<summary><strong>Tools that came up in scoping but are not taught in the timed labs</strong></summary>

- [ros2_tracing](https://github.com/ros2/ros2_tracing) for application-level
  debugging: executor delay, callback duration. It goes further than anything in
  Lab 2, at the cost of instrumenting your application.
- [performance_test](https://gitlab.com/ApexAI/performance_test) for standardized
  throughput and latency benchmarking.
- [htop](https://htop.dev/) and [iftop](http://www.ex-parrot.com/pdw/iftop/) for general
  CPU and network monitoring, a lighter complement to [netdata](https://www.netdata.cloud/).
  Both ship in the workshop image.
- [Wireshark](https://www.wireshark.org/) proper, the engine that Webshark is a
  browser-based skin over. Reach for it once you outgrow the presets and want
  Decode As, Follow Stream or saved filter profiles.
- [Netshoot](https://github.com/nicolaka/netshoot) is an optional network-
  troubleshooting toolbox that can enter another container's network namespace
  without modifying its image. After starting Lab 3's `wifi-ap`, try it as a
  sidecar:

  ```bash
  docker run --rm -it --network container:wifi-ap nicolaka/netshoot
  ```

  **Challenge:** choose one workshop container and use Netshoot to make a useful
  observation or diagnose a networking problem. The workshop itself does not
  require Netshoot.

</details>

## Licence

Apache-2.0, with one exception. The Webshark viewer in `docker/webshark/` is a modified copy of
[QXIP/node-webshark](https://github.com/QXIP/node-webshark), so `index.html`, `root.js` and
`sharkd_dict.js` are GPL-2.0-or-later. [`LICENSE`](LICENSE) names those three files.
[`docker/webshark/THIRD-PARTY.md`](docker/webshark/THIRD-PARTY.md) covers what we changed and
what else the image ships.

## Questions

Let us know in the form, or feel free to open an issue.
