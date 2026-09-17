# Recorded failure captures

Ten captures of ROS 2 going wrong and four of it going right, recorded on the mock fleet. Open
them in Webshark and work through the symptom sections of the [guide](../guide.html). You need no
robot and no network.

The viewer lists one directory, so copy them in first:

```bash
cd docker/webshark
mkdir -p captures                  # first run only, see webshark.yml for why
cp fixtures/*.pcap.gz captures/
docker compose -f webshark.yml up -d
```

Then open <http://localhost:8085/webshark/> and pick one.

## What each capture shows

| Capture | Open it and | Guide |
|---|---|---|
| `qos-mismatch` | filter `rtps.param.topicName contains "fixture_qos"`. Both endpoints announce the topic, one BEST_EFFORT and one RELIABLE. They never match, and neither side is told. | 5.7 |
| `domain-mismatch` | filter `udp.dstport == 17900 \|\| udp.dstport == 26650`. Two participants announcing on domains 42 and 77, 60 frames, nothing crossing. Add `rtps.sm.id == 0x06` and it goes to zero: neither side matched anyone to acknowledge. Keep the port scope, since the healthy fleet on the same wire contributes 993 ACKNACKs. | 5.2 |
| `multicast-storm` | click **SPDP** for 1604, then filter `ip.dst == 239.255.0.1` for all 3293. Every frame in the file is discovery, from 18 participant GUID prefixes. | 5.4 |
| `nothing-on-wire` | filter `rtps.param.topicName contains "fixture_localhost"` and get nothing, on a bus carrying 24991 RTPS frames. The publisher was healthy the whole time. | 5.1 |
| `multicast-blocked` | filter `ip.dst == 239.255.0.1`. Of the 162 frames, 89 are the observer's and 73 are the first robot's. The second robot is configured identically and appears zero times. | 5.3 |
| `node-death` | click **SPDP** and read down the Time column, which is already capture order. One robot stops announcing at 17.5 s, another at 38.0 s, a third runs to 67.5 s. No departure notice from either. | 5.2 |
| `fragment-loss` | turn on **Reassembly**, then filter `rtps.sm.id == 0x16`. 1505 fragment submessages and 10944 IP fragments that never reassemble. | 5.9, 5.13 |
| `reliable-vs-besteffort` | filter `rtps.param.topicName contains "fixture_img"`. The same camera frames on two topics under one impairment, differing only in reliability. | 5.8 |
| `zenoh-no-router` | filter `tcp.port == 7999`. Fifteen frames: eight connection attempts, seven refused, and no Zenoh at all, so the failure is below the protocol. Keep the port scope, since the fleet on the same wire puts 15581 Zenoh frames on port 7447. | 5.10 |
| `zenoh-router-killed` | filter `zenoh.body.close.reason`. The router dies, sessions close, 27 reconnect attempts follow, then three handshakes complete. | 5.10 |

Counts come from `manifest.tsv`, which is generated rather than hand-tallied.

## The healthy ones

Every broken shape above is only legible against a working one, so four baselines ship
alongside. Open the matching pair when a symptom section quotes both.

| Capture | What it is |
|---|---|
| `healthy-fastdds` | A Fast DDS fleet discovering and running, 5928 frames, nothing wrong |
| `healthy-cyclone` | A short Cyclone capture that opens in a couple of seconds, for a first look |
| `healthy-cyclone-discovery` | Cyclone endpoint discovery, the reference for what SEDP should look like |
| `healthy-zenoh` | A Zenoh session declaring its key expressions normally |

## How they were made

`../record-fixtures.sh`, against the mock fleet from `scripts/workshop`. It records, cuts each capture to
the window that shows the symptom, gzips, and writes the manifest:

```bash
scripts/workshop -t flat up 3 cyclone
scripts/workshop webshark up
./record-fixtures.sh record all
./record-fixtures.sh trim all
./record-fixtures.sh manifest
./record-fixtures.sh verify     # re-derives every manifest number from the committed files
```

The Zenoh pair needs `scripts/workshop -t flat up 3 zenoh` (then `scripts/workshop webshark up`) instead, and the script refuses to record a fixture
against the wrong middleware rather than mislabelling the file.

Trimming is directed by each fixture's own filter: the script finds where the symptom is, cuts
around it, then re-runs the filter on the result and fails if the evidence went missing. Picking
a frame range by eye does not work here. On the capture this library replaces, endpoint discovery
sat at frames 40260 to 45051 of fifty thousand, so a cut of the first four thousand frames
produced a file with no discovery in it at all, named for discovery.

## Provenance

Synthetic traffic from the mock robots in `docker/compose/flat.yml`. No real
robot, no customer data, nothing to redact. Impairments come from
`lab2-on-the-wire/scripts/netem_profile.sh`, and the manifest header records whether netem
shaped both directions or egress only, which depends on the `ifb` module being loaded on the
recording host.

Payload bytes are on the wire but not decodable. Wireshark can only interpret a serialized ROS 2
message if discovery carried a TypeObject for the type, and ROS 2 does not send one by default,
so these captures tell you who spoke and about what topic rather than what was in the message.
Guide 5.13 covers why.
