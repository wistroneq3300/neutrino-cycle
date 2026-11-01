#!/usr/bin/env python3
"""Rebuild the DMESG_BUNDLE family table from a campaign directory.

Usage:
    ./extract.py /path/to/campaign

Reads <campaign>/<node>/loop*/report.json and the matching dmesg_clear.txt.
Writes families.md next to this script. Raw dmesg text is customer data and is
not printed; only normalised message families and their counts are.
"""
import collections
import glob
import json
import os
import re
import sys

NODE_RE = re.compile(r'(.+)/loop\d+$')
BDF_RE = re.compile(r'\b[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]\b')


def normalise(text):
    """Collapse values that differ between occurrences of the same message."""
    text = BDF_RE.sub('<BDF>', text)
    text = re.sub(r'\[\d+\]', '[<PID>]', text)
    text = re.sub(r'pid \d+', 'pid <N>', text)
    text = re.sub(r'i2c-IPI0001:\d+', 'i2c-IPI0001:<N>', text)
    text = re.sub(r'dmi-ipmi-ssif\.\d+', 'dmi-ipmi-ssif.<N>', text)
    return re.sub(r'\b\d+\b', '<N>', text)[:105]


def first_timestamp(campaign, probe, sample_node='Neutrino13_n2', sample_loop='loop0010'):
    """Kernel timestamp of the first sample occurrence, used as boot-phase evidence."""
    key = probe.split('<')[0][:45]
    path = os.path.join(campaign, sample_node, sample_loop, 'dmesg_clear.txt')
    try:
        with open(path, errors='replace') as handle:
            for line in handle:
                if key in line:
                    match = re.match(r'\[\s*([\d.]+)\]', line)
                    if match:
                        return float(match.group(1))
    except OSError:
        pass
    return None


def collect(campaign):
    loops = collections.Counter()
    families = {}
    for path in sorted(glob.glob(os.path.join(campaign, '*', 'loop*', 'report.json'))):
        match = NODE_RE.search(os.path.dirname(path))
        if not match:
            continue
        node = os.path.basename(match.group(1))
        with open(path) as handle:
            record = json.load(handle)
        loops[node] += 1
        for item in record.get('issues') or []:
            if item.get('code') != 'DMESG_BUNDLE':
                continue
            for entry in item.get('entries') or []:
                text = (entry.get('text') or '')[:220]
                key = normalise(text)
                if key not in families:
                    families[key] = [text, collections.Counter()]
                families[key][1][node] += int(entry.get('count', 1) or 1)
    return loops, families


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    campaign = sys.argv[1]
    loops, families = collect(campaign)
    nodes = sorted(loops)
    lines = ['# DMESG_BUNDLE families', '',
             'Loops: ' + ', '.join(f'{n}={loops[n]}' for n in nodes), '',
             'Rate = occurrences per loop. 1.00x means once per boot.', '',
             '| # | Family | ' + ' | '.join(nodes) + ' | 1st stamp |',
             '|---|---|' + '---|' * len(nodes) + '---|']
    ordered = sorted(families.items(), key=lambda kv: -sum(kv[1][1].values()))
    for index, (key, (probe, per_node)) in enumerate(ordered, 1):
        cells = [f'{per_node[n] / loops[n]:.2f}x' if per_node.get(n) else '-' for n in nodes]
        stamp = first_timestamp(campaign, probe)
        lines.append(f'| {index} | `{key}` | ' + ' | '.join(cells)
                     + f' | {f"[{stamp:.2f}s]" if stamp else "-"} |')
    target = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'families.md')
    with open(target, 'w') as handle:
        handle.write('\n'.join(lines) + '\n')
    print(f'wrote {target} ({len(ordered)} families over {sum(loops.values())} loops)')


if __name__ == '__main__':
    main()
