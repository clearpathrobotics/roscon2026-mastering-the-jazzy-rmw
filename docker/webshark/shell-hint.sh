#!/bin/bash
# Printed on `docker exec -it webshark bash`.
#
# A shell lands in the Node API directory, which has upstream's sample `captures/` next to
# it. The obvious reading is that captures go there and that tshark will record here, and
# both are wrong: the mount is /captures, and recording depends on which compose file
# started the container.

# dumpcap carries cap_net_admin,cap_net_raw=eip. execve() returns EPERM when a file grants
# permitted capabilities outside the bounding set with the effective bit set, so a missing
# CAP_NET_ADMIN fails the exec no matter what CAP_NET_RAW says. That is the difference
# between webshark.yml and webshark.robot.yml, and it surfaces as the unhelpful
# "Couldn't run dumpcap in child process: Operation not permitted".
capbnd=$(awk '/^CapBnd:/ { print $2 }' /proc/self/status)
if (( 0x${capbnd:-0} >> 12 & 1 )); then
    can_capture=yes
else
    can_capture=no
fi

printf '\n  webshark container\n'
printf '  Captures are read from and written to /captures (not ./captures beside the app,\n'
printf '  which is upstream sample data).\n\n'

# Compose auto-creates a missing bind mount as root, and this container is UID 1000, so a
# recording lands on "Permission denied" long after the capability question is settled.
# Reading the mount still works, so say which half is broken rather than just "not writable".
if [ ! -w /captures ]; then
    printf '  /captures is not writable by this container (uid %s). Reading works, recording\n' "$(id -u)"
    printf '  does not. The host directory behind the mount is owned by another user, which is\n'
    printf '  what compose does when it has to create it. On the host:\n\n'
    # shellcheck disable=SC2016  # printed for the reader to run on the host, not expanded here
    printf '    sudo chown -R $(id -u):$(id -g) <the directory bound to /captures>\n\n'
fi

if [[ $can_capture == yes ]]; then
    printf '  Capture here: yes. Pick the interface by address, then write into the mount:\n\n'
    printf '    ip -o -4 addr show\n'
    printf '    tshark -i <iface> -s 0 -a duration:60 -w /captures/mine.pcap\n\n'
    printf '  Start the capture before the ROS stack, or the discovery window is gone.\n\n'
else
    printf '  Capture here: no. This container was started without CAP_NET_ADMIN, so dumpcap\n'
    printf '  cannot exec and every tshark -i fails with "Operation not permitted".\n\n'
    printf '  This is the viewer configuration. To record, either capture on the machine\n'
    printf '  carrying the traffic and drop the file into /captures, or bring this container\n'
    printf '  up with the robot compose file instead:\n\n'
    printf '    docker compose -f webshark.robot.yml up -d\n\n'
fi
