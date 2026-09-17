#!/usr/bin/env python3
"""Validate observable tc state against the shared Lab 2 profile catalogue.

iproute2 JSON uses seconds, fractional probabilities and bytes/second, not
human-readable ms/%/mbit strings. See tc/q_netem.c and tc/m_mirred.c upstream.
The kernel does not expose the delay distribution table through tc JSON;
application logs retain that requested setting, without claiming to verify it.
"""
from __future__ import annotations
import json
import math
from pathlib import Path
import re
import sys

CATALOGUE = Path(__file__).resolve().parents[2] / 'lab2-on-the-wire/scripts/netem_profile.sh'


def objects(raw):
    value = json.loads(raw)
    if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
        raise ValueError('expected an array of objects')
    return value


def close(actual, expected):
    return type(actual) in (int, float) and math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-4, abs_tol=1e-6)


def nodes(value):
    if isinstance(value, dict):
        yield value
        for v in value.values(): yield from nodes(v)
    elif isinstance(value, list):
        for v in value: yield from nodes(v)


def profile_values(profile):
    match = re.search(r'\[' + re.escape(profile) + r'\]="delay (\d+)ms (\d+)ms distribution paretonormal loss gemodel ([\d.]+)%"', CATALOGUE.read_text())
    if not match: raise ValueError('unsupported profile')
    delay, jitter, loss = map(float, match.groups())
    return delay / 1000, jitter / 1000, loss / 100


def check_netem(qdiscs, profile, rate, prefix):
    errors = []
    roots = [q for q in qdiscs if q.get('root') is True]
    if len(roots) != 1 or roots[0].get('kind') != 'netem':
        return [prefix + '_netem_missing']
    options = roots[0].get('options', {})
    delay, jitter, loss = profile_values(profile)
    observed_delay = options.get('delay', {})
    if not isinstance(observed_delay, dict): observed_delay = {}
    if not close(observed_delay.get('delay'), delay) or not close(observed_delay.get('jitter'), jitter):
        errors.append(prefix + '_delay_mismatch')
    ge = options.get('loss-gemodel', {})
    if not isinstance(ge, dict): ge = {}
    if not all(close(ge.get(k), v) for k, v in {'p': loss, 'r': 1-loss, '1-h': 1, '1-k': 0}.items()):
        errors.append(prefix + '_loss_mismatch')
    wanted_rate = float(rate.removesuffix('mbit')) * 1e6 / 8 if rate else 0
    observed_rate = options.get('rate', {})
    if isinstance(observed_rate, dict): observed_rate = observed_rate.get('rate', 0)
    if not close(observed_rate, wanted_rate): errors.append(prefix + '_rate_mismatch')
    for field in ('loss-random', 'loss-state', 'duplicate', 'reorder', 'corrupt', 'slot'):
        if options.get(field): errors.append(prefix + '_unexpected_' + field)
    return errors


def validate(qdisc_raw, ingress_raw, links_raw, all_qdisc_raw, profile, rate):
    try:
        qdisc, ingress, links, all_qdisc = map(objects, (qdisc_raw, ingress_raw, links_raw, all_qdisc_raw))
        # All-link and all-qdisc queries distinguish absent IFB from query failure.
        if not any(x.get('ifname') == 'eth0' for x in links):
            return False, ['eth0_state_unavailable']
        ifb = [x for x in links if x.get('ifname') == 'ifb0']
        ifb_qdisc = [q for q in all_qdisc if q.get('dev') == 'ifb0']
        errors = []
        if profile == 'none':
            if not qdisc: errors.append('egress_state_unavailable')
            if any(q.get('kind') not in ('noqueue', 'fq_codel', 'pfifo_fast', 'mq') for q in qdisc):
                errors.append('residual_shaping')
            if ingress or ifb or ifb_qdisc: errors.append('residual_ingress_or_ifb')
        else:
            errors += check_netem(qdisc, profile, rate, 'egress')
            if not any(n.get('kind') == 'mirred' and n.get('mirred_action') == 'redirect' and n.get('direction') == 'egress' and n.get('to_dev') == 'ifb0' for n in nodes(ingress)):
                errors.append('ingress_redirect_missing')
            if not ifb or 'UP' not in ifb[0].get('flags', []): errors.append('ifb_missing_or_down')
            errors += check_netem(ifb_qdisc, profile, rate, 'ifb')
        return not errors, errors
    except (ValueError, TypeError, KeyError, AttributeError):
        return False, ['state_unavailable_or_unsupported']


def main(argv):
    if len(argv) != 6: return 2
    valid, reasons = validate(*argv)
    print(json.dumps({'valid': valid, 'reasons': reasons, 'limitations': ['delay_distribution_not_observable_in_tc_json']}))
    return 0 if valid else 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
