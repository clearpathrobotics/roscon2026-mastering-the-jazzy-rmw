# ROSCon 2026 Workshop - Mastering the Jazzy RMW

### A Performance-Driven Framework for ROS 2 Middleware Selection and Tuning

Default RMW settings can fail as systems scale. Many teams inherit tuning
configurations that worked on previous projects but fail under new loads. This
workshop replaces guesswork with a repeatable workflow for ROS 2 Jazzy.

The session centers on tuning and benchmarking through hands-on labs. Participants
configure and measure Fast DDS, Cyclone DDS, and Zenoh instead of treating
middleware as a black box. Using a multi-modal MCAP dataset, attendees run
high-scale stress tests on their own hardware to see how middleware behavior has
changed since Humble.

---

# Before the workshop

The labs run in Docker in a Linux environment on your own laptop. You'll need to check your computer's compatibility.

Come back on September 15, 2026 to download the repo and docker images.

## 1. Check your computer

A script is provided for convenience to check your Linux environment:

```bash
curl -fsSLO https://raw.githubusercontent.com/clearpathrobotics/roscon2026-mastering-the-jazzy-rmw/main/compat-check.sh
bash compat-check.sh
```

It reads your system and prints a summary line at the end. Keep that line for
step 2.

To check by hand instead:

```bash
docker run --rm hello-world
docker compose version                                  # 2.20 or newer
free -h                                                 # 16 GB RAM
df -h ~                                                 # ~15 GB free
lsmod | grep -E 'sch_netem|sch_htb|ifb|act_mirred'      # sch_netem is the one that matters; the rest add bidirectional shaping
```

Docker is required for every lab. `sch_netem` is what drives the network-shaping
part of Lab 3; `sch_htb`, `ifb` and `act_mirred` only add bidirectional (ingress)
shaping on top, and Lab 3 falls back to egress-only impairment without them. If
the last command doesn't list all four modules, run `sudo modprobe -a sch_netem
sch_htb ifb act_mirred` and check again. If that fails, see [Fixes](#fixes).

`lsmod` only shows modules already loaded, so it can't rule shaping out for
certain. The container test in [Fixes](#fixes) does, by using the kernel your
containers actually get.

## 2. Fill in the form

**<POLL-LINK>**

Tell us what you are bringing and how the check went. If it did not pass, say whether
you could bring a different computer instead. Please answer either way.

## 3. Install Docker

Docker Engine plus Compose v2.20 or newer, inside the Linux environment you will use.
[docs.docker.com/engine/install](https://docs.docker.com/engine/install/)

Macs are untested. If you are bringing one, run the script and tell us the result in
the form.

## Optional reading

Not a requirement. We are unlikely to repeat content from our 2024 networking
workshop, so it is worth a look if ROS 2, Linux or networking are new to you:

[Demystifying ROS 2 Networking](https://github.com/clearpathrobotics/roscon2024-workshop-demystifying-ros2-networking).

---

# Compatibility

| | |
|---|---|
| **RAM** | 16 GB |
| **Disk** | ~15 GB free. An SSD is recommended. |
| **OS** | A Linux environment. See Platforms below. |
| **Docker** | Docker Engine recommended. Docker Desktop is untested. |
| **Docker Compose** | v2.20 or newer, the `docker compose` plugin rather than the old `docker-compose` script |

## Network shaping

Lab 3 adds delay and packet loss to a robot's link so you can see how each RMW copes
with bad Wi-Fi. It uses Linux `tc`/NetEm from your kernel. `sch_netem` alone is enough
to run it, just egress-only; `sch_htb`, `ifb` and `act_mirred` add shaping on the
return path too. If your kernel has none of them, that part of Lab 3 is skipped. A
recorded capture may be provided. Everything else in the lab still runs.

Missing modules may simply not be loaded yet. See Fixes.

## Platforms

The workshop needs a Linux environment with Docker Engine. Native Linux, WSL2 and a
VM all count. Run the script inside whichever one you will use on the day, not on the
host around it.

Prefer a normal desktop or server install. Minimal, cloud and container images strip
out `linux-modules-extra`, which is where the network degradation modules live.

| Your setup | The workshop | Network shaping |
|---|---|---|
| Linux on amd64 | Recommended | Yes |
| Windows with WSL2 | Works | Yes on a current kernel. Older ones lack it, so run `wsl --update`. |
| Linux VM on an amd64 host | Works | Yes |
| Linux on arm64 | Untested | Depends on your kernel. Run the check. |
| NVIDIA Jetson (L4T) | Works | No, the stock L4T kernel ships without the modules. |
| Any Mac | Untested | Untested. Run the script and tell us what you get. |
| Docker Desktop, any OS | Not recommended | Untested |

## Fixes

Modules present but not loaded, which is the usual case (`-a` matters here: plain
`modprobe sch_netem sch_htb ifb act_mirred` treats the last three names as
parameters for `sch_netem` and only loads that one):

```bash
sudo modprobe -a sch_netem sch_htb ifb act_mirred
```

Modules absent, common on minimal and cloud images:

```bash
sudo apt install linux-modules-extra-$(uname -r)
```

Windows, in PowerShell, then reopen your Linux terminal:

```powershell
wsl --update
wsl --shutdown
```

macOS: run the script and put the result in the form.

To confirm that NetEm works inside a container:

```bash
docker run --rm --cap-add NET_ADMIN alpine sh -c '
  apk add -q iproute2 || { echo "no network from inside containers"; exit 2; }
  tc qdisc add dev lo root netem delay 1ms || { echo "no netem"; exit 3; }
  echo "netem works"'
```

Alpine is not a workshop image, just a 4 MB base to run `tc` in. The command installs
`iproute2` inside it, so it fails at the first line if the container cannot reach the
network. Fix that first, because pulling the workshop images needs the same connection.

## If your computer cannot run it

See whether you can bring a different computer, or borrow one from a colleague.

If that is not possible, say so in the form.

---

# Workshop materials

Instructions and content land in this repository on **Tuesday 15 September 2026**.

Clone the repository and pull the Docker images before you travel. The images are
several GB, and conference Wi-Fi will not cope with a room full of people pulling
them at once.

# Questions

Let us know in the form, or feel free to open an issue.
