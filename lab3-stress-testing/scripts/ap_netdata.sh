#!/usr/bin/env bash
# Export the routed AP's shared ifb0 qdisc counters to Netdata StatsD.
set -uo pipefail

IFB="${AP_IFB:-ifb0}"
INTERVAL="${AP_METRICS_INTERVAL:-1}"
STATSD_HOST="${NETDATA_STATSD_HOST:-}"

if [[ -z "$STATSD_HOST" ]]; then
    AP_ADDRESS="$(ip -o -4 addr show | awk '$4 ~ /^172\.40\..*\.2\// {print $4; exit}')"
    STATSD_HOST="${AP_ADDRESS%.*}.1"
fi

read_counters() {
    tc -s qdisc show dev "$IFB" 2>/dev/null | awk '
        /^ Sent/ && !seen_sent {
            sent_bytes=$2; dropped=$7; gsub(/,/, "", dropped); seen_sent=1
        }
        /^ backlog/ && !seen_backlog {
            backlog=$2; sub(/b$/, "", backlog); seen_backlog=1
        }
        END { printf "%s %s %s\n", sent_bytes+0, dropped+0, backlog+0 }'
}

previous_bytes=0
previous_drops=0
while sleep "$INTERVAL"; do
    read -r sent_bytes dropped backlog_bytes <<<"$(read_counters)"
    capacity_mbps=0 delay_ms=0 loss_pct=0
    [[ -r /run/ap_shape.env ]] && source /run/ap_shape.env
    if (( sent_bytes >= previous_bytes && previous_bytes > 0 )); then
        throughput_mbps="$(awk -v current="$sent_bytes" -v previous="$previous_bytes" -v seconds="$INTERVAL" \
            'BEGIN { printf "%.3f", (current - previous) * 8 / seconds / 1000000 }')"
        drops_per_sec="$(awk -v current="$dropped" -v previous="$previous_drops" -v seconds="$INTERVAL" \
            'BEGIN { printf "%.3f", (current - previous) / seconds }')"
        backlog_kib="$(awk -v bytes="$backlog_bytes" 'BEGIN { printf "%.3f", bytes / 1024 }')"
        # One metric per datagram: netdata's statsd listener only reads the
        # first line of whatever it receives in a single packet.
        printf 'lab3_ap.throughput_mbps:%s|g\n' "$throughput_mbps" >"/dev/udp/$STATSD_HOST/8125" || true
        printf 'lab3_ap.drops_per_sec:%s|g\n' "$drops_per_sec" >"/dev/udp/$STATSD_HOST/8125" || true
        printf 'lab3_ap.backlog_kib:%s|g\n' "$backlog_kib" >"/dev/udp/$STATSD_HOST/8125" || true
    fi
    printf 'lab3_ap.capacity_mbps:%s|g\n' "$capacity_mbps" >"/dev/udp/$STATSD_HOST/8125" || true
    printf 'lab3_ap.delay_ms:%s|g\n' "$delay_ms" >"/dev/udp/$STATSD_HOST/8125" || true
    printf 'lab3_ap.loss_pct:%s|g\n' "$loss_pct" >"/dev/udp/$STATSD_HOST/8125" || true
    previous_bytes="$sent_bytes"
    previous_drops="$dropped"
done
