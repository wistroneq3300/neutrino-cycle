"""Summary-first cycle report with linked detail files.

Reuses cycle_report.py unchanged for every helper; only render_html is
replaced. The main HTML keeps the overview (outcome + target results) and
links to detail pages written beside it, so the page opens instantly instead
of carrying hundreds of MB of inline tables.

Usage:
    python3 cycle_report_lite.py <campaign_dir>

It rewrites only Fullstress-style report artifacts it owns:
    CYCLE_REVIEW_LITE.html        (small summary)
    details/<slug>.html           (heavy detail pages)
Everything else in the campaign dir is left untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import vera_cycle.reporting.cycle_report as base
from vera_cycle.core.cycle_core import atomic_write, health, now
elapsed = base.elapsed

esc = base.esc
badge = base.badge
facts = base.facts
status = base.status
duration = base.duration
node_order = base.node_order
issue_cards = base.issue_cards_compact
record_html = base.record_html
_wistron_logo = base._wistron_logo


def _detail_page(title, run_id, body):
    css = (base.ASSETS / 'report.css').read_text(encoding='utf-8')
    logo = _wistron_logo()
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer"><title>{esc(title)} | {esc(run_id)}</title>
<style>{css}</style></head><body>
<div class="brandbar"><div class="brand-lockup">{logo}<span class="brand-caption">System validation</span></div><span>Engineering / Cycle review</span></div>
<header><p><a href="../CYCLE_REVIEW_LITE.html">&larr; Back to summary</a></p><h1>{esc(title)}</h1>
<div class="runline"><code>{esc(run_id)}</code></div></header>
<main id="main">{body}</main>
<footer><p>Generated {esc(now())}. Offline detail page.</p></footer></body></html>'''


def render_html(campaign, console_log=''):
    result = status(campaign)
    nodes, items = campaign['nodes'], base.merge_issues(result['issues'])
    indices = {n['key']: i for i, n in enumerate(nodes)}

    # ---- detail bodies (written to separate files) --------------------- #
    rows, choices, panels = [], [], []
    for node in sorted(nodes, key=node_order):
        i = indices[node['key']]
        node_items = [item for item in items if item['node'] == node['key']]
        health_value = health(node_items)
        state = 'BLOCKED' if node['blocked'] else 'STOPPED' if node['stop_reason'] else campaign['state']
        note = '; '.join(node['blocked']) or node['stop_reason'] or '; '.join(dict.fromkeys(item['component'] + ': ' + item['code'] for item in node_items)) or 'No findings'
        rows.append(f'<tr><td class="target"><a href="details/nodes.html#node-{i}">{esc(node["key"])}</a><small>{esc(node["target"]["os_ip"])}</small></td><td>{badge(health_value)}</td><td>{badge(state)}</td><td>{node["completed"]}</td><td>{esc(note)}</td></tr>')
        choices.append(f'<a class="node-choice" href="#node-{i}" data-panel="node-{i}" data-health="{health_value}">{esc(node["key"])} {badge(health_value)}<small>{node["completed"]} loops</small></a>')
        records = record_html(node['pre'], i, node['pre']) + (record_html(node['start'], i, node['pre']) if node.get('start') else '') + ''.join(record_html(r, i, node['pre']) for r in node['loops'])
        if node.get('recovery_issues'):
            records += f'<details id="node-{i}-recovery"><summary>Recovery integrity {badge("FAIL")}</summary><ul>' + ''.join(f'<li>{esc(item["detail"])}</li>' for item in node['recovery_issues']) + '</ul></details>'
        last = node['loops'][-1] if node['loops'] else node['pre']
        times = [r['duration_seconds'] for r in node['loops'] if r.get('post_complete') and r.get('duration_seconds') is not None]
        notice = f'<p class="notice">{esc("; ".join(node["blocked"]) or node["stop_reason"])}</p>' if node['blocked'] or node['stop_reason'] else ''
        panels.append(f'''<article class="node-panel" id="node-{i}" aria-labelledby="heading-node-{i}"><h2 id="heading-node-{i}">{esc(node['key'])} {badge(health_value)}</h2>{notice}{facts([('BMC', node['target']['bmc_ip']), ('OS', node['target']['os_ip']), ('Node elapsed (PRE to last POST)', duration(elapsed(node['pre']['started'], last.get('finished')))), ('Average completed loop', duration(sum(times) / len(times) if times else None))])}<h3>PRE and cycle history</h3><p class="muted">POST uses the original PRE baseline. PRE-EXISTING findings become KNOWN when repeated.</p>{records}</article>''')

    outcome = f'''<div class="sheet"><div class="outcome"><div><h2>Campaign outcome</h2><p>{esc(campaign.get('stop_reason') or 'Campaign is in progress.')}</p></div><div class="outcome-badges"><div><span class="label">Execution</span>{badge(result['completion'])}</div><div><span class="label">Health</span>{badge(result['health'])}</div></div></div>{facts([('Cycle / channel', f"{campaign['cycle_mode']} / {campaign['channel']}"), ('Requested limits', f"{campaign['limits']['loops'] or 'No'} loop limit / {campaign['limits']['hours'] or 'No'} hour limit"), ('Campaign elapsed', duration(elapsed(campaign['started'], campaign.get('finished') or now()))), ('POST completed', result['completed_node_loops']), ('Attempts', result['attempted_node_loops']), ('Boot confirmed', result['boot_confirmed_node_loops']), ('Valid cycles', result['valid_node_cycles']), ('Escalated findings (WARN→FAIL)', result['escalated']), ('Selected / approved nodes', f"{len(nodes)} / {sum(not n['blocked'] for n in nodes)}"), ('PRE-existing issue groups', result['known']), ('New issue groups during cycling', result['new'])])}</div>'''

    problems_count = len(items)
    node_links = ''.join(
        f'<li><a href="details/node-{esc(n["key"])}.html">Node {esc(n["key"])}</a></li>'
        for n in sorted(nodes, key=node_order))
    overview = f'''<section role="tabpanel" id="overview">{outcome}<div class="sheet"><h2>Target results</h2><p class="muted">All selected nodes. Heavy detail is in the linked pages below.</p><div class="tablewrap"><table id="target-results"><thead><tr><th>Target / OS address</th><th>Health</th><th>Execution</th><th>Completed loops</th><th>Findings</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<div class="sheet" style="margin-top:16px"><h2>Detail pages</h2><p class="muted">Heavy sections live in separate files so this summary opens instantly. Open them from here or from the links above.</p><ul>
<li><a href="details/issues.html">Issue review</a> &mdash; {problems_count} grouped issues (FAIL first).</li>
{node_links}
<li><a href="cycle_summary.txt">cycle_summary.txt</a> &middot; <a href="known_issues.md">known_issues.md</a> &middot; <a href="new_issues.md">new_issues.md</a></li>
</ul></div></section>'''

    css = (base.ASSETS / 'report.css').read_text(encoding='utf-8')
    logo = _wistron_logo()
    summary = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="referrer" content="no-referrer"><title>{esc(campaign['run_id'])} | Cycle review (summary)</title><style>{css}</style></head><body>
    <a class="skip" href="#main">Skip to report</a>
    <div class="brandbar"><div class="brand-lockup">{logo}<span class="brand-caption">System validation</span></div><span>Engineering / Cycle review</span></div><header><a class="spec-link" href="CYCLE_VALIDATION_SPECIFICATION.html">Validation Specification</a><h1>Cycle review &mdash; summary</h1><div class="runline"><code>{esc(campaign['run_id'])}</code><span class="muted">Started {esc(campaign['started'])}</span></div></header>
    <main id="main">{overview}</main><footer><p>Generated {esc(now())}. Offline summary. Open a detail page for full logs.</p><p>Hardware script SHA-256: <code>{esc(campaign['script_sha256'])}</code></p></footer></body></html>'''

    # One detail file per node (keeps each page bounded, instead of one
    # 108 MB page), plus a single issues page (problems/issues were the same
    # issue_cards rendered twice).
    details = {
        'issues.html': _detail_page('Issue review', campaign['run_id'],
            '<div class="sheet"><p>FAIL first, then WARN. Repeated findings are grouped within each node; KNOWN still affects health.</p>' + issue_cards(items, indices) + '</div>'),
    }
    for node, panel in zip(sorted(nodes, key=node_order), panels):
        details[f'node-{node["key"]}.html'] = _detail_page(
            f'Node {node["key"]}', campaign['run_id'],
            '<div class="sheet node-browser"><div class="node-content">' + panel + '</div></div>')
    return summary, details


def write(root):
    root = Path(root)
    from vera_cycle.reporting.cycle_report import read_journal
    campaign = read_journal(root)
    console_path = root / 'console.log'
    console_log = console_path.read_text(encoding='utf-8') if console_path.is_file() else ''
    summary, details = render_html(campaign, console_log)
    atomic_write(root / 'CYCLE_REVIEW_LITE.html', summary)
    ddir = root / 'details'
    ddir.mkdir(exist_ok=True)
    for name, body in details.items():
        atomic_write(ddir / name, body)
    print(f'wrote {root/"CYCLE_REVIEW_LITE.html"}')
    for name in details:
        p = ddir / name
        print(f'  {p}  ({p.stat().st_size/1e6:.1f} MB)')


if __name__ == '__main__':
    write(sys.argv[1] if len(sys.argv) > 1 else '.')
