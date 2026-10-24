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

# Every command that can change the physical power state of a node. Tests assert
# against this set whenever they must prove that no power action was issued.
POWER_COMMANDS = {
    'reboot', 'ipmitool power cycle', 'power cycle', 'power reset',
    '/usr/bin/stbypowerctrl.sh aux_cycle', '/usr/bin/powerctrl.sh power_cycle',
}


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
        self.assertFalse(any(cmd in POWER_COMMANDS for _, _, cmd in self.fake.calls))

    def test_loop_mismatch_before_action_sends_no_power(self):
        """A host that already reports the wrong hostname must never be cycled.

        The pre-action identity check is strict (same rule as PRE and START), so
        the node stops before any power command is issued. Only that node stops.
        """
        self.ready()
        self.fake.mismatch = True          # wrong hostname BEFORE the loop starts
        self.fake.calls.clear()
        record = self.session.one_loop(1)
        self.assertEqual([call for call in self.fake.calls if call[2] in POWER_COMMANDS], [])
        self.assertFalse(self.session.node['active'])
        self.assertEqual(self.session.node['attempts'], 0)
        codes = [issue['code'] for issue in record['issues']]
        self.assertIn('IDENTITY_UNSAFE', codes)
        self.assertEqual(record['status'], 'FAIL')

    def test_loop_mismatch_detected_after_action_keeps_prior_history(self):
        """A mismatch first seen AFTER the power action cannot un-issue it.

        This is the residual case: the pre-action check passed, the action ran,
        and the node came back as a different machine. The loop is FAIL, the
        history is retained, and no automatic retry/power is issued.
        """
        self.ready()
        self.fake.on_action = lambda: setattr(self.fake, 'mismatch', True)
        record = self.session.one_loop(1)
        finding = next(i for i in record['issues'] if i['code'] == 'HOSTNAME_MISMATCH')
        self.assertEqual(finding['severity'], 'FAIL')
        self.assertEqual(record['status'], 'FAIL')
        self.assertTrue(self.session.node['active'])
        self.assertEqual(self.session.node['attempts'], 1)
        power_calls = [call for call in self.fake.calls if call[2] in POWER_COMMANDS]
        self.assertEqual(len(power_calls), 1, 'the one approved action, never a retry')

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

    def test_every_hostname_check_is_retained_without_duplicate_fail_cards(self):
        record = new_record('LOOP 100')
        record['loop'] = 100
        boot = '00000000-0000-0000-0000-000000000100'
        replies = iter((
            Command(0, f'HOSTNAME=wrong-A\nBOOT_ID={boot}\n'),
            Command(0, f'HOSTNAME=wrong-B\nBOOT_ID={boot}\n'),
            Command(0, f'HOSTNAME=os-n1\nBOOT_ID={boot}\n'),
        ))
        with patch.object(self.fake, 'ssh', side_effect=lambda *args, **kwargs: next(replies)):
            self.session.identity(record, 'os', stem='post_identity_1')
            self.session.identity(record, 'os', stem='post_identity_2')
            self.session.identity(record, 'os', stem='final_identity')
        observations = record['identity_observations']
        self.assertEqual([o['actual'] for o in observations], ['wrong-A', 'wrong-B', 'os-n1'])
        self.assertEqual([o['result'] for o in observations], ['MISMATCH', 'MISMATCH', 'MATCH'])
        self.assertEqual([o['stage'] for o in observations],
                         ['post_identity_1', 'post_identity_2', 'final_identity'])
        self.assertEqual(record['identities']['os']['hostname'], 'os-n1')
        self.assertEqual(len([i for i in record['issues']
                              if i['code'] == 'HOSTNAME_MISMATCH']), 1)
        page = cycle_report.record_html_compact(record, 0)
        self.assertIn('wrong-A', page)
        self.assertIn('wrong-B', page)
        self.assertIn('final_identity', page)
        unavailable = new_record('LOOP 101')
        unavailable['loop'] = 101
        with patch.object(self.fake, 'ssh', return_value=Command(255, 'down')):
            with self.assertRaises(ConnectionError):
                self.session.identity(unavailable, 'os', stem='named_unavailable')
        self.assertEqual(unavailable['identity_observations'], [{
            'role': 'os', 'stage': 'named_unavailable', 'expected': 'os-n1',
            'actual': '', 'result': 'UNAVAILABLE',
        }])
        invalid = new_record('LOOP 102')
        invalid['loop'] = 102
        with patch.object(
                self.fake, 'ssh',
                return_value=Command(0, 'HOSTNAME=os-n1\nBOOT_ID=invalid\n')):
            with self.assertRaises(IdentityUnsafe):
                self.session.identity(
                    invalid, 'os', save_evidence=False, record_command=False)
        self.assertEqual(invalid['identity_observations'], [{
            'role': 'os', 'stage': 'os_identity', 'expected': 'os-n1',
            'actual': 'os-n1', 'result': 'INVALID_BOOT_ID',
        }])


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

    def test_aliasing_bundle_entries_preserve_count_conservation(self):
        """Different raw lines may share one logical, counter-free identity."""
        record = new_record('LOOP 50')
        record['loop'] = 50
        record['identities']['os'] = {
            'hostname': 'os-n1',
            'boot_id': '00000000-0000-0000-0000-000000000050',
        }
        text = ('[ 10.0] pcieport 0000:01:00.0: I/O 1 failed\n'
                '[ 11.0] pcieport 0000:01:00.0: I/O 2 failed\n')
        original = self.fake.ssh

        def one_capture(t, role, cmd, timeout=60, sudo=False):
            if cmd == 'dmesg -c':
                return Command(0, text)
            return original(t, role, cmd, timeout, sudo)

        with patch.object(self.fake, 'ssh', side_effect=one_capture):
            self.session.collect_dmesg(record, 'dmesg_clear', clear=True)

        bundles = [i for i in record['issues'] if i['code'] == 'DMESG_BUNDLE']
        self.assertEqual(len(bundles), 1)
        self.assertEqual(bundles[0]['occurrence_count'], 2)
        self.assertEqual([e['count'] for e in bundles[0]['entries']], [1, 1])
        self.assertEqual(sum(e['count'] for e in bundles[0]['entries']), 2)
        self.assertEqual(len(bundles[0]['observations']), 2)
        node = {'key': 'tray1_n1', 'pre': new_record('PRE'), 'loops': [record]}
        findings = [i for i in aggregate_issues({'nodes': [node]})
                    if i['code'] == 'DMESG_BUNDLE']
        self.assertEqual(len(findings), 1)
        self.assertEqual(sum(o['occurrence_count'] for o in findings[0]['occurrences']), 2)
        self.assertIn('I/O 1 failed', bundles[0]['entries'][0]['text'])
        self.assertIn('I/O 2 failed', bundles[0]['entries'][1]['text'])

    def test_changed_bundle_signature_does_not_recount_prior_message(self):
        """A followed by overlapping A+B contributes A once and B once."""
        record = new_record('LOOP 51')
        record['loop'] = 51
        record['identities']['os'] = {
            'hostname': 'os-n1',
            'boot_id': '00000000-0000-0000-0000-000000000051',
        }
        first = '[ 10.0] pcieport 0000:01:00.0: BAR assignment failed\n'
        second = '[ 11.0] pcieport 0000:01:00.0: device reset failed\n'
        replies = iter((Command(0, first), Command(0, first + second)))
        original = self.fake.ssh

        def overlapping(t, role, cmd, timeout=60, sudo=False):
            if cmd in {'dmesg', 'dmesg -c'}:
                return next(replies)
            return original(t, role, cmd, timeout, sudo)

        with patch.object(self.fake, 'ssh', side_effect=overlapping):
            self.session.collect_dmesg(record, 'dmesg_probe')
            self.session.collect_dmesg(record, 'dmesg_clear', clear=True)
        bundles = [i for i in record['issues'] if i['code'] == 'DMESG_BUNDLE']
        self.assertEqual(sum(i['occurrence_count'] for i in bundles), 2)
        self.assertEqual(sum(e['count'] for i in bundles for e in i['entries']), 2)
        self.assertEqual([i['occurrence_count'] for i in bundles], [1, 1])
        self.assertEqual(len(bundles[1]['entries']), 1)
        self.assertIn('device reset failed', bundles[1]['entries'][0]['text'])
        self.assertIn('device reset failed', bundles[1]['snippet'])
        self.assertNotIn('BAR assignment failed', bundles[1]['snippet'])
        self.assertEqual(bundles[1]['new_observations'], bundles[1]['observations'])

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
        self.assertNotIn('Event IDs:', page)


def redfish_finding(severity='FAIL', event_id='48', message='service fault', service='EventLog'):
    item = issue(
        'REDFISH_CRITICAL' if severity == 'FAIL' else 'REDFISH_WARNING',
        'eventlog' if service == 'EventLog' else 'redfish_sel',
        f'Redfish {service}: {event_id} {message}', severity=severity,
    )
    item['identity'] = f'{service}|{event_id}|{message}'
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
        items = merge_issues(aggregate_issues(self.campaign(records)))
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual([o['severity'] for o in item['occurrences']], ['WARN', 'FAIL'])
        self.assertEqual([o['classification'] for o in item['occurrences']], ['NEW', 'KNOWN'])

    def test_redfish_same_fault_with_new_event_id_is_recurrence(self):
        first = loop(20, [redfish_finding(event_id='7')])
        first['redfish_delta_ids'] = ['EventLog|7']
        empty = loop(21)
        empty['redfish_delta_ids'] = []
        repeated = loop(22, [redfish_finding(event_id='8')])
        repeated['redfish_delta_ids'] = ['EventLog|8']
        items = aggregate_issues(self.campaign([first, empty, repeated]))
        self.assertEqual(len(items), 1)
        phases = {o['phase']: o['classification'] for o in items[0]['occurrences']}
        self.assertEqual(phases, {'LOOP 20': 'NEW', 'LOOP 22': 'RECURRENCE'})
        self.assertEqual({event_id for o in items[0]['occurrences']
                          for event_id in o['event_ids']}, {'7', '8'})

    def test_redfish_accumulated_ids_are_sorted_and_raw_ids_are_retained(self):
        records = []
        for number, ids in ((1, ('7',)), (2, ('7', '8')), (3, ('7', '8'))):
            record = loop(number, [redfish_finding(event_id=value) for value in ids])
            record['redfish_delta_ids'] = ([f'EventLog|{value}' for value in ids]
                                           if number == 1 else
                                           (['EventLog|8'] if number == 2 else []))
            records.append(record)
        item = merge_issues(aggregate_issues(self.campaign(records)))[0]
        self.assertEqual([o['phase'] for o in item['occurrences']],
                         ['LOOP 1', 'LOOP 2', 'LOOP 3'])
        self.assertEqual([o['event_ids'] for o in item['occurrences']],
                         [['7'], ['7', '8'], ['7', '8']])
        self.assertEqual([o['occurrence_count'] for o in item['occurrences']], [1, 2, 2])
        self.assertEqual(sum(s['occurrence_count'] for s in item['segments']), 5)

    def test_same_loop_redfish_ids_use_one_worst_severity_observation(self):
        previous = loop(1, [redfish_finding('FAIL', event_id='7')])
        previous['redfish_delta_ids'] = ['EventLog|7']
        mixed = loop(2, [redfish_finding('WARN', event_id='7'),
                         redfish_finding('FAIL', event_id='8')])
        mixed['redfish_delta_ids'] = ['EventLog|8']
        item = merge_issues(aggregate_issues(self.campaign([previous, mixed])))[0]
        self.assertEqual([o['severity'] for o in item['occurrences']], ['FAIL', 'FAIL'])
        self.assertEqual([o['classification'] for o in item['occurrences']], ['NEW', 'KNOWN'])
        self.assertEqual(len(item['segments']), 2)
        self.assertFalse(item.get('severity_changed', False))

    def test_redfish_logical_identity_keeps_service_and_full_pipe_message(self):
        records = [
            loop(1, [redfish_finding(event_id='9', message='rail | service fault'),
                     redfish_finding(event_id='9', message='rail | service fault', service='SEL')]),
        ]
        records[0]['redfish_delta_ids'] = ['EventLog|9', 'SEL|9']
        items = merge_issues(aggregate_issues(self.campaign(records)))
        self.assertEqual(len(items), 2)
        self.assertEqual({i['component'] for i in items}, {'eventlog', 'redfish_sel'})
        self.assertTrue(all('rail | service fault' in i['identity'] for i in items))
        blank = loop(2, [redfish_finding(event_id='10', message=''),
                         redfish_finding(event_id='11', message='')])
        blank['redfish_delta_ids'] = ['EventLog|10', 'EventLog|11']
        blank_items = merge_issues(aggregate_issues(self.campaign([blank])))
        self.assertEqual(len(blank_items), 2)

    def test_pci_collection_failure_does_not_prove_recovery(self):
        drift = issue('PCI_DRIFT', '0000:01:00.0', 'PRE device -> POST missing')
        first = new_record('LOOP 1')
        first.update(loop=1, issues=[drift], post_complete=True,
                     hardware_execution_complete=True)
        first['commands']['pci'] = {'valid': True}
        unavailable = new_record('LOOP 2')
        unavailable.update(loop=2, post_complete=True,
                           hardware_execution_complete=True)
        unavailable['commands']['pci'] = {'valid': False}
        repeated = new_record('LOOP 3')
        repeated.update(loop=3, issues=[copy.deepcopy(drift)], post_complete=True,
                        hardware_execution_complete=True)
        repeated['commands']['pci'] = {'valid': True}
        item = aggregate_issues(self.campaign([first, unavailable, repeated]))[0]
        self.assertEqual([o['classification'] for o in item['occurrences']],
                         ['NEW', 'KNOWN'])

    def test_card_total_counts_every_loop_not_just_the_first(self):
        """The card header must report the campaign lifetime, not one loop.

        ``entries`` carries the message breakdown of a single observation, so a
        card that showed only that sum reported the first loop's count for a
        finding that recurred in every loop.
        """
        records = []
        for number in range(1, 4):
            record = new_record(f'LOOP {number}')
            finding = dmesg_issues('[ 1.0] pcieport 0000:01:00.0: BAR 0: failed to assign\n'
                                   '[ 2.0] pcieport 0000:01:00.0: BAR 2: failed to assign\n')
            for event in finding:
                event.update(boot_id='b', phase='dmesg_clear', evidence='e')
            record.update(loop=number, status='FAIL', post_complete=True, valid_cycle=True,
                          issues=finding, duration_seconds=.1)
            record['identities']['os'] = {'hostname': 'os-n1', 'boot_id': 'b'}
            record['observation_status'].update(dmesg='AVAILABLE')
            records.append(record)
        campaign_data = complete_campaign([report_node('tray1_n1', records)])
        cards = [i for i in aggregate_issues(campaign_data) if i['code'].startswith('DMESG_')]
        expected = sum(sum(e['count'] for e in i.get('entries') or [])
                       for record in records for i in record['issues']
                       if i['code'].startswith('DMESG_'))
        self.assertEqual(sum(card['occurrence_count'] for card in cards), expected)
        for card in cards:
            self.assertEqual(card['occurrence_count'], 3, 'three loops x one occurrence')
        page = render_html(campaign_data)
        self.assertIn('3 occurrence(s)', page)
        self.assertIn('loop 1-3', page)

    def test_empty_pci_inventory_does_not_prove_recovery(self):
        drift = issue('PCI_DRIFT', '0000:01:00.0', 'PRE device -> POST missing')
        first = new_record('LOOP 1')
        first.update(loop=1, issues=[drift], post_complete=True)
        empty = new_record('LOOP 2')
        empty.update(loop=2, post_complete=True, pci={})
        empty['commands']['pci'] = {'valid': True}
        repeated = new_record('LOOP 3')
        repeated.update(loop=3, issues=[copy.deepcopy(drift)], post_complete=True)
        item = aggregate_issues(self.campaign([first, empty, repeated]))[0]
        self.assertEqual([o['classification'] for o in item['occurrences']],
                         ['NEW', 'KNOWN'])


class FinalSourceObservationTests(unittest.TestCase):
    """Production capture writes the metadata consumed by lifecycle recovery."""

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
        self.fake.hardware_failure = False
        self.session = NodeSession(
            target(), self.fake, self.root, 'source-observation', b'script',
            digest(b'script'), options, [],
        )
        self.session.precheck()

    def tearDown(self):
        self.temp.cleanup()

    def post_record(self, number=1):
        record = new_record(f'LOOP {number}')
        record['loop'] = number
        return record

    def test_pci_failure_and_empty_output_are_formally_unavailable(self):
        original = self.fake.ssh
        for result in (Command(1, 'lspci failed'), Command(0, 'not a full BDF row')):
            record = self.post_record()

            def replace_pci(t, role, cmd, timeout=60, sudo=False, reply=result):
                if cmd == 'lspci -Dnn':
                    return reply
                return original(t, role, cmd, timeout, sudo)

            with patch.object(self.fake, 'ssh', side_effect=replace_pci):
                self.session.capture(record, post=True)
            self.assertEqual(record['observation_status']['pci'], 'UNAVAILABLE')
            self.assertTrue(record['hardware_execution_complete'])

        def fail_usb_sources(t, role, cmd, timeout=60, sudo=False):
            if cmd in {'lsusb', 'lsusb -tv'}:
                return Command(1, f'{role} USB collection failed')
            return original(t, role, cmd, timeout, sudo)

        usb_record = self.post_record(2)
        with patch.object(self.fake, 'ssh', side_effect=fail_usb_sources):
            self.session.capture(usb_record, post=True)
        self.assertEqual(usb_record['observation_status']['usb'], 'UNAVAILABLE')
        self.assertEqual(usb_record['observation_status']['bmc_usb'], 'UNAVAILABLE')
        self.assertTrue(usb_record['hardware_execution_complete'])

    def test_network_failure_and_sensor_confirmation_failure_are_unavailable(self):
        original_ssh = self.fake.ssh
        original_oob = self.fake.oob
        sensor_reads = {'count': 0}

        def fail_network(t, role, cmd, timeout=60, sudo=False):
            if cmd == 'ip address show':
                return Command(1, 'network collection failed')
            return original_ssh(t, role, cmd, timeout, sudo)

        def incomplete_sensor(t, cmd, timeout=30):
            if cmd == 'sensor list':
                sensor_reads['count'] += 1
                if sensor_reads['count'] == 1:
                    return Command(0, 'Temp | 30 | degrees C | ok | na\n')
                return Command(1, 'sensor confirmation failed')
            return original_oob(t, cmd, timeout)

        record = self.post_record()
        with patch.object(self.fake, 'ssh', side_effect=fail_network), \
                patch.object(self.fake, 'oob', side_effect=incomplete_sensor):
            self.session.capture(record, post=True)
        self.assertEqual(record['observation_status']['network'], 'UNAVAILABLE')
        self.assertEqual(record['observation_status']['sensor'], 'UNAVAILABLE')
        self.assertTrue(any(i['code'] == 'SENSOR_CONFIRM_FAILED'
                            for i in record['issues']))

        blank_reads = {'count': 0}

        def empty_confirmation(t, cmd, timeout=30):
            if cmd == 'sensor list':
                blank_reads['count'] += 1
                return (Command(0, 'Temp | 30 | degrees C | ok | na\n')
                        if blank_reads['count'] == 1 else Command(0, ''))
            return original_oob(t, cmd, timeout)

        empty = self.post_record(2)
        with patch.object(self.fake, 'oob', side_effect=empty_confirmation):
            self.session.capture(empty, post=True)
        self.assertIn('sensor_confirmation', empty)
        self.assertEqual(empty['sensor_confirmation'], [])
        self.assertEqual(empty['observation_status']['sensor'], 'UNAVAILABLE')

        critical = issue('SENSOR_CRITICAL', 'Temp', 'Status critical; reading 90')
        first = self.post_record(1)
        first['issues'] = [critical]
        first['observation_status']['sensor'] = 'AVAILABLE'
        repeated = self.post_record(3)
        repeated['issues'] = [copy.deepcopy(critical)]
        repeated['observation_status']['sensor'] = 'AVAILABLE'
        data = {'nodes': [{'key': 'tray1_n1', 'pre': new_record('PRE'),
                           'loops': [first, empty, repeated]}]}
        finding = next(item for item in aggregate_issues(data)
                       if item['code'] == 'SENSOR_CRITICAL' and item['component'] == 'Temp')
        self.assertEqual([o['classification'] for o in finding['occurrences']],
                         ['NEW', 'KNOWN'])


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
        self.assertIn('Report: READY',
                      (output / 'cycle_summary.txt').read_text(encoding='utf-8'))
        self.assertIn('Report: READY',
                      (output / 'CYCLE_REVIEW_REPORT.md').read_text(encoding='utf-8'))

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
        summary = (output / 'cycle_summary.txt').read_text(encoding='utf-8')
        markdown = (output / 'CYCLE_REVIEW_REPORT.md').read_text(encoding='utf-8')
        self.assertIn('Report: READY', summary)
        self.assertIn('Report: READY', markdown)
        self.assertNotIn('Report: FAILED', summary)
        self.assertNotIn('Report: FAILED', markdown)

        # A lightweight-summary failure must not rewrite the successful HTML
        # outcome, and the renderer must still run only once.
        summary_failure = self.root / 'summary-failure'
        summary_failure.mkdir()
        failed_summary_campaign = complete_campaign([report_node()])
        with patch.object(cycle_report, 'render_html', wraps=cycle_report.render_html) as renderer, \
                patch.object(cycle_report, '_write_current_summaries',
                             side_effect=OSError('summary blocked')):
            with self.assertRaises(ReportDegraded):
                write_reports(summary_failure, failed_summary_campaign)
        self.assertEqual(renderer.call_count, 1)
        self.assertTrue((summary_failure / 'CYCLE_REVIEW_REPORT.html').is_file())
        self.assertEqual(failed_summary_campaign['report']['state'], 'READY')
        self.assertEqual(failed_summary_campaign['report']['summary_state'], 'FAILED')
        persisted = read_journal(summary_failure)
        self.assertEqual(persisted['report']['state'], 'READY')
        self.assertEqual(persisted['report']['summary_state'], 'FAILED')
        run_status_data = json.loads(
            (summary_failure / 'run_status.json').read_text(encoding='utf-8'))
        self.assertEqual(run_status_data['report']['state'], 'READY')
        self.assertEqual(run_status_data['report']['summary_state'], 'FAILED')

        # Replacing the two current-state text files is all-or-rollback.  A
        # failure on the second replace cannot leave a mixed summary pair.
        rollback = self.root / 'summary-rollback'
        rollback.mkdir()
        summary_path = rollback / 'cycle_summary.txt'
        markdown_path = rollback / 'CYCLE_REVIEW_REPORT.md'
        summary_path.write_text('old summary\n', encoding='utf-8')
        markdown_path.write_text('old markdown\n', encoding='utf-8')
        real_atomic_write = cycle_report.atomic_write

        def fail_first_markdown(path, text):
            if Path(path).name == 'CYCLE_REVIEW_REPORT.md':
                raise OSError('markdown replace blocked')
            return real_atomic_write(path, text)

        with patch.object(cycle_report, 'atomic_write', side_effect=fail_first_markdown):
            with self.assertRaises(OSError):
                cycle_report._write_current_summaries(rollback, rebuilt)
        self.assertEqual(summary_path.read_text(encoding='utf-8'), 'old summary\n')
        self.assertEqual(markdown_path.read_text(encoding='utf-8'), 'old markdown\n')

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

    def test_continuous_hostname_card_retains_changed_actual_values(self):
        records = []
        for number, actual in ((1, 'wrong-A'), (2, 'wrong-B')):
            record = new_record(f'LOOP {number}')
            record.update(loop=number, post_complete=True, issues=[
                issue('HOSTNAME_MISMATCH', 'os',
                      f"os hostname mismatch: inventory says 'os-n1', host reports '{actual}'")
            ])
            record['identities']['os'] = {'hostname': actual, 'boot_id': '0' * 36}
            records.append(record)
        items = merge_issues(aggregate_issues(complete_campaign([report_node(records=records)])))
        page = issue_cards_compact(items, {'tray1_n1': 0})
        self.assertEqual(page.count('class="issue-row"'), 1)
        self.assertIn('wrong-A', page)
        self.assertIn('wrong-B', page)

    def test_synthetic_four_node_280_loop_report_is_complete_html(self):
        nodes = []
        for node_number in range(1, 5):
            records = []
            for number in range(1, 281):
                record = new_record(f'LOOP {number}')
                expected = f'os-n{node_number}'
                boot_id = f'{node_number:08d}-0000-0000-0000-{number:012d}'
                trace = [
                    {
                        'role': 'os', 'stage': f'identity_{check}',
                        'expected': expected,
                        'actual': (f'wrong-{node_number}-{number}-{check}'
                                   if check < 5 else expected),
                        'result': 'MISMATCH' if check < 5 else 'MATCH',
                    }
                    for check in range(1, 6)
                ]
                bdf = f'0000:{node_number:02d}:00.0'
                dmesg = dmesg_issues(
                    f'[ 10.0] pcieport {bdf}: I/O 1 failed\n'
                    f'[ 11.0] pcieport {bdf}: I/O 2 failed\n'
                )
                for event in dmesg:
                    event.update(boot_id=boot_id, phase='dmesg_clear',
                                 evidence=f'loops/{number}/dmesg_clear.txt')
                hostname = issue(
                    'HOSTNAME_MISMATCH', 'os',
                    f"os hostname mismatch: inventory says '{expected}', "
                    f"host reports 'wrong-{node_number}-{number}-1'",
                )
                redfish = redfish_finding(
                    'FAIL' if ((number - 1) // 20) % 2 else 'WARN',
                    event_id=f'{node_number}-{number}',
                    message='stress | supply fault',
                )
                record.update(
                    loop=number, status='FAIL', post_complete=True,
                    valid_cycle=True, finished='2026-10-24T00:01:00+08:00',
                    duration_seconds=.1, issues=[hostname, *dmesg, redfish],
                    identity_observations=trace,
                )
                record['identities']['os'] = {'hostname': expected, 'boot_id': boot_id}
                record['redfish_delta_ids'] = [f'EventLog|{node_number}-{number}']
                record['observation_status'].update(
                    dmesg='AVAILABLE', eventlog='AVAILABLE')
                records.append(record)
            nodes.append(report_node(f'tray1_n{node_number}', records))
        page = render_html(complete_campaign(nodes))
        self.assertTrue(page.startswith('<!doctype html>'))
        self.assertTrue(page.rstrip().endswith('</html>'))
        self.assertIn('SYNTHETIC DEMONSTRATION', page)
        self.assertIn('LOOP 280', page)
        self.assertIn('wrong-4-280-4', page)
        self.assertIn('(20 distinct IDs)', page)
        self.assertIn('I/O 1 failed', page)
        self.assertIn('I/O 2 failed', page)
        self.assertEqual(page.count('class="node-panel"'), 4)
        self.assertIn('Issues (12)', page)
        # The same 12 cards appear in Overview and the filterable Issues tab.
        self.assertEqual(page.count('class="issue-row"'), 24)
        self.assertLess(len(page.encode('utf-8')), 12 * 1024 * 1024)


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
