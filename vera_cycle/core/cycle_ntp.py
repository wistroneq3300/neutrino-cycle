"""Point each BMC's NTP client at its own node's OS.

These BMCs boot with NTP enabled but an empty server list, so they sit at
2000-01-01 and every SEL/EventLog timestamp is meaningless. Writing the
clock once does not survive: every cycle reboots the BMC. Setting NTPServers
persists there, so one PATCH before PRE is enough to make each entry this
campaign produces carry a real timestamp.

Nothing here raises. A BMC that will not take the setting is reported as
WARN; it must never block a power action or change a node's verdict.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

# A BMC whose clock is within this window of the node's is considered synced.
CLOCK_TOLERANCE_SECONDS = 120

# Poll budget after a write. The BMC's first NTP exchange is usually under
# 15s, but a cold serviced BMC can take longer.
VERIFY_ATTEMPTS = 6
VERIFY_INTERVAL = 5.0


def manager_id(payload):
    """Return the first Manager id from a /Managers collection payload.

    The id is read from the payload instead of assumed to be ``BMC_0``: the
    same firmware family ships under different ids, and a wrong id would turn
    every write into a 404 that looks like a permission problem.
    """
    if not isinstance(payload, dict):
        return None
    for member in payload.get("Members") or []:
        if not isinstance(member, dict):
            continue
        path = str(member.get("@odata.id") or "").rstrip("/")
        if path:
            candidate = path.split("/")[-1]
            if candidate and candidate != "Managers":
                return candidate
    return None


def ntp_state(payload):
    """Extract (enabled, servers) from a NetworkProtocol payload."""
    if not isinstance(payload, dict):
        return False, []
    ntp = payload.get("NTP") or {}
    servers = [str(s).strip() for s in (ntp.get("NTPServers") or []) if str(s).strip()]
    return bool(ntp.get("ProtocolEnabled")), servers


def parse_clock(text):
    """Parse a Redfish ``DateTime`` into an aware UTC datetime, or None.

    Redfish allows offsets down to the minute and may drop the seconds field,
    so the accepted forms differ from ISO 8601 exactly. A clock reading we
    cannot parse is None - never "close enough".
    """
    if not text:
        return None
    value = str(text).strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    # ``+0000`` (no colon) is legal in the field but not in fromisoformat
    # before 3.11; normalise it so the parse does not silently fail.
    value = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # A naive timestamp has no defined offset; treat it as UTC rather than
        # local time, which would make the skew comparison depend on the
        # orchestrator's zone.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def clock_skew(bmc_text, reference):
    """Seconds between a BMC clock reading and ``reference`` (aware UTC)."""
    bmc = parse_clock(bmc_text)
    if bmc is None or reference is None:
        return None
    return (bmc - reference).total_seconds()


def needs_sync(enabled, servers, os_ip, skew):
    """Decide whether a BMC must be pointed at its node.

    Already pointing here with a plausible clock: leave it alone. Anything
    else - empty list, a different server, NTP disabled, or a clock that has
    drifted outside tolerance - is rewritten, because a stale clock produces
    exactly the meaningless timestamps this exists to prevent.
    """
    if not enabled:
        return True
    if not servers:
        return True
    if os_ip and os_ip.strip() not in servers:
        return True
    if skew is None:
        # The clock could not be read, so we cannot claim it is right.
        return True
    return abs(skew) > CLOCK_TOLERANCE_SECONDS
