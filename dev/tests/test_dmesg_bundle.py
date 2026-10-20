"""Unclassified dmesg error/fail lines must not vanish, and must not flood.

Real evidence: on the Vera CPU rack a boot capture held 103 error/fail lines
but the parser surfaced only one (an APEI corrected event). 92 lines were
silently dropped -- PCI io-window ``failed to assign``, ipmi_ssif probe
failures, tegra-bpmp debugfs, mlx_compat taint. These tests pin the fallback
sweep that collects them into one bundle, with IPMI transport failures
reported as FAIL because a broken SSIF makes ``ipmitool`` unusable.
"""
import unittest

from cycle_core import dmesg_issues, health

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
