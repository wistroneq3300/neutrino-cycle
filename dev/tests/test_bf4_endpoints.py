"""Offline regressions for the BF4 DPU OS / BMC post-reboot check.

No SSH, network or hardware access: the transport is faked, and the settle
window is driven by an injected clock so the tests do not actually wait.
"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import tempfile as _tempfile
import os
os.environ.setdefault('VERA_CAMPAIGN_TMP', _tempfile.mkdtemp(prefix='vera-campaign-tmp-'))

from vera_cycle import paths
from vera_cycle.core.cycle_core import Target, parse_policy
from vera_cycle.core.cycle_transport import Command, IdentityTransient, IdentityUnsafe
from vera_cycle.engine import cycle_engine
from vera_cycle.engine.cycle_engine import NodeSession, new_record
from vera_cycle.reporting.cycle_report import _render_bf4_group

DPU_BOOT = '11111111-2222-3333-4444-555555555555'
BMC_BOOT = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'


def bf4_target():
    return Target('tray1', 'n1', '192.0.2.1', '192.0.2.2', 'bmc-n1', 'os-n1',
                  bf4_os_ip='192.0.2.101', bf4_bmc_ip='192.0.2.102',
                  bf4_os_hostname='Neutrino1-n1', bf4_bmc_hostname='Neutrino1-n1')


class FakeBf4Transport:
    """Answers only for the BF4 roles, and only when told to be up."""

    def __init__(self, up=('bf4_os', 'bf4_bmc'), hostname='localhost.localdomain',
                 boot_ids=None, open_ports=(22,)):
        self.up = set(up)
        self.hostname = hostname
        self.boot_ids = boot_ids or {'bf4_os': DPU_BOOT, 'bf4_bmc': BMC_BOOT}
        self.open_ports = list(open_ports)
        self.calls = []
        self.probed = []

    def ssh(self, t, role, cmd, timeout=60, sudo=False):
        self.calls.append((role, cmd))
        if role not in self.up:
            raise ConnectionError(f'{role} refused')
        boot = self.boot_ids.get(role, '')
        return Command(0, f'HOSTNAME={self.hostname}\nBOOT_ID={boot}\n')

    def tcp_probe(self, t, role, ports=(22, 443), timeout=5):
        self.probed.append(role)
        return self.open_ports

    def oob(self, t, cmd, timeout=30):
        raise AssertionError('BF4 check must not touch IPMI')


class Bf4EndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.options = SimpleNamespace(
            project='neutrino', bf4_settle_timeout=120, bf4_fail_confirmations=2,
            issue_policy=paths.ISSUE_POLICY)

    def tearDown(self):
        self.temp.cleanup()

    def session(self, transport):
        return NodeSession(bf4_target(), transport, self.root, 'test', b'script', 'hash',
                           self.options, parse_policy(self.options.issue_policy.read_text()))

    def test_no_bf4_endpoints_means_no_check(self):
        plain = Target('tray1', 'n1', '192.0.2.1', '192.0.2.2', 'bmc-n1', 'os-n1')
        session = NodeSession(plain, FakeBf4Transport(), self.root, 'test', b's', 'h',
                              self.options, [])
        record = new_record('LOOP 1')
        session.check_bf4_endpoints(record)
        self.assertEqual(record['bf4'], {})
        self.assertEqual(record['issues'], [])

    def test_reachable_card_passes_without_complaint(self):
        transport = FakeBf4Transport()
        session = self.session(transport)
        record = new_record('LOOP 1')
        session.check_bf4_endpoints(record)
        self.assertTrue(record['bf4']['bf4_os']['reachable'])
        self.assertTrue(record['bf4']['bf4_bmc']['reachable'])
        self.assertEqual(record['issues'], [])

    def test_dpu_hostname_is_not_compared(self):
        # The DPU reports localhost.localdomain and the BMC dpu-bmc; neither can
        # match the inventory name, and neither may be reported as a mismatch.
        session = self.session(FakeBf4Transport(hostname='localhost.localdomain'))
        record = new_record('LOOP 1')
        session.check_bf4_endpoints(record)
        self.assertEqual([i for i in record['issues'] if i['code'] == 'HOSTNAME_MISMATCH'], [])
        self.assertEqual(record['bf4']['bf4_os']['hostname'], 'localhost.localdomain')

    def test_first_unreachable_loop_is_only_a_warning(self):
        transport = FakeBf4Transport(up=())
        session = self.session(transport)
        record = new_record('LOOP 1')
        session.check_bf4_endpoints(record)
        issues = [i for i in record['issues'] if i['code'] == 'BF4_ENDPOINT_UNREACHABLE']
        self.assertEqual(len(issues), 2)
        self.assertTrue(all(i['severity'] == 'WARN' for i in issues))
        self.assertEqual(session.node['bf4_failures']['bf4_os'], 1)

    def test_second_consecutive_loop_fails(self):
        transport = FakeBf4Transport(up=())
        session = self.session(transport)
        session.check_bf4_endpoints(new_record('LOOP 1'))
        record = new_record('LOOP 2')
        session.check_bf4_endpoints(record)
        issues = [i for i in record['issues'] if i['code'] == 'BF4_ENDPOINT_UNREACHABLE']
        self.assertTrue(all(i['severity'] == 'FAIL' for i in issues))
        self.assertEqual(session.node['bf4_failures']['bf4_os'], 2)

    def test_a_pass_resets_the_consecutive_counter(self):
        session = self.session(FakeBf4Transport(up=()))
        session.check_bf4_endpoints(new_record('LOOP 1'))
        self.assertEqual(session.node['bf4_failures']['bf4_os'], 1)
        session.transport = FakeBf4Transport()          # card came back
        session.check_bf4_endpoints(new_record('LOOP 2'))
        self.assertEqual(session.node['bf4_failures']['bf4_os'], 0)

    def test_unreachable_records_listening_ports(self):
        transport = FakeBf4Transport(up=(), open_ports=[])
        session = self.session(transport)
        record = new_record('LOOP 1')
        session.check_bf4_endpoints(record)
        self.assertEqual(record['bf4']['bf4_os']['open_ports'], [])
        self.assertIn('none', [i for i in record['issues']
                               if i['code'] == 'BF4_ENDPOINT_UNREACHABLE'][0]['detail'])

    def test_transient_auth_is_retried_not_fatal(self):
        class Flaky(FakeBf4Transport):
            def __init__(self):
                super().__init__()
                self.n = 0

            def ssh(self, t, role, cmd, timeout=60, sudo=False):
                self.n += 1
                if self.n == 1:
                    raise IdentityTransient(f'{role}: authentication failed')
                return super().ssh(t, role, cmd, timeout, sudo)

        session = self.session(Flaky())
        record = new_record('LOOP 1')
        with patch.object(cycle_engine.time, 'sleep'):
            session.check_bf4_endpoints(record)
        self.assertTrue(record['bf4']['bf4_os']['reachable'])
        self.assertGreaterEqual(record['bf4']['bf4_os']['attempts'], 2)

    def test_bad_host_key_still_stops_the_node(self):
        class BadKey(FakeBf4Transport):
            def ssh(self, t, role, cmd, timeout=60, sudo=False):
                raise IdentityUnsafe(f'{role}: SSH host key validation failed')

        session = self.session(BadKey())
        with self.assertRaises(IdentityUnsafe):
            session.check_bf4_endpoints(new_record('LOOP 1'))

    def test_missing_boot_id_is_a_warning_not_a_stop(self):
        transport = FakeBf4Transport(boot_ids={'bf4_os': 'not-a-boot-id', 'bf4_bmc': BMC_BOOT})
        session = self.session(transport)
        record = new_record('LOOP 1')
        session.check_bf4_endpoints(record)
        codes = [i['code'] for i in record['issues']]
        self.assertIn('BF4_BOOT_ID_UNAVAILABLE', codes)
        self.assertTrue(record['bf4']['bf4_os']['reachable'])


class Bf4ReportTests(unittest.TestCase):
    def test_healthy_card_renders_nothing(self):
        record = new_record('LOOP 1')
        record['bf4'] = {'bf4_os': {'reachable': True, 'seconds': 5.9},
                         'bf4_bmc': {'reachable': True, 'seconds': 5.9}}
        self.assertEqual(_render_bf4_group(record), '')

    def test_failing_card_renders_a_block(self):
        record = new_record('LOOP 1')
        record['bf4'] = {'bf4_os': {'reachable': False, 'seconds': 120, 'attempts': 12,
                                    'last_error': 'ConnectionError: refused', 'open_ports': []}}
        record['issues'].append(dict(code='BF4_ENDPOINT_UNREACHABLE', component='bf4_os',
                                     detail='no answer', severity='FAIL', evidence='', snippet=''))
        html = _render_bf4_group(record)
        self.assertIn('BF4 DPU / BMC after reboot', html)
        self.assertIn('bf4_os', html)

    def test_no_bf4_data_renders_nothing(self):
        self.assertEqual(_render_bf4_group(new_record('LOOP 1')), '')


if __name__ == '__main__':
    unittest.main()
