"""Unclassified dmesg error/fail lines must not vanish, and must not flood.

Real evidence: on the Vera CPU rack a boot capture held 103 error/fail lines
but the parser surfaced only one (an APEI corrected event). 92 lines were
silently dropped -- PCI io-window ``failed to assign``, ipmi_ssif probe
failures, tegra-bpmp debugfs, mlx_compat taint. These tests pin the fallback
sweep that collects them into one bundle, with IPMI transport failures
reported as FAIL because a broken SSIF makes ``ipmitool`` unusable.
"""
import unittest

from vera_cycle.core.cycle_core import (classify_against_pre, dmesg_issues, display_component, health,
                        issue_baseline)
from vera_cycle.reporting.cycle_report import _dmesg_package_html, _finding_html, _finding_html_compact

BOOT = '\n'.join([
    '[   11.87] pci 0001:00:00.0: bridge window [io  size 0x1000]: failed to assign',
    '[   11.87] pci 0002:02:00.0: BAR 2 [io  size 0x0080]: failed to assign',
    '[   11.86] PCI: OF: of_root node is NULL, cannot create PCI host bridge node',
    '[   15.45] tegra-bpmp NVDA3001:00: debugfs initialization failed: -27',
    '[   26.34] ipmi_ssif dmi-ipmi-ssif.1: probe with driver ipmi_ssif failed with error -17',
    '[   26.62] ipmi_si: Unable to find any System Interface(s)',
    '[   41.76] ipmi_ssif i2c-IPI0001:00: ipmi_ssif: Error fetching SSIF: -121 0 00, your system probably doesn\'t support this command so using defaults',
    '[   57.03] ipmi_ssif i2c-IPI0001:00: ipmi_ssif: Unable to clear message flags: 0 3 c1',
    '[   72.28] ipmi_ssif i2c-IPI0001:00: ipmi_ssif: Error getting global enables: -121 0 00',
    '[   28.00] mlx_compat: module verification failed: signature and/or required key missing - tainting kernel',
])


def by_code(items):
    return {item['code']: item for item in items}


class BundleTests(unittest.TestCase):
    def test_unclassified_lines_are_one_finding_not_many(self):
        items = dmesg_issues(BOOT)
        self.assertEqual(sorted(by_code(items)), ['DMESG_BUNDLE'])
        bundle = by_code(items)['DMESG_BUNDLE']
        texts = '\n'.join(e['text'] for e in bundle['entries'])
        self.assertIn('failed to assign', texts)
        self.assertIn('BAR 2', texts)
        self.assertIn('PCI: OF: of_root node is NULL', texts)
        self.assertIn('tegra-bpmp', texts)
        self.assertIn('mlx_compat', texts)

    def test_ipmi_transport_failure_is_fail(self):
        items = dmesg_issues(BOOT)
        bundle = by_code(items)['DMESG_BUNDLE']
        self.assertEqual(bundle['severity'], 'FAIL')
        self.assertEqual(health(items), 'FAIL')
        texts = '\n'.join(e['text'] for e in bundle['entries'])
        for needle in ('probe with driver ipmi_ssif failed',
                       'Unable to find any System Interface',
                       'Error fetching SSIF', 'Unable to clear message flags',
                       'Error getting global enables'):
            self.assertIn(needle, texts)

    def test_bundle_is_fail_when_ipmi_is_healthy(self):
        # Everything is FAIL for now; the operator adds a per-project allowlist
        # of known-benign lines later rather than the parser pre-judging them.
        benign = '\n'.join(line for line in BOOT.splitlines() if 'ipmi' not in line and 'tegra-bpmp' not in line)
        bundle = by_code(dmesg_issues(benign))['DMESG_BUNDLE']
        self.assertEqual(bundle['severity'], 'FAIL')
        self.assertEqual(health(dmesg_issues(benign)), 'FAIL')

    def test_normal_initialization_is_not_an_error(self):
        text = '\n'.join([
            'nvme nvme0: Shutdown timeout set to 10 seconds',
            'CPU features: detected: WFx with timeout',
            'sbsa-gwdt sbsa-gwdt.0: Initialized with 10s timeout @ 1000000000 Hz, action=0.',
            'AER: enabled error reporting',
            '0 errors',
        ])
        self.assertEqual(dmesg_issues(text), [])

    def test_known_family_lines_are_not_double_counted(self):
        aer = ('[ 1.0] PCIe Bus Error: severity=Uncorrected (Fatal), type=Physical\n'
               '[ 1.1] pcieport 0001:00:00.0: AER: error status/mask=00000004/00002000\n')
        codes = [item['code'] for item in dmesg_issues(aer)]
        self.assertIn('DMESG_PCIE', codes)
        self.assertNotIn('DMESG_BUNDLE', codes)

    def test_genuine_device_errors_are_not_treated_as_benign(self):
        # A bare nvme/mlx5/NVRM token used to sit in the benign list as a family
        # "continuation anchor", which silently dropped real device errors no
        # strict pattern claimed. Only true AER continuation markers may remain.
        for line, code in [('mlx5_core 0001:01:00.0: mlx5_cmd_check timeout', 'DMESG_BUNDLE'),
                           ('mlx5_core 0001:01:00.0: driver failed to load', 'DMESG_BUNDLE'),
                           ('nvme nvme0: I/O 12 QID 1 timeout, aborting', 'DMESG_NVME'),
                           ('nvme nvme0: controller is down; will reset', 'DMESG_NVME')]:
            with self.subTest(line=line):
                codes = [item['code'] for item in dmesg_issues(line)]
                self.assertIn(code, codes)
        # The benign normal-initialisation line is still dropped.
        self.assertEqual(dmesg_issues('nvme nvme0: Shutdown timeout set to 10 seconds'), [])

    def test_bundle_keeps_distinct_device_addresses(self):
        # Two cards logging the same failure text are two findings. Masking the
        # BDF in the dedup key hid the second card entirely.
        text = '\n'.join([
            '[ 1.0] mlx5_core 0001:01:00.0: mlx5_cmd_check timeout',
            '[ 1.1] mlx5_core 0002:01:00.0: mlx5_cmd_check timeout',
        ])
        bundle = by_code(dmesg_issues(text))['DMESG_BUNDLE']
        self.assertEqual(len(bundle['entries']), 2)
        texts = '\n'.join(e['text'] for e in bundle['entries'])
        self.assertIn('0001:01:00.0', texts)
        self.assertIn('0002:01:00.0', texts)

    def test_bundle_fingerprint_ignores_device_addresses(self):
        # The fingerprint keys the PRE comparison. It must not change when boot
        # re-enumerates BDFs, or a pre-existing bundle would be NEW every run.
        pre = dmesg_issues('pci 0001:00:00.0: BAR 2 [io size 0x0080]: failed to assign')
        same = dmesg_issues('pci 0001:00:00.0: BAR 2 [io size 0x0080]: failed to assign')
        moved = dmesg_issues('pci 0009:00:00.0: BAR 2 [io size 0x0080]: failed to assign')
        self.assertEqual(pre[0]['fingerprint'], same[0]['fingerprint'])
        self.assertEqual(pre[0]['fingerprint'], moved[0]['fingerprint'])
        self.assertEqual(classify_against_pre(moved, issue_baseline(pre))[0]['classification'], 'KNOWN')
        fresh = dmesg_issues('nvme0: probe failed -19')
        self.assertEqual(classify_against_pre(fresh, issue_baseline(pre))[0]['classification'], 'NEW')

    def test_display_component_labels_bundle_only(self):
        bundle = by_code(dmesg_issues('ipmi_ssif probe failed -17'))['DMESG_BUNDLE']
        self.assertEqual(display_component(bundle), 'fail/error')
        for item in dmesg_issues('PCIe Bus Error: severity=Uncorrectable (Fatal)'):
            self.assertEqual(display_component(item), 'pcie')
        apei = dmesg_issues('[ 1.0] {1}[Hardware Error]: Hardware error from APEI Generic Hardware Error Source: 8194\n'
                            '[ 1.1] {1}[Hardware Error]: event severity: fatal\n'
                            '[ 1.2] {1}[Hardware Error]: device: 0000:01:00.0\n')[0]
        self.assertEqual(display_component(apei), '0000:01:00.0')

    def test_dmesg_package_html_survives_every_capture_shape(self):
        # bundle=None must not be dereferenced (APEI-only captures), and the
        # card renderers must accept the same shapes.
        apei = dmesg_issues('[ 1.0] {1}[Hardware Error]: Hardware error from APEI Generic Hardware Error Source: 8194\n'
                            '[ 1.1] {1}[Hardware Error]: event severity: fatal\n'
                            '[ 1.2] {1}[Hardware Error]: device: 0000:01:00.0\n')
        bundle = dmesg_issues('ipmi_ssif probe failed -17')
        for issues in ([], apei, bundle, apei + bundle):
            with self.subTest(count=len(issues)):
                b = next((i for i in issues if i['code'] == 'DMESG_BUNDLE'), None)
                a = [i for i in issues if i['code'] == 'DMESG_APEI']
                self.assertIn('dmesg', _dmesg_package_html(b, a))
                record = dict(phase='LOOP 1', issues=issues)
                for rendered in (_finding_html(record), _finding_html_compact(record)):
                    # No issues is a benign empty card, not a crash and not a claim.
                    self.assertTrue('record-issues' in rendered or 'No issues recorded' in rendered)
