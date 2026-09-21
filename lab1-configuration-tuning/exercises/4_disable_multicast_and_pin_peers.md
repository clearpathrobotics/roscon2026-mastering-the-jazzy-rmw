# 4. Disable multicast and pin peers

Domains isolate the fleet but leave discovery flooding every domain (Exercise 3). Here you
take the opposite lever: keep **one** domain, turn **multicast off**, and hand Cyclone DDS an
explicit list of **peers** so each robot only ever discovers the **observer** and never the
other robots. You author the config yourself and feed it to the harness with
`--rmw-directory`.

Uses **Cyclone DDS** on the flat topology. Start from the repository root.

> **What you will visualize:** a single-domain fleet where the observer still sees every
> robot, but each robot's graph contains only itself and the observer. Discovery is driven by
> unicast peer lists instead of a multicast free-for-all.

## How the config controls discovery

Two Cyclone settings do the work:

- `<AllowMulticast>false</AllowMulticast>`: stop announcing/listening over multicast, so a
  participant no longer hears every other participant on the segment automatically.
- `<Peers>`: with multicast off, a participant only runs discovery against the **unicast
  addresses you list**. List a peer and the two exchange discovery, but omit it and they never do.

So a **hub-and-spoke** graph falls out of *who lists whom*: the observer lists every robot,
each robot lists only the observer. Robots share the bus but, listing no other robot, never
exchange discovery with each other. Peers can be container **hostnames**, Docker's embedded
DNS resolves `observer` and `mock-robot-N` on `flat-net`, so you don't have to chase the
dynamic IPs.

## Steps

1. Create the config directory for this lab and its Cyclone subdirectory:

   ```bash
   mkdir -p docker/rmw_configuration/lab1/cyclone
   ```

2. Create the **observer** profile at `docker/rmw_configuration/lab1/cyclone/observer.xml`.
   It peers with all three robots, so it discovers the whole fleet:

   ```xml
   <CycloneDDS>
     <Domain id="any">
       <General>
         <!-- Hub. Multicast off; discover only the explicitly listed peers. -->
         <AllowMulticast>false</AllowMulticast>
       </General>
       <Discovery>
         <ParticipantIndex>auto</ParticipantIndex>
         <MaxAutoParticipantIndex>120</MaxAutoParticipantIndex>
         <Peers>
           <Peer address="localhost"/>       <!-- same-host participants (ros2 CLI) -->
           <Peer address="mock-robot-1"/>
           <Peer address="mock-robot-2"/>
           <Peer address="mock-robot-3"/>
         </Peers>
       </Discovery>
     </Domain>
   </CycloneDDS>
   ```

3. Create the **three robot** profiles — `mock-robot-1.xml`, `mock-robot-2.xml`, and
   `mock-robot-3.xml` in the same directory. Each is **identical** and peers with **only the
   observer**, so no robot lists another robot:

   ```xml
   <CycloneDDS>
     <Domain id="any">
       <General>
         <!-- Spoke. Multicast off; peer with the observer only, so this robot
              never exchanges discovery with the other robots. -->
         <AllowMulticast>false</AllowMulticast>
       </General>
       <Discovery>
         <ParticipantIndex>auto</ParticipantIndex>
         <MaxAutoParticipantIndex>120</MaxAutoParticipantIndex>
         <Peers>
           <Peer address="localhost"/>   <!-- same-host participants (ros2 CLI) -->
           <Peer address="observer"/>
         </Peers>
       </Discovery>
     </Domain>
   </CycloneDDS>
   ```

   You should now have four files:

   ```bash
   ls docker/rmw_configuration/lab1/cyclone
   # mock-robot-1.xml  mock-robot-2.xml  mock-robot-3.xml  observer.xml
   ```

4. Bring the fleet up on the flat bus with your directory instead of the generated config.
   `--rmw-directory` copies your files in for the selected RMW (flat + Cyclone):

   ```bash
   MOCK_RUN_PILOT=false scripts/workshop -t flat up 3 cyclone \
     --model a300,j100,r100 \
     --rmw-directory docker/rmw_configuration/lab1/cyclone
   ```

   All three robots stay on the **same** domain (the default `25`) — the isolation now comes
   from the peer lists, not from separate domains.

5. Confirm the hub-and-spoke split. From a **robot**, you now see only yourself and the
   observer — the other robots are gone:

   ```bash
   scripts/workshop shell mock-robot-1
   ros2 node list --no-daemon --spin-time 5      # only robot_1's nodes (+ observer), not robot_2 / robot_3
   exit
   ```

6. From the **observer**, you still see the whole fleet, because the observer peers with every
   robot:

   ```bash
   scripts/workshop shell observer
   ros2 node list --no-daemon --spin-time 5  # robot_1, robot_2, and robot_3
   exit
   ```

<details>
<summary>Answer: domains vs. peer lists</summary>

Exercise 3 isolated robots by putting each on its **own domain**, separate DDS partitions
that never discover each other, but each still floods its own domain with multicast discovery.
Here you keep every robot on **one** domain and instead switch multicast off and pin explicit
**peers**. Discovery only flows along the links you name, so you get a deliberate
hub-and-spoke graph. Every robot is reachable from the observer, but no robot is reachable from another,
there is no multicast burst at all. Same isolation goal, two very different levers: one at the
domain boundary, one at the discovery-transport layer.

</details>

## Move on to the next exercise

Bring the fleet down before continuing:

```bash
scripts/workshop -t flat down
```

**Next:** [5. Configure the RMW for the star](5_configure_the_rmw_for_the_star.md)
