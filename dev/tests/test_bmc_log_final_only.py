"""final-only BMC logging: one read at the end, attributed to loops by time."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import test_cycle as fixtures
from vera_cycle import paths
from vera_cycle.core import cycle_bmclog as bmclog
from vera_cycle.core.cycle_core import aggregate_issues, health, parse_policy
from vera_cycle.core.cycle_transport import Command
from vera_cycle.engine.cycle_engine import NodeSession


class BmcLogPureTests(unittest.TestCase):
    def test_windows_skip_loops_without_both_boundaries(self):
        loops = [
            {'loop': 1, 'loop_window_start': '2026-10-31T02:00:00+08:00',
             'loop_window_end': '2026-10-31T02:10:00+08:00'},
            {'loop': 2, 'loop_window_start': None, 'loop_window_end': '2026-10-31T02:20:00+08:00'},
            {'loop': 3, 'loop_window_start': '2026-10-31T02:20:00+08:00'},
        ]
        self.assertEqual([number for number, _, _ in bmclog.windows(loops)], [1])

    def test_entry_outside_every_window_is_kept_unattributed(self):
        spans = bmclog.windows([{'loop': 1, 'loop_window_start': '2026-10-31T02:00:00+08:00',
                                 'loop_window_end': '2026-10-31T02:10:00+08:00'}])
        tagged = bmclog.attribute([{'id': '9', 'created': '2026-10-31T05:00:00+08:00'}], spans)
        self.assertEqual(len(tagged), 1)
        self.assertIsNone(tagged[0]['loop'])

    def test_unparsable_timestamp_is_not_assigned_to_a_loop(self):
        spans = bmclog.windows([{'loop': 1, 'loop_window_start': '2026-10-31T02:00:00+08:00',
                                 'loop_window_end': '2026-10-31T02:10:00+08:00'}])
        tagged = bmclog.attribute([{'id': '3', 'created': 'not a time'}], spans)
        self.assertIsNone(tagged[0]['loop'])

    def test_offset_aware_timestamp_matches_window_in_another_zone(self):
        # The window is written in +08:00, the entry in Z. The same instant
        # must still match, or every BMC-UTC entry would look unattributed.
        spans = bmclog.windows([{'loop': 4, 'loop_window_start': '2026-10-31T02:00:00+08:00',
                                 'loop_window_end': '2026-10-31T02:10:00+08:00'}])
        tagged = bmclog.attribute([{'id': '7', 'created': '2026-10-30T18:05:00Z'}], spans)
        self.assertEqual(tagged[0]['loop'], 4)

    def test_severity_counts_and_worst(self):
        entries = [{'severity': 'Critical'}, {'severity': 'Warning'}, {'severity': 'OK'}]
        self.assertEqual(bmclog.severity_counts(entries),
                         {'Critical': 1, 'Warning': 1, 'OK': 1, 'Other': 0})
        self.assertEqual(bmclog.worst(entries), 'FAIL')
        self.assertEqual(bmclog.worst([{'severity': 'Warning'}]), 'WARN')
        self.assertEqual(bmclog.worst([{'severity': 'OK'}]), 'PASS')

    def test_sel_rows_become_entries_with_a_real_time(self):
        text = ('   1 | 10/30/2026 | 18:05:00 | Power Unit #0x01 | Power off/down | Asserted\n'
                '   2 | 10/30/2026 | 18:06:00 | Power Unit #0x01 | Power off/down | Deasserted\n'
                'not a row\n')
        entries = bmclog.parse_sel_entries(text)
        self.assertEqual([entry['id'] for entry in entries], ['1', '2'])
        # 18:05 at UTC+8 is 10:05 UTC.
        self.assertEqual(entries[0]['created'], '2026-10-30T10:05:00+00:00')

    def test_unparsable_sel_row_is_dropped_not_invented(self):
        self.assertEqual(bmclog.parse_sel_entries('   1 | 99/99/9999 | 18:05:00 | x'), [])

    def test_sel_severity_is_derived_from_the_row_text(self):
        # `ipmitool sel list` has no severity column, so the text decides.
        cases = {
            'Processor #0x01 | IERR | Asserted': ('Critical', 'critical'),
            'Memory | Uncorrectable ECC | Asserted': ('Critical', 'critical'),
            'Temperature #0x02 | Upper non-critical going high | Asserted': ('Warning', 'warning'),
            'Processor #0x01 | IERR | Deasserted': ('', ''),
            'Power Unit #0x01 | Power off/down | Asserted': ('', ''),
            'OEM | vendor specific | Asserted': ('', ''),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(bmclog.sel_severity(text), expected)

    def test_critical_keyword_outranks_warning_keyword(self):
        # A row naming both must be the worse of the two, not whichever the
        # pattern happens to match first.
        self.assertEqual(bmclog.sel_severity('Device | uncorrectable threshold | Asserted'),
                         ('Critical', 'critical'))


class FinalOnlySessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.options = SimpleNamespace(
            project='neutrino', cycle_mode='power_cycle', channel='inband',
            boot_timeout=.03, poll_interval=.001, loops=2, hours=0, cycle=True,
            config_script=paths.project_config_path('neutrino'),
            issue_policy=paths.ISSUE_POLICY, output=self.root / 'output',
            sensor_retry_delay=0, bmc_log_mode='final-only')
        self.fake = fixtures.FakeTransport({}, self.root / 'ssh')
        self.session = NodeSession(fixtures.target(), self.fake, self.root, 'test', b'script',
                                   fixtures.digest(b'script'), self.options,
                                   parse_policy(self.options.issue_policy.read_text()))

    def tearDown(self):
        self.temp.cleanup()

    def test_per_loop_reads_are_skipped_in_final_only_mode(self):
        self.assertTrue(self.session.final_only)
        self.session.precheck()
        self.assertFalse(self.session.node['blocked'])
        self.session.start()
        self.fake.calls.clear()
        self.session.one_loop(1)
        reads = [call for call in self.fake.calls if call[1] == 'redfish']
        sels = [call for call in self.fake.calls if call[1] == 'oob' and 'sel' in str(call[2])]
        self.assertEqual(reads, [])
        self.assertEqual(sels, [])
        loop = self.session.node['loops'][0]
        self.assertIn('loop_window_start', loop)
        self.assertIn('loop_window_end', loop)

    def test_final_read_attributes_entries_to_their_loop(self):
        self.session.precheck()
        self.session.start()
        first = self.session.one_loop(1)
        self.session.one_loop(2)
        # An entry stamped inside loop 1's own window belongs to loop 1. The
        # window is read back from the record rather than assumed, because
        # this fixture's loops complete within the same second.
        start = bmclog.parse_time(first['loop_window_start'])
        self.assertIsNotNone(start)
        inside = start.astimezone(timezone.utc).isoformat()

        original = self.fake.redfish_get

        def redfish_get(target, path, token, timeout=30):
            if path.endswith('/EventLog/Entries'):
                return Command(0, json.dumps({'Members': [
                    {'Id': '11', 'Severity': 'Critical', 'Created': inside, 'Message': 'boom'},
                ]}))
            return original(target, path, token, timeout)

        self.fake.redfish_get = redfish_get
        self.session.final_bmc_logs()
        final = self.session.node['final']
        self.assertTrue(final['bmc_log_final']['collected'])
        attributed = {entry['id']: entry['loop'] for entry in final['bmc_log_final']['eventlog']}
        self.assertEqual(attributed['11'], 1)
        self.assertEqual(final['bmc_log_final']['sudden_counts']['Critical'], 1)
        hints = [item.get('loop_hint') for item in final['issues'] if item['code'] == 'REDFISH_CRITICAL']
        self.assertEqual(hints, [1])

    def test_final_read_failure_is_never_pass(self):
        self.session.precheck()
        self.session.start()
        self.session.one_loop(1)
        self.fake.redfish_fail = True
        self.session.final_bmc_logs()
        final = self.session.node['final']
        self.assertFalse(final['bmc_log_final']['collected'])
        codes = [item['code'] for item in final['issues']]
        self.assertIn('BMC_LOG_UNAVAILABLE', codes)

    def test_evidence_files_are_written_once_per_node(self):
        self.session.precheck()
        self.session.start()
        self.session.one_loop(1)
        self.session.final_bmc_logs()
        final = self.session.node['final']
        eventlog = self.root / final['bmc_log_final']['evidence_eventlog']
        sel = self.root / final['bmc_log_final']['evidence_sel']
        self.assertTrue(eventlog.is_file())
        self.assertTrue(sel.is_file())

    def test_loop_time_window_is_written_in_campaign_clock(self):
        self.session.precheck()
        self.session.start()
        loop = self.session.one_loop(1)
        start = bmclog.parse_time(loop['loop_window_start'])
        end = bmclog.parse_time(loop['loop_window_end'])
        self.assertIsNotNone(start)
        self.assertIsNotNone(end)
        self.assertLessEqual(start, end)

    def test_bmc_without_a_sel_service_is_not_a_finding(self):
        # This platform's BMCs merge SEL into the EventLog. A missing SEL must
        # stay quiet, or every campaign on this hardware would report a fault
        # that does not exist.
        self.session.precheck()
        self.session.start()
        self.session.one_loop(1)
        self.session.final_bmc_logs()
        final = self.session.node['final']
        self.assertFalse([item for item in final['issues']
                          if item['code'] in ('SEL_CRITICAL', 'SEL_WARNING', 'BMC_LOG_UNAVAILABLE')
                          and item['component'] == 'sel'])

    def test_sel_ierr_becomes_a_fail_finding_with_evidence(self):
        # A platform that does expose SEL: the IERR row must reach the issue
        # list with its own evidence file, exactly like an EventLog Critical.
        self.session.precheck()
        self.session.start()
        first = self.session.one_loop(1)
        stamp = bmclog.parse_time(first['loop_window_start']).astimezone(timezone.utc)
        local = stamp.astimezone(bmclog.BMC_TIMEZONE)
        row = (f" 7 | {local.month}/{local.day}/{local.year} | "
               f"{local.hour:02d}:{local.minute:02d}:{local.second:02d} | "
               "Processor #0x01 | IERR | Asserted\n")
        original = self.fake.oob

        def oob(target, cmd, timeout=30):
            return Command(0, row) if cmd == 'sel list' else original(target, cmd, timeout)

        self.fake.oob = oob
        self.fake.redfish_sel_present = True
        self.session.final_bmc_logs()
        final = self.session.node['final']
        sel_items = [item for item in final['issues'] if item['code'] == 'SEL_CRITICAL']
        self.assertEqual(len(sel_items), 1)
        self.assertEqual(sel_items[0]['severity'], 'FAIL')
        self.assertEqual(sel_items[0]['evidence'], 'tray1_n1/bmc_log/bmc_sel_final.txt')
        self.assertEqual(sel_items[0]['loop_hint'], 1)


if __name__ == '__main__':
    unittest.main()
