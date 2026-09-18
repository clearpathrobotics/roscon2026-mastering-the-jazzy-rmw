# 1. Take a capture (but fall short)

A capture can be full of ROS 2 traffic and still not tell you which stream is which.
This exercise makes that happen, then walks through how to fix it without restarting
the fleet.

This exercise runs on Fast DDS, with the fleet and the rotating capture already up
from [Setup](../README.md).

## Steps

1. Confirm the flat fleet is up and check its current shaping state:

   ```bash
   scripts/workshop -t flat netem
   ```

   If you skipped setup:
   ```
   scripts/workshop -t flat up 3 fast
   scripts/workshop webshark up
   scripts/workshop observer capture start 3 --files 12
   ```
   Wait until three files have appeared before going on.

   If Webshark is not capturing:
   ```
   chmod 777 lab2-on-the-wire/captures/
   ```

2. Open <http://localhost:8085/webshark/> and click the file at the top of the list.
   That is the newest window, as Webshark sorts newest on top.

3. Click **SEDP**. Read the count beside the filter box.
   It reads `0 of N displayed`, in red. The window holds tens of thousands of valid RTPS
   packets and not one of them names a topic.

4. Click **SPDP**. That one is not empty. Whatever went wrong took endpoint discovery
   and left participant discovery alone.

> [!TIP]
> The next step needs the first window of the run to still exist. The ring holds
> `--files N` files of 30 seconds each and deletes the rest, so Setup's `--files 12`
> keeps six minutes of history where the default of 6 would keep three. Once the first
> window is gone, step 7 is the only way back.

5. Scroll to the *bottom* of the file list and open the oldest window. Click **SEDP**
   again. The handshake is in there.

6. Now get the Endpoint Discovery back into the current window without restarting anything:

   ```bash
   scripts/workshop observer capture bounce
   ```

   It prints the file the burst landed in. Open **that** file, click **Refresh**, then
   **SEDP**. Do not just take the top row: the ring may have rotated while the bounce ran,
   which would leave the burst one row down.

Question: Why can't you always just see the SEDP in the newest file?
<details style="border: 2px solid #333; padding: 5px">
<summary>Answer: why the newest file is the wrong one</summary>

An RTPS packet carries the writer's GUID, not the topic name. Names cross the wire in the
endpoint discovery handshake (SEDP), which fires when a publisher and a subscriber first
match. After that the fleet stops mentioning them.

Participant discovery (SPDP) is periodic and keeps announcing for as long as the fleet
runs, which is why step 4 is not empty. Only endpoint discovery goes quiet.

So any steady-state window is anonymous, and newest-first sorting hands you a steady-state
window every time. Webshark's default sort order leads you to the wrong file.

For example, measured on a three-robot Fast DDS fleet, two separate runs, consecutive
30-second windows:

| window | SEDP | SPDP |
|---|---:|---:|
| 1, capture start | 1456 / 1896 | 1034 / 1173 |
| 2, steady state | **0** / **0** | 906 / 907 |

Your own counts will differ, but the shape holds every time. Endpoint discovery is spent in
the first window and reads zero in every window after it, while participant discovery
carries on. Anything you do in the meantime that joins the graph, a `ros2 topic info`
included, puts a fresh burst into whichever window is being recorded at the time.

`scripts/workshop observer capture bounce` joins a throwaway subscriber. Every robot sees a new endpoint and
re-announces, putting a fresh handshake in the window that is open right now.

The same shape holds on Zenoh, which you will see in
[exercise 3](3_how_the_capture_lies.md): a few hundred `Declare` frames in the first
window and zero in the second, so the blind spot survives the change of protocol.
</details>

## Troubleshooting

**The file list is empty.** `scripts/workshop observer capture start` writes into `captures/`, which the viewer
mounts. Check that new `live_<rmw>_*.pcap` files appear under
`lab2-on-the-wire/captures/`, or that the webshark file list populates.

**SPDP is empty too.** That is not this exercise's failure. The capture is not seeing the
fleet's traffic at all, so check the observer container is up.

**The title bar says `undefined frames` while you are reading.** The window you had open
rotated out of the ring. Go back to the file list and take the new top entry.

**The fleet will not start.** If the robots exit immediately with
`file not found: 'xacro'`, your local image predates the one the lab needs, and
`pull_policy: missing` means compose will keep using it rather than fetching a newer one.
Rebuild it, then recreate the fleet, because a rebuild retags the image without touching
containers that already exist:

```bash
docker compose -f docker/compose/flat.yml --profile mock build observer
scripts/workshop -t flat down && scripts/workshop -t flat up 3 fast && scripts/workshop webshark up
```

**The fleet is dead but the viewer is up.** Copy the recorded captures into the directory
this viewer is serving, which is the fleet's own, not the one under `docker/webshark`:

```bash
cp docker/webshark/fixtures/*.pcap.gz lab2-on-the-wire/captures/
```

Then open `healthy-cyclone-discovery`.

**Nothing is running and the fleet will not start.** Start the standalone viewer on its
own. It serves `docker/webshark/captures` and needs no fleet:

```bash
mkdir -p docker/webshark/captures                  # first run only, see docker/webshark/webshark.yml for why
cp docker/webshark/fixtures/*.pcap.gz docker/webshark/captures/
docker compose -f docker/webshark/webshark.yml up -d
```

Either way you get the second half of the exercise, what a healthy handshake looks like.
The first half needs a live fleet, because the mistake cannot be made once the file exists.

Leave everything running. [Exercise 2](2_the_cli_cannot_answer.md) uses the same fleet.
