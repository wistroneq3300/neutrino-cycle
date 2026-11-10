"""BMC clock sync: NTP availability, direct write fallback, and decisions."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from vera_cycle.core import cycle_ntp as ntp


class ServingNtpTests(unittest.TestCase):
    def test_udp_123_listener_is_detected(self):
        output = (
            "Netid State  Recv-Q Send-Q Local Address:Port Peer Address:Port\n"
            "udp   UNCONN 0      0            0.0.0.0:123        0.0.0.0:*\n"
        )
        self.assertTrue(ntp.serving_ntp(output))

    def test_wildcard_v6_listener_is_detected(self):
        output = "udp UNCONN 0 0 [::]:123 [::]:*\n"
        self.assertTrue(ntp.serving_ntp(output))

    def test_netstat_style_address_is_detected(self):
        output = "udp 0 0 10.36.72.44:123 0.0.0.0:*\n"
        self.assertTrue(ntp.serving_ntp(output))

    def test_no_listener_is_false(self):
        output = (
            "Netid State  Recv-Q Send-Q Local Address:Port Peer Address:Port\n"
            "udp   UNCONN 0      0          127.0.0.53:53        0.0.0.0:*\n"
        )
        self.assertFalse(ntp.serving_ntp(output))

    def test_empty_output_is_false(self):
        self.assertFalse(ntp.serving_ntp(""))
        self.assertFalse(ntp.serving_ntp(None))

    def test_other_port_ending_in_123_is_not_a_match(self):
        # 8123 is not 123; a substring match would wrongly pass it.
        self.assertFalse(ntp.serving_ntp("udp UNCONN 0 0 0.0.0.0:8123 0.0.0.0:*\n"))


class ProbedOutputTests(unittest.TestCase):
    """The node probe prints /proc/uptime first, then the listener table."""

    def test_uptime_is_parsed_from_probe_output(self):
        text = "12345.67 45781.02\nudp UNCONN 0 0 0.0.0.0:123 0.0.0.0:*\n"
        self.assertEqual(ntp.parse_uptime(text), 12345.67)
        self.assertTrue(ntp.serving_ntp(text))

    def test_node_without_listener_still_yields_uptime(self):
        text = "12345.67 45781.02\nudp UNCONN 0 0 127.0.0.53:53 0.0.0.0:*\n"
        self.assertEqual(ntp.parse_uptime(text), 12345.67)
        self.assertFalse(ntp.serving_ntp(text))

    def test_unparsable_uptime_is_none(self):
        self.assertIsNone(ntp.parse_uptime(""))
        self.assertIsNone(ntp.parse_uptime("not-a-number"))


class NodeClockTests(unittest.TestCase):
    def test_long_uptime_with_dead_rtc_is_not_a_source(self):
        # A node up for days whose clock reads 2000 cannot serve time.
        self.assertFalse(ntp.node_clock_ok(200000))

    def test_fresh_boot_is_acceptable(self):
        self.assertTrue(ntp.node_clock_ok(60))

    def test_unknown_uptime_falls_back_to_ntp_path(self):
        self.assertTrue(ntp.node_clock_ok(None))


class ChronyConfigTests(unittest.TestCase):
    def test_sources_text_uses_plain_ntp_without_nts(self):
        text = ntp.sources_text(['185.125.190.58', '91.189.91.157'])
        self.assertEqual(text, 'server 185.125.190.58 iburst\nserver 91.189.91.157 iburst\n')
        # NTS requires 4460/tcp, which a lab firewall commonly blocks; the
        # generated file must never carry it.
        self.assertNotIn('nts', text)

    def test_sources_text_skips_blanks(self):
        self.assertEqual(ntp.sources_text(['', '  ', '1.2.3.4']), 'server 1.2.3.4 iburst\n')

    def test_sources_text_empty_when_no_servers(self):
        self.assertEqual(ntp.sources_text([]), '')

    def test_allow_text_renders_network(self):
        self.assertEqual(ntp.allow_text('10.36.72.0/22'), 'allow 10.36.72.0/22\n')

    def test_allow_text_empty_when_unset(self):
        self.assertEqual(ntp.allow_text(''), '')
        self.assertEqual(ntp.allow_text(None), '')

    def test_sources_file_has_required_suffix(self):
        # chrony ignores anything in sources.d that is not *.sources
        self.assertTrue(ntp.SOURCES_FILE.endswith('.sources'))


class NodeDateTests(unittest.TestCase):
    def test_node_tolerance_is_tighter_than_bmc(self):
        # Minute-level agreement is enough across nodes, but the node window
        # must still be stricter than the BMC one.
        self.assertLess(ntp.NODE_CLOCK_TOLERANCE_SECONDS, ntp.CLOCK_TOLERANCE_SECONDS)
        self.assertTrue(ntp.local_date_plausible(1794281344, 1794281310))

    def test_node_verify_budget_covers_slow_first_sync(self):
        total = ntp.NODE_VERIFY_ATTEMPTS * ntp.NODE_VERIFY_INTERVAL
        self.assertGreaterEqual(total, 60, 'chrony first sync can take over a minute')

    def test_plausible_when_within_tolerance(self):
        self.assertTrue(ntp.local_date_plausible(1794281360, 1794281310))

    def test_same_minute_tolerance_accepts_59s(self):
        self.assertTrue(ntp.local_date_plausible(1794281369, 1794281310))
        self.assertFalse(ntp.local_date_plausible(1794281371, 1794281310))

    def test_implausible_when_stuck_in_2000(self):
        self.assertFalse(ntp.local_date_plausible(946684800, 1794281310))

    def test_missing_values_are_not_plausible(self):
        self.assertFalse(ntp.local_date_plausible(None, 1794281310))
        self.assertFalse(ntp.local_date_plausible(1794281310, None))

    def test_parse_epoch_reads_first_line(self):
        self.assertEqual(ntp.parse_epoch('1794281316\n'), 1794281316)

    def test_parse_epoch_rejects_garbage(self):
        self.assertIsNone(ntp.parse_epoch(''))
        self.assertIsNone(ntp.parse_epoch('not-an-epoch'))


class ForceSyncConstantsTests(unittest.TestCase):
    def test_direct_verify_budget_is_bounded(self):
        self.assertGreaterEqual(ntp.DIRECT_VERIFY_ATTEMPTS, 1)
        self.assertGreater(ntp.DIRECT_VERIFY_INTERVAL, 0)
        total = ntp.DIRECT_VERIFY_ATTEMPTS * ntp.DIRECT_VERIFY_INTERVAL
        self.assertLessEqual(total, 30, 'direct verification must stay short')

    def test_utc_now_text_matches_redfish_format(self):
        stamp = ntp.utc_now_text(datetime(2026, 11, 10, 3, 9, 2, tzinfo=timezone.utc))
        self.assertEqual(stamp, '2026-11-10T03:09:02+00:00')

    def test_utc_now_text_normalises_other_zones(self):
        tz = timezone(__import__('datetime').timedelta(hours=8))
        stamp = ntp.utc_now_text(datetime(2026, 11, 10, 11, 9, 2, tzinfo=tz))
        self.assertEqual(stamp, '2026-11-10T03:09:02+00:00')

    def test_round_trip_through_clock_skew_is_zero(self):
        now = datetime(2026, 11, 10, 3, 9, 2, tzinfo=timezone.utc)
        self.assertEqual(ntp.clock_skew(ntp.utc_now_text(now), now), 0)


if __name__ == '__main__':
    unittest.main()
