#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"

die() {
    echo "$SCRIPT_NAME: $*" >&2
    exit 2
}

[[ $# -eq 3 ]] || die "usage: $SCRIPT_NAME <output-dir> <total-robots> <pinned-robots>"

OUTPUT_DIR="$1"
TOTAL_ROBOTS="$2"
PINNED_ROBOTS="$3"

[[ "$TOTAL_ROBOTS" =~ ^[1-9][0-9]*$ ]] || die "total robot count must be a positive integer"
[[ "$PINNED_ROBOTS" =~ ^[1-9][0-9]*$ ]] || die "pinned robot count must be a positive integer"
(( PINNED_ROBOTS <= TOTAL_ROBOTS )) || die "pinned robot count cannot exceed total robot count"

write_cyclone() {
    local file="$1" allow_multicast="$2" iface="$3" peers="$4"
    {
        echo '<CycloneDDS>'
        echo '  <Domain id="any">'
        echo '    <General>'
        echo "      <AllowMulticast>$allow_multicast</AllowMulticast>"
        if [[ "$iface" == "auto" ]]; then
            echo '      <Interfaces>'
            echo '        <NetworkInterface autodetermine="true"/>'
            echo '      </Interfaces>'
        elif [[ -n "$iface" ]]; then
            echo '      <Interfaces>'
            local ip
            IFS=',' read -ra ifaces <<< "$iface"
            for ip in "${ifaces[@]}"; do
                echo "        <NetworkInterface address=\"$ip\"/>"
            done
            echo '      </Interfaces>'
        fi
        echo '    </General>'
        echo '    <Discovery>'
        echo '      <ParticipantIndex>auto</ParticipantIndex>'
        echo '      <MaxAutoParticipantIndex>120</MaxAutoParticipantIndex>'
        if [[ -n "$peers" ]]; then
            echo '      <Peers>'
            printf '%s\n' "$peers"
            echo '      </Peers>'
        fi
        echo '    </Discovery>'
        echo '  </Domain>'
        echo '</CycloneDDS>'
    } > "$file"
}

mkdir -p "$OUTPUT_DIR"

observer_peers='        <Peer address="localhost"/>'
for robot in $(seq 1 "$PINNED_ROBOTS"); do
    observer_peers+=$'\n        <Peer address="mock-robot-'
    observer_peers+="$robot"$'"/>'
done
write_cyclone "$OUTPUT_DIR/observer.xml" false "" "$observer_peers"

for robot in $(seq 1 "$TOTAL_ROBOTS"); do
    if (( robot <= PINNED_ROBOTS )); then
        peers='        <Peer address="localhost"/>'$'\n''        <Peer address="observer"/>'
        write_cyclone "$OUTPUT_DIR/mock-robot-$robot.xml" false "" "$peers"
    else
        write_cyclone "$OUTPUT_DIR/mock-robot-$robot.xml" true "" ""
    fi
done

printf 'Exercise 1 Cyclone fixture generated: %s pinned + %s default robots; total %s\n' \
    "$PINNED_ROBOTS" "$((TOTAL_ROBOTS - PINNED_ROBOTS))" "$TOTAL_ROBOTS"
