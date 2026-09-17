# 4. Puzzles

Ten recorded captures of ROS 2 going wrong, none of which need a running fleet. Each one is
a symptom you could be handed in the field, and the question is always the same: what
broke, and what on the wire proves it.

They run easiest to hardest. Get through what you can here and finish the rest at home.

```bash
mkdir -p docker/webshark/captures                  # first run only, see docker/webshark/webshark.yml for why
cp docker/webshark/fixtures/*.pcap.gz docker/webshark/captures/
docker compose -f docker/webshark/webshark.yml up -d
```

Open <http://localhost:8085/webshark/> and pick a capture from the list. Section numbers
point at [the guide](../../docker/webshark/guide.html), which has the long version of each
answer.

On a large capture the count beside the filter box keeps showing the previous filter's
result for a second or two. Wait for the filter text and the count to settle together
before you read a number.

---

## 1. `multicast-storm`

The fleet is idle and nobody is publishing. The link is saturated anyway.

Click **SPDP**, and note both numbers in `N of M displayed`. Then clear the filter and type:

```
ip.dst == 239.255.0.1
```

<details style="border: 2px solid #333; padding: 5px">
<summary>Answer</summary>

SPDP alone matches 1604, which looks like half the capture until you filter on the
discovery multicast group and get 3293, the whole file. Every frame in it is addressed to
`239.255.0.1` and there is no user data anywhere.

That is 3293 frames in 29.1 seconds, about 113 a second, carrying 18 distinct participant
GUID prefixes from one host.

Discovery traffic scales with the square of the participant count, so a fleet that works
at three robots can drown itself at eighteen without a single application message being
sent. Guide 5.4.
</details>

## 2. `node-death`

Three robots start together, and by the end of the capture the fleet is one robot. Nothing
logged an error.

Click **SPDP** and read down the Time column. Packets are listed in capture order, so that
is already time order.

<details style="border: 2px solid #333; padding: 5px">
<summary>Answer</summary>

One robot stops announcing at 17.5 s, the second at 38.0 s, the third runs to 67.5 s.
Neither of the first two sent a departure notice.

A participant that dies without unregistering just stops appearing. Its peers keep the
endpoint until a liveliness lease expires, so for that window the graph says the robot is
present and no data is coming. Guide 5.2.
</details>

## 3. `nothing-on-wire`

A publisher is running and healthy. Its subscriber, on another machine, receives nothing.

Filter `rtps.param.topicName contains "fixture_localhost"`.

<details style="border: 2px solid #333; padding: 5px">
<summary>Answer</summary>

Nothing matches, on a capture carrying 24991 RTPS frames. The bus is busy and this topic
is not on it.

The publisher was working the whole time. It was bound to an interface that does not reach
the subscriber, so the messages were real and never left the host. An empty filter on a
busy capture is the signature. Guide 5.1.
</details>

## 4. `multicast-blocked`

Two robots, configured identically. One is discovered, one is not.

Filter `ip.dst == 239.255.0.1`, then narrow it to each sender in turn:

```
ip.dst == 239.255.0.1 && ip.src == 172.30.10.20
ip.dst == 239.255.0.1 && ip.src == 172.30.10.11
ip.dst == 239.255.0.1 && ip.src == 172.30.10.12
```

<details style="border: 2px solid #333; padding: 5px">
<summary>Answer</summary>

The group carries 162 frames, but only two senders produce them: 89 from the observer
at `.20` and 73 from robot 1 at `.11`. Robot 2 at `.12` matches **zero**, despite identical
configuration.

Its announcements never reached the group, so nothing it publishes can be discovered.
Switches, bridges and VPNs drop multicast far more often than they drop unicast, which is
why this failure follows people into production. Guide 5.3.
</details>

## 5. `domain-mismatch`

Two participants, both healthy, both talking. Neither can see the other.

Filter `udp.dstport == 17900 || udp.dstport == 26650`.

<details style="border: 2px solid #333; padding: 5px">
<summary>Answer</summary>

Sixty frames, two participants announcing on domains 42 and 77, nothing crossing between
them. Add `rtps.sm.id == 0x06` and it goes to zero: neither side matched anyone, so
neither has anything to acknowledge.

The domain ID is baked into the UDP port number, so a mismatch is visible in the port
alone before you decode anything. Keep the port scope, because the healthy fleet sharing
this wire contributes 993 ACKNACKs that would otherwise mask it. Guide 5.2.
</details>

## 6. `qos-mismatch`

Publisher and subscriber both exist. Both name the same topic. No data flows and neither
side reports an error.

Filter `rtps.param.topicName contains "fixture_qos"`.

<details style="border: 2px solid #333; padding: 5px">
<summary>Answer</summary>

Both endpoints announce the topic. One is BEST_EFFORT and the other is RELIABLE, so they
never match, and DDS tells nobody.

A reliable subscriber will not accept a best-effort publisher, because the publisher
cannot promise what the subscriber requires. The reverse pairing is fine. This is the
failure that `ros2 topic info -v` can actually solve, and it is worth knowing which ones
the CLI covers. Guide 5.7.
</details>

## 7. `reliable-vs-besteffort`

One impairment, two camera topics, identical payload. One survives.

Filter `rtps.param.topicName contains "fixture_img"` to find both topics. That shows they
exist and nothing else, so ask what QoS they announced and what repair followed:

```
rtps.reliability_kind == 1
rtps.reliability_kind == 2
rtps.sm.id == 0x06
```

<details style="border: 2px solid #333; padding: 5px">
<summary>Answer</summary>

The topic filter matches 907 frames across both streams and cannot tell them apart. The
reliability field separates them, with 3 announcements at kind 1, BEST_EFFORT, against 32
at kind 2, RELIABLE. Same camera frames, same netem profile, one setting different.

The third filter shows what that setting buys. 176 ACKNACK submessages, which only the
reliable stream generates, are the repair that saves it while the best-effort one just
loses frames.

That recovery is not free, because the repair traffic competes with the original stream on
a link that is already dropping packets. It is why the choice is a real one on a
constrained network rather than an obvious win. Guide 5.8.
</details>

## 8. `fragment-loss`

Camera frames arrive at maybe 80% of the publish rate. The laser scan on the same link is
untouched.

Turn on **Reassembly** in the viewer, then click **Fragments**. That counts the RTPS side.
For the IP side, ask how many fragments never completed:

```
(ip.flags.mf == 1 || ip.frag_offset > 0) && !ip.reassembled.length
```

<details style="border: 2px solid #333; padding: 5px">
<summary>Answer</summary>

1505 `DATA_FRAG` submessages, and 10944 IP fragments that never reassemble into a complete
sample.

A 41 KB JPEG does not fit in one datagram, so it crosses as roughly 28 fragments and every
one of them has to arrive. Under best-effort, losing any single fragment discards the
whole frame. The `LaserScan` fits in one datagram, so the same loss rate barely touches
it, which is exactly the contrast you measured live in
[exercise 2](2_the_cli_cannot_answer.md). Guide 5.9 and 5.13.
</details>

## 9. `zenoh-no-router`

A Zenoh fleet comes up and nothing discovers anything. Every RTPS filter you know returns
zero, but so does every Zenoh filter.

Filter `tcp.port == 7999`.

<details style="border: 2px solid #333; padding: 5px">
<summary>Answer</summary>

Fifteen frames: eight connection attempts, seven refused, and no Zenoh protocol traffic at
all.

The failure is below the protocol. There is no router listening, so no session is ever
established and nothing reaches the point of speaking Zenoh. When the protocol filters are
empty, drop a layer rather than assuming the dissector is broken. Keep the port scope,
because the healthy fleet on this wire puts 15581 Zenoh frames on port 7447. Guide 5.10.
</details>

## 10. `zenoh-router-killed`

A working Zenoh fleet stops mid-run, then partly recovers.

Filter `zenoh.body.close.reason` to find the moment it dies. Then drop a layer and count
what the clients did about it:

```
tcp.flags.syn == 1 && tcp.flags.ack == 0
tcp.flags.reset == 1
zenoh.body.init_ack.zid
```

<details style="border: 2px solid #333; padding: 5px">
<summary>Answer</summary>

Three sessions close with a reason code, then 27 connection attempts go out and 25 are
refused outright. Three `init_ack` frames come back, so three handshakes complete.

Under the per-host topology each robot has its own router, so losing one takes out that
robot's path and leaves the rest running. That is the argument for `perhost` over a single
central router, and it is visible here as a partial rather than total outage. Guide 5.10.
</details>

---

## Notes

The counts in these answers come from `fixtures/manifest.tsv`, which is generated by
`docker/webshark/record-fixtures.sh` rather than tallied by hand. Run
`docker/webshark/record-fixtures.sh verify` to re-derive every one of them from the
committed files.

Payload bytes are on the wire but not decodable. Wireshark can only interpret a serialized
ROS 2 message if discovery carried a TypeObject for the type, and ROS 2 does not send one
by default. These captures tell you who spoke and about what topic, not what was in the
message. Guide 5.13 covers why.
