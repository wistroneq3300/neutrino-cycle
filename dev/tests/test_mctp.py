"""Offline tests for the P5032 MCTP / BMC USB parsing and judgement."""
import unittest

from cycle_core import (
    bmc_usb_issues,
    mctp_check_issues,
    mctp_stress_issues,
    parse_bmc_lsusb,
    parse_mctp_stressor,
)

# Real content captured from the BMC's `lsusb -tv` (device lines trimmed).
BMC_USB_TREE = """unable to initialize usb spec/:  Bus 001.Port 001: Dev 001, Class=root_hub, Driver=ehci-platform/1p, 480M
    ID 1d6b:0002
    |__ Port 001: Dev 002, If 0, Class=[unknown], Driver=hub/4p, 480M
        ID 0424:2514
        |__ Port 002: Dev 004, If 0, Class=[unknown], Driver=hub/4p, 480M
            ID 0424:2514
            |__ Port 001: Dev 010, If 2, Class=[unknown], Driver=mctp-usb, 480M
                ID 0955:7410
            |__ Port 002: Dev 011, If 2, Class=[unknown], Driver=mctp-usb, 480M
                ID 0955:7410
        |__ Port 003: Dev 005, If 0, Class=[unknown], Driver=mctp-usb, 480M
            ID 0955:cf11
"""

PREFLIGHT = """P5032 CPU0 / EID 16: 10 loops plus baseline; timeout 10s
pldmd.service state: active
Preflight passed. No PLDM requests sent or service state changed.
"""

STRESS_OK = """Capturing baseline GetFirmwareParameters response
PASS iteration=1/10
PASS iteration=2/10
SUMMARY cpu=CPU0 eid=16 attempted=10 passed=10 failed=0
Restoring pldmd.service
"""

STRESS_FAIL = """Capturing baseline GetFirmwareParameters response
PASS iteration=1/10
FAIL iteration=2/10: response differs from baseline
PASS iteration=3/10
SUMMARY cpu=CPU1 eid=17 attempted=10 passed=9 failed=1
Restoring pldmd.service
"""


class BmcLsusbTests(unittest.TestCase):
    def test_parses_port_path_and_vid_pid(self):
        rows = parse_bmc_lsusb(BMC_USB_TREE)
        self.assertIn('001-1.2.1 0955:7410', rows)
        self.assertIn('001-1.2.2 0955:7410', rows)
        self.assertIn('001-1.3 0955:cf11', rows)
        self.assertEqual(rows['001-1.2.1 0955:7410']['path'], '001-1.2.1')

    def test_root_hub_device_without_port(self):
        self.assertIn('001 1d6b:0002', parse_bmc_lsusb(BMC_USB_TREE))

    def test_drift_only_reports_pre_present_absent(self):
        pre = parse_bmc_lsusb(BMC_USB_TREE)
        current = {k: v for k, v in pre.items() if '0955:7410' not in k}
        found = bmc_usb_issues(pre, current)
        self.assertEqual({i['code'] for i in found}, {'BMC_USB_DRIFT'})
        self.assertEqual(len(found), 2)

    def test_added_endpoint_is_not_a_finding(self):
        pre = parse_bmc_lsusb(BMC_USB_TREE)
        current = dict(pre)
        current['001-1.9 0955:9999'] = dict(path='001-1.9', id='0955:9999', raw='ID 0955:9999', description='')
        self.assertEqual(bmc_usb_issues(pre, current), [])


class MctpStressorParseTests(unittest.TestCase):
    def test_preflight_is_check_kind(self):
        verdict = parse_mctp_stressor(PREFLIGHT)
        self.assertEqual(verdict['kind'], 'check')

    def test_stress_summary_is_parsed(self):
        verdict = parse_mctp_stressor(STRESS_OK)
        self.assertEqual(verdict['kind'], 'stress')
        self.assertEqual((verdict['attempted'], verdict['passed'], verdict['failed']), (10, 10, 0))

    def test_failing_iterations_are_listed(self):
        verdict = parse_mctp_stressor(STRESS_FAIL)
        self.assertEqual(verdict['failed'], 1)
        self.assertEqual(verdict['failures'], ['2/10'])


class MctpJudgementTests(unittest.TestCase):
    def test_preflight_pass(self):
        self.assertEqual(mctp_check_issues(16, '0', PREFLIGHT, 0), [])

    def test_preflight_fail_on_nonzero_exit(self):
        found = mctp_check_issues(16, '0', PREFLIGHT, 1)
        self.assertEqual([i['code'] for i in found], ['MCTP_CHECK_FAIL'])

    def test_preflight_fail_without_passed_marker(self):
        found = mctp_check_issues(16, '0', 'EID 16 is absent, ambiguous, or not USB.\n', 2)
        self.assertEqual([i['code'] for i in found], ['MCTP_CHECK_FAIL'])

    def test_stress_pass(self):
        self.assertEqual(mctp_stress_issues(16, '0', STRESS_OK, 0), [])

    def test_stress_fail_reports_counts(self):
        found = mctp_stress_issues(17, '1', STRESS_FAIL, 1)
        self.assertEqual([i['code'] for i in found], ['MCTP_STRESS_FAIL'])
        self.assertIn('failed=1', found[0]['detail'])
        self.assertIn('2/10', found[0]['detail'])


if __name__ == '__main__':
    unittest.main()
