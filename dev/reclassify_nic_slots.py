"""Reclassify NIC slot issues in a finished campaign and re-render the HTML.

Ground truth (this cycle): a NIC holds its PCI slot but its MST DEVICE_TYPE
flipped from Vera to NA. The producer (before the fix) only compared counts
(21 < 22) and the reviewer labelled it DEVICE_MISSING, which reads as a
physically removed card even though lspci still enumerates the slot. This
script derives the true per-slot state from the retained ``mst status``
evidence and rewrites the issue to NIC_DEGRADED when the slot is degraded.

It never rewrites campaign.json; only the rendered HTML is refreshed.
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from vera_cycle.reporting.cycle_report import read_journal, render_html  # noqa: E402

NIC_SLOTS = [
    '0001:00:00.0', '0002:00:00.0', '0002:20:00.0', '0003:00:00.0',
    '0003:80:00.0', '0004:00:00.0', '0004:40:00.0', '0004:80:00.0',
    '0004:c0:00.0', '0005:00:00.0', '0006:00:00.0', '0009:00:00.0',
    '000a:00:00.0', '000a:20:00.0', '000b:00:00.0', '000b:80:00.0',
    '000c:00:00.0', '000c:40:00.0', '000c:80:00.0', '000c:c0:00.0',
    '000d:00:00.0', '000e:00:00.0',
]
BDF = re.compile(r'^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]$')


def mst_section(path: Path) -> str:
    text = path.read_text(encoding='utf-8', errors='replace')
    block = text.split('[Evidence] MST', 1)
    if len(block) < 2:
        return ''
    return block[1].split('[Evidence]', 1)[0]


def classify(mst: str) -> dict:
    """Map every expected slot to PRESENT / DEGRADED:<type> / MISSING."""
    rows = []
    for line in mst.splitlines():
        cells = line.split()
        bdf = next((c for c in cells if BDF.match(c)), None)
        if bdf and cells:
            rows.append((line, cells[0], bdf.lower()))
    states = {}
    for slot in NIC_SLOTS:
        hit = None
        for raw, dtype, bdf in rows:
            if bdf == slot.lower() and dtype == 'NA' and re.search(r'_pci_cr\d+$', raw):
                continue
            if bdf == slot.lower():
                hit = (dtype, raw)
                break
        if hit is None:
            states[slot] = ('MISSING', None)
        elif hit[0].lower().startswith('vera'):
            states[slot] = ('PRESENT', None)
        else:
            mstdev = next((c for c in hit[1].split() if c.startswith('/dev/mst/')), '')
            states[slot] = ('DEGRADED', (hit[0], mstdev, ' '.join(hit[1].split())))
    return states


def reclassify(root: Path) -> int:
    campaign = read_journal(root)
    changed = 0
    for node in campaign['nodes']:
        for record in node['loops']:
            nic = [i for i in record['issues']
                   if i.get('component') == 'NIC' and i.get('code') in {'DEVICE_MISSING', 'NIC_DEGRADED'}]
            if not nic:
                continue
            m = re.search(r'(\d+)\s*$', str(record.get('phase', '')))
            if not m:
                continue
            loops_dir = root / node['key'] / ('loop' + m.group(1).zfill(4))
            hw = next((p for p in (loops_dir / 'hardware.txt',) if p.is_file()), None)
            if hw is None:
                continue
            states = classify(mst_section(hw))
            degraded = sorted(s for s, v in states.items() if v[0] == 'DEGRADED')
            missing = sorted(s for s, v in states.items() if v[0] == 'MISSING')
            item = nic[0]
            if degraded and not missing:
                bdf = degraded[0]
                dtype, mstdev, mstrow = states[bdf][1]
                item['code'] = 'NIC_DEGRADED'
                item['detail'] = (f'root port {bdf} -> downstream Vera NIC (MST device {mstdev.split("/")[-1]}) '
                                  f"degraded: DEVICE_TYPE='{dtype}' (expected Vera); card present but not functional "
                                  f'(degraded slot {bdf}). mst status row: {mstrow}')
                item['snippet'] = f'NIC actual=21, expected 22; degraded slot {bdf} (device type {dtype})'
                changed += 1
            elif missing:
                bdf = missing[0]
                item['code'] = 'DEVICE_MISSING'
                item['detail'] = f'Expected at least 22; detected 21 (missing slot {bdf})'
                item['snippet'] = f'measured NIC actual=21, expected 22; missing slot {bdf}'
                changed += 1
    if not changed:
        print('no NIC slot issue needed reclassification')
        return 0
    console_path = root / 'console.log'
    console_log = console_path.read_text(encoding='utf-8', errors='replace') if console_path.is_file() else ''
    html = render_html(campaign, console_log)
    out = root / 'CYCLE_REVIEW_REPORT.html'
    out.write_text(html, encoding='utf-8')
    print(f'reclassified {changed} NIC issue(s); wrote {out} ({len(html)} bytes)')
    return changed


if __name__ == '__main__':
    raise SystemExit(0 if reclassify(Path(sys.argv[1]).resolve()) >= 0 else 1)
