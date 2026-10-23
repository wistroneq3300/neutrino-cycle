"""Final approved hardening regressions; entirely offline.

These tests encode the final engineering decisions that supersede the older
soft-hostname and two-state issue-classification rules.  No test in this file
opens a network connection or dispatches a real power action.
"""
from __future__ import annotations

import tempfile
import copy
import io
import json
import socket
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from vera_cycle import paths
from vera_cycle.core.cycle_core import (
    aggregate_issues,
    dmesg_issues,
    digest,
    issue,
    parse_policy,
)
from vera_cycle.core.cycle_transport import Command, IdentityUnsafe
from vera_cycle.engine.cycle_engine import NodeSession, new_record
from vera_cycle.cli import campaign
from vera_cycle.cli import discover_interrupted_campaigns, startup_recovery_prompt
from vera_cycle.core.cycle_core import write_json
from vera_cycle.reporting import cycle_report
from vera_cycle.reporting.cycle_report import (
    ReportDegraded,
    issue_cards_compact,
    journal_path,
    merge_issues,
    read_journal,
    rebuild,
    render_html,
    write_reports,
)

from dev.tests.test_cycle import FakeTransport, target


class FinalHostnameDecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.options = SimpleNamespace(
            project='neutrino', cycle_mode='power_cycle', channel='inband',
            boot_timeout=.05, poll_interval=.001, loops=2, hours=0, cycle=True,
            config_script=paths.project_config_path('neutrino'),
            issue_policy=paths.ISSUE_POLICY, output=self.root / 'output',
            sensor_retry_delay=0,
        )
        self.fake = FakeTransport({}, self.root / 'ssh')
        self.session = NodeSession(
            target(), self.fake, self.root, 'final-hostname', b'script',
            digest(b'script'), self.options,
            parse_policy(self.options.issue_policy.read_text(encoding='utf-8')),
        )

    def tearDown(self):
        self.temp.cleanup()

    def ready(self):
        self.session.precheck()
        self.assertFalse(self.session.node['blocked'])
        self.session.start()

    def test_start_hostname_mismatch_prohibits_start(self):
        self.session.precheck()
        self.fake.mismatch = True
        with self.assertRaises(IdentityUnsafe):
            self.session.start()
        self.assertFalse(any(cmd in {
            'reboot', 'ipmitool power cycle', 'power cycle', 'power reset',
            '/usr/bin/stbypowerctrl.sh aux_cycle',
            '/usr/bin/powerctrl.sh power_cycle',
        } for _, _, cmd in self.fake.calls))

    def test_loop_hostname_mismatch_is_fail_and_node_continues(self):
        self.ready()
        self.fake.on_action = lambda: setattr(self.fake, 'mismatch', True)
        record = self.session.one_loop(1)
        finding = next(i for i in record['issues'] if i['code'] == 'HOSTNAME_MISMATCH')
        self.assertEqual(finding['severity'], 'FAIL')
        self.assertEqual(record['status'], 'FAIL')
        self.assertTrue(self.session.node['active'])
        self.assertEqual(self.session.node['attempts'], 1)

    def test_transient_loop_mismatch_cannot_be_washed_out_later_in_round(self):
        self.ready()
        original = self.fake.ssh
        injected = {'done': False}

        def one_bad_identity(t, role, cmd, timeout=60, sudo=False):
            if ("printf 'HOSTNAME='" in cmd and role == 'os'
                    and self.fake.boots.get(t.key, 0) > 0 and not injected['done']):
                injected['done'] = True
                boot = f'00000000-0000-0000-0000-{self.fake.boots[t.key]:012d}'
                return Command(0, f'HOSTNAME=wrong-once\nBOOT_ID={boot}\n')
            return original(t, role, cmd, timeout, sudo)

        with patch.object(self.fake, 'ssh', side_effect=one_bad_identity):
            record = self.session.one_loop(1)
        self.assertTrue(injected['done'])
        self.assertEqual(record['identities']['os']['hostname'], 'os-n1')
        mismatch = [i for i in record['issues'] if i['code'] == 'HOSTNAME_MISMATCH']
        self.assertEqual(len(mismatch), 1)
        self.assertEqual(mismatch[0]['severity'], 'FAIL')
        self.assertEqual(record['status'], 'FAIL')
        self.assertTrue(self.session.node['active'])


class FinalDmesgCountingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        options = SimpleNamespace(
            project='neutrino', cycle_mode='power_cycle', channel='inband',
            boot_timeout=.05, poll_interval=.001, loops=1, hours=0, cycle=True,
            config_script=paths.project_config_path('neutrino'),
            issue_policy=paths.ISSUE_POLICY, output=self.root / 'output',
            sensor_retry_delay=0,
        )
        self.fake = FakeTransport({}, self.root / 'ssh')
        self.session = NodeSession(
            target(), self.fake, self.root, 'final-dmesg', b'script',
            digest(b'script'), options, [],
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_overlapping_capture_counts_only_the_new_occurrence(self):
        record = new_record('LOOP 1')
        record['loop'] = 1
        record['identities']['os'] = {
            'hostname': 'os-n1',
            'boot_id': '00000000-0000-0000-0000-000000000001',
        }
        line1 = '[ 10.0] pcieport 0000:01:00.0: BAR assignment failed\n'
        line2 = '[ 11.0] pcieport 0000:01:00.0: BAR assignment failed\n'
        replies = iter((Command(0, line1), Command(0, line1 + line2)))
        original = self.fake.ssh

        def overlapping(t, role, cmd, timeout=60, sudo=False):
            if cmd in {'dmesg', 'dmesg -c'}:
                return next(replies)
            return original(t, role, cmd, timeout, sudo)

        with patch.object(self.fake, 'ssh', side_effect=overlapping):
            self.session.collect_dmesg(record, 'dmesg_probe')
            self.session.collect_dmesg(record, 'dmesg_clear', clear=True)
        findings = [i for i in record['issues'] if i['code'] == 'DMESG_BUNDLE']
        self.assertEqual(sum(i['occurrence_count'] for i in findings), 2)
        self.assertEqual([i['occurrence_count'] for i in findings], [1, 1])

    def test_normal_loop_collects_dmesg_once_at_the_end(self):
        self.session.precheck()
        self.session.start()
        self.fake.calls.clear()
        self.session.one_loop(1)
        dmesg_commands = [command for _, role, command in self.fake.calls
                           if role == 'os' and command in {'dmesg', 'dmesg -c'}]
        self.assertEqual(dmesg_commands, ['dmesg -c'])

    def test_different_devices_are_separate_cards_and_keep_true_counts(self):
        text = ('[ 10.0] pcieport 0000:01:00.0: BAR assignment failed\n'
                '[ 11.0] pcieport 0000:01:00.0: BAR assignment failed\n'
                '[ 12.0] pcieport 0000:02:00.0: BAR assignment failed\n')
        record = new_record('LOOP 1')
        record.update(loop=1, post_complete=True, issues=dmesg_issues(text))
        node = {'key': 'tray1_n1', 'pre': new_record('PRE'), 'loops': [record]}
        items = merge_issues(aggregate_issues({'nodes': [node]}))
        bundles = [item for item in items if item['code'] == 'DMESG_BUNDLE']
        self.assertEqual(len(bundles), 2)
        by_device = {item['device'][0]: item for item in bundles}
        self.assertEqual(set(by_device), {'0000:01:00.0', '0000:02:00.0'})
        self.assertEqual(sum(event['occurrence_count']
                             for event in by_device['0000:01:00.0']['occurrences']), 2)
        self.assertEqual(sum(event['occurrence_count']
                             for event in by_device['0000:02:00.0']['occurrences']), 1)
        page = issue_cards_compact(bundles, {'tray1_n1': 0})
        self.assertEqual(page.count('class="issue-row"'), 2)


def redfish_finding(severity='FAIL'):
    item = issue(
        'REDFISH_CRITICAL' if severity == 'FAIL' else 'REDFISH_WARNING',
        'eventlog', 'Redfish EventLog: 48 service fault', severity=severity,
    )
    item['identity'] = 'EventLog|48|service fault'
    return item


def loop(number, findings=(), availability='AVAILABLE'):
    record = new_record(f'LOOP {number}')
    record['loop'] = number
    record['issues'] = list(findings)
    record['observation_status'] = {'eventlog': availability}
    record['eventlog_delta_ids'] = (
        ['48'] if number == 1 and findings else []
    ) if availability == 'AVAILABLE' else None
    return record


class FinalIssueStateTests(unittest.TestCase):
    def campaign(self, records):
        return {'nodes': [{'key': 'tray1_n1', 'pre': new_record('PRE'), 'loops': records}]}

    def test_new_known_recurrence_after_confirmed_recovery(self):
        records = [
            loop(1, [redfish_finding()]),
            loop(2, [redfish_finding()]),
            loop(3),
            loop(4),
            loop(5, [redfish_finding()]),
        ]
        item = aggregate_issues(self.campaign(records))[0]
        per_phase = {o['phase']: o['classification'] for o in item['occurrences']}
        self.assertEqual(per_phase, {
            'LOOP 1': 'NEW', 'LOOP 2': 'KNOWN', 'LOOP 5': 'RECURRENCE',
        })

    def test_unavailable_gap_is_not_recovery(self):
        records = [
            loop(1, [redfish_finding()]),
            loop(2, availability='UNAVAILABLE'),
            loop(3, [redfish_finding()]),
        ]
        item = aggregate_issues(self.campaign(records))[0]
        per_phase = {o['phase']: o['classification'] for o in item['occurrences']}
        self.assertEqual(per_phase['LOOP 3'], 'KNOWN')

    def test_continuous_warning_to_critical_is_one_issue_with_two_severity_segments(self):
        records = [
            loop(1, [redfish_finding('WARN')]),
            loop(2, [redfish_finding('FAIL')]),
        ]
        items = aggregate_issues(self.campaign(records))
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual([o['severity'] for o in item['occurrences']], ['WARN', 'FAIL'])
        self.assertEqual([o['classification'] for o in item['occurrences']], ['NEW', 'KNOWN'])


def complete_campaign(nodes):
    return {
        'run_id': 'synthetic-final-hardening',
        'project': 'neutrino',
        'started': '2026-10-24T00:00:00+08:00',
        'finished': '2026-10-24T00:01:00+08:00',
        'state': 'COMPLETE',
        'stop_reason': 'Synthetic acceptance fixture completed',
        'cycle_mode': 'power_cycle',
        'channel': 'outband',
        'limits': {'loops': 280, 'hours': 0},
        'script_sha256': '0' * 64,
        'nodes': nodes,
        'synthetic': True,
    }


def report_node(key='tray1_n1', records=()):
    pre = new_record('PRE')
    pre.update(status='PASS', finished='2026-10-24T00:00:01+08:00')
    records = list(records)
    return {
        'key': key,
        'target': {
            'tray': key.split('_')[0], 'node': key.split('_')[-1],
            'bmc_ip': '192.0.2.1', 'os_ip': '192.0.2.2',
        },
        'blocked': [], 'active': False, 'pre': pre, 'loops': records,
        'completed': len(records), 'attempts': len(records),
        'boot_confirmed': len(records), 'valid_cycles': len(records),
        'stop_reason': '', 'persistence': 'OK', 'persistence_detail': '',
    }


class FinalHtmlLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def campaign_options(self):
        return SimpleNamespace(
            project='neutrino', cycle_mode='power_cycle', channel='inband',
            boot_timeout=.05, poll_interval=.001, loops=2, hours=0, cycle=True,
            config_script=paths.project_config_path('neutrino'),
            issue_policy=paths.ISSUE_POLICY, output=self.root / 'campaigns',
            inventory=paths.inventory_path('neutrino'), sensor_retry_delay=0,
        )

    def test_full_html_is_rendered_once_at_terminal_state_not_each_loop(self):
        options = self.campaign_options()
        with patch.object(cycle_report, 'render_html', wraps=cycle_report.render_html) as renderer:
            campaign(options, [target()], {}, confirm=lambda _: 'yes',
                     transport_factory=FakeTransport, runtime_root=self.root / 'runtime')
        output = next(options.output.iterdir())
        self.assertEqual(renderer.call_count, 1)
        self.assertTrue((output / 'CYCLE_REVIEW_REPORT.html').is_file())
        self.assertEqual(read_journal(output)['report']['state'], 'READY')

    def test_failed_html_history_survives_successful_manual_rebuild(self):
        data = complete_campaign([report_node()])
        output = self.root / data['run_id']
        output.mkdir()
        with patch.object(cycle_report, 'render_html', side_effect=ValueError('bad template')):
            with self.assertRaises(ReportDegraded):
                write_reports(output, data)
        failed = read_journal(output)
        self.assertEqual(failed['report']['state'], 'FAILED')
        self.assertTrue(any(h['state'] == 'FAILED' and 'bad template' in h['detail']
                            for h in failed['report']['history']))
        rebuilt = rebuild(output)
        self.assertEqual(rebuilt['report']['state'], 'READY')
        self.assertTrue(any(h['state'] == 'FAILED' and 'bad template' in h['detail']
                            for h in rebuilt['report']['history']))
        page = (output / 'CYCLE_REVIEW_REPORT.html').read_text(encoding='utf-8')
        self.assertIn('Output recovery history', page)
        self.assertIn('bad template', page)

    def test_one_card_contains_lifecycle_and_severity_segments(self):
        repeated_with_count_detail = redfish_finding('FAIL')
        repeated_with_count_detail['detail'] += ' (second captured occurrence)'
        records = [
            loop(1, [redfish_finding('WARN')]),
            loop(2, [redfish_finding('FAIL')]),
            loop(3, [repeated_with_count_detail]),
            loop(4),
            loop(5, [redfish_finding('FAIL')]),
        ]
        items = merge_issues(aggregate_issues(complete_campaign([report_node(records=records)])))
        page = issue_cards_compact(items, {'tray1_n1': 0})
        self.assertEqual(page.count('class="issue-row"'), 1)
        self.assertIn('NEW', page)
        self.assertIn('KNOWN', page)
        self.assertIn('RECURRENCE', page)
        self.assertIn('WARN', page)
        self.assertIn('FAIL', page)
        self.assertIn('loop 2-3', page)
        self.assertIn('loop 5', page)

    def test_synthetic_four_node_280_loop_report_is_complete_html(self):
        nodes = []
        for node_number in range(1, 5):
            records = []
            for number in range(1, 281):
                record = new_record(f'LOOP {number}')
                record.update(
                    loop=number, status='PASS', post_complete=True,
                    valid_cycle=True, finished='2026-10-24T00:01:00+08:00',
                    duration_seconds=.1,
                )
                records.append(record)
            nodes.append(report_node(f'tray1_n{node_number}', records))
        page = render_html(complete_campaign(nodes))
        self.assertTrue(page.startswith('<!doctype html>'))
        self.assertTrue(page.rstrip().endswith('</html>'))
        self.assertIn('SYNTHETIC DEMONSTRATION', page)
        self.assertIn('LOOP 280', page)
        self.assertEqual(page.count('class="node-panel"'), 4)


class FinalRecoveryStartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output_root = self.root / 'campaigns'
        self.output = self.output_root / 'interrupted-final-fixture'
        self.output.mkdir(parents=True)
        record = new_record('LOOP 1')
        record.update(loop=1, status='PASS', post_complete=True, boot_confirmed=True,
                      valid_cycle=True,
                      finished='2026-10-24T00:00:02+08:00')
        self.data = complete_campaign([report_node(records=[record])])
        self.data.update(
            run_id=self.output.name, state='RUNNING', finished=None,
            writer_owner={
                'pid': 2147483647, 'process_token': 'dead-fixture',
                'host': socket.gethostname(),
            },
        )
        write_json(journal_path(self.output), self.data)

    def tearDown(self):
        journal = journal_path(self.output)
        try:
            journal.unlink()
            journal.parent.rmdir()
        except OSError:
            pass
        self.temp.cleanup()

    def test_dead_running_campaign_is_detected_without_mutation(self):
        before = journal_path(self.output).read_bytes()
        found = discover_interrupted_campaigns(self.output_root)
        self.assertEqual([item['run_id'] for item in found], [self.output.name])
        self.assertEqual(journal_path(self.output).read_bytes(), before)

    def test_skip_keeps_history_and_does_not_force_rebuild(self):
        before = journal_path(self.output).read_bytes()
        out = io.StringIO()
        result = startup_recovery_prompt(
            self.output_root, input_func=lambda _: 's', output_func=out.write,
        )
        self.assertEqual(result[0]['action'], 'SKIPPED')
        self.assertEqual(journal_path(self.output).read_bytes(), before)
        self.assertFalse((self.output / 'CYCLE_REVIEW_REPORT.html').exists())

    def test_operator_selected_rebuild_recovers_without_any_power_action(self):
        out = io.StringIO()
        result = startup_recovery_prompt(
            self.output_root, input_func=lambda _: 'r', output_func=out.write,
        )
        self.assertEqual(result[0]['action'], 'REBUILT')
        recovered = read_journal(self.output)
        self.assertEqual(recovered['state'], 'INCOMPLETE')
        self.assertEqual(recovered['report']['state'], 'READY')
        self.assertTrue((self.output / 'CYCLE_REVIEW_REPORT.html').is_file())


class FinalDeliveryZipTests(unittest.TestCase):
    def test_delivery_zip_includes_evidence_and_snapshots_but_never_journal(self):
        from vera_cycle.reporting.cycle_report import create_delivery_zip

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / 'run'
            (root / 'tray1_n1' / 'loop0001').mkdir(parents=True)
            expected = {
                'CYCLE_REVIEW_REPORT.html': '<html>ready</html>',
                'console.log': 'operator log\n',
                'run_status.json': '{}\n',
                'neutrino_inventory.snapshot.csv': 'tray,node\ntray1,n1\n',
                'neutrino_config.snapshot.sh': '# config\n',
                'tray1_n1/loop0001/report.json': '{"loop": 1}\n',
                'tray1_n1/loop0001/dmesg_clear.txt': 'raw kernel evidence\n',
            }
            for name, content in expected.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')
            (root / 'campaign.json').write_text('{"must": "stay out"}\n', encoding='utf-8')
            (root / '.ssh').mkdir()
            (root / '.ssh' / 'known_hosts').write_text('host key\n', encoding='utf-8')
            archive = create_delivery_zip(root)
            with zipfile.ZipFile(archive) as bundle:
                members = set(bundle.namelist())
                self.assertEqual(members, set(expected))
                self.assertEqual(bundle.read('tray1_n1/loop0001/dmesg_clear.txt'),
                                 (root / 'tray1_n1/loop0001/dmesg_clear.txt').read_bytes())
            self.assertTrue((root / 'campaign.json').is_file())


if __name__ == '__main__':
    unittest.main()
