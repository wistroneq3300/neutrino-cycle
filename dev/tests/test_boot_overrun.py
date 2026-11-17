"""Boot overrun handling: a slow boot is followed, not failed."""
from __future__ import annotations

import unittest

from vera_cycle.engine import cycle_engine


class SlowBootConstantsTests(unittest.TestCase):
    def test_slow_threshold_is_below_the_total_timeout(self):
        # A boot cannot be "slow" past the point it is already a failure.
        self.assertLess(cycle_engine.BOOT_SLOW_THRESHOLD, 1800)

    def test_slow_poll_is_slower_than_the_normal_poll(self):
        # Past the threshold the poll must back off, not get faster.
        self.assertGreater(cycle_engine.BOOT_SLOW_POLL_INTERVAL, 10)

    def test_slow_poll_still_fits_several_tries_in_the_overrun(self):
        # From 900s to 1800s at 60s there are 15 checks: enough to catch the OS.
        overrun = 1800 - cycle_engine.BOOT_SLOW_THRESHOLD
        self.assertGreaterEqual(overrun // cycle_engine.BOOT_SLOW_POLL_INTERVAL, 10)


class BootSlowSeverityTests(unittest.TestCase):
    def test_boot_slow_is_info_not_warn(self):
        # A late boot must not drag the case verdict down; it is a fact about
        # the machine's speed, not a hardware fault.
        import inspect
        source = inspect.getsource(cycle_engine.NodeSession.wait_boot)
        self.assertIn('BOOT_SLOW', source)
        self.assertIn("severity='INFO'", source)

    def test_timeout_still_fails_the_loop(self):
        import inspect
        source = inspect.getsource(cycle_engine.NodeSession.wait_boot)
        self.assertIn('BOOT_TIMEOUT', source)
        # The timeout path must end by reporting failure to the caller.
        self.assertTrue(source.rstrip().endswith('return False'))


if __name__ == '__main__':
    unittest.main()
