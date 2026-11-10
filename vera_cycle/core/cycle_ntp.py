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

# The node's own clock only has to line up well enough that timestamps from
# different nodes land in the same minute. Stricter than the BMC window so a
# node still stepping is not reported as synced.
NODE_CLOCK_TOLERANCE_SECONDS = 60

# chrony needs a couple of exchanges before it will step the clock, so a node
# that was just started is not wrong at 30s - it is simply not finished.
NODE_VERIFY_ATTEMPTS = 24
NODE_VERIFY_INTERVAL = 5.0

# Poll budget after a direct DateTime write. The value is applied synchronously
# by the BMC, so this only covers the read-back round trip.
DIRECT_VERIFY_ATTEMPTS = 3
DIRECT_VERIFY_INTERVAL = 1.0

# A BMC rejects a DateTime write while its NTP client is enabled ("its value
# would conflict with ... NTPProcotolEnabled"), so a forced sync has to disable
# NTP first and may need a moment before the manager accepts the write.
FORCE_PAUSE_SECONDS = 2.0


def parse_uptime(text):
    """Return the node's uptime in seconds from ``/proc/uptime``, or None."""
    if not text:
        return None
    parts = str(text).split()
    if not parts:
        return None
    try:
        value = float(parts[0])
    except ValueError:
        return None
    return value if value >= 0 else None


def node_clock_ok(uptime_seconds, tolerance=CLOCK_TOLERANCE_SECONDS):
    """Decide whether a node's clock is plausible enough to be a time source.

    A node that booted long ago whose clock still reads 2000 is running on a
    dead RTC and cannot serve time. ``None`` is not evidence either way, so it
    is treated as usable and the caller falls back to the plain NTP path.
    """
    if uptime_seconds is None:
        return True
    return uptime_seconds <= tolerance * 10


def serving_ntp(listen_output):
    """True when a node's ``ss -lun`` output shows a UDP listener on port 123.

    Pointing the BMC at a node that does not answer NTP is the failure this
    check exists to name. An empty or unparsable output is read as "not
    serving", because the check exists to prove service, not to assume it.
    """
    if not listen_output:
        return False
    for line in str(listen_output).splitlines():
        fields = line.split()
        if not fields:
            continue
        # ss prints the local address in a different column depending on
        # whether the netid was merged; match the port suffix so both layouts
        # are covered.
        for field in fields:
            address = field.rsplit("@", 1)[0]
            if address.endswith(":123") or address.endswith(".123"):
                return True
    return False


def utc_now_text(reference):
    """Format an aware UTC datetime as the Redfish ``DateTime`` string."""
    return reference.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


# Ubuntu ships its NTP pools with ``nts prefer``. NTS needs a key exchange on
# 4460/tcp before any time is exchanged, and that port is commonly blocked in a
# lab network: chrony then sits at Reach=0 with every source at stratum 0 while
# plain UDP/123 works fine.
DEFAULT_SOURCES = ("185.125.190.58", "91.189.91.157")

# ``sourcedir`` entries must end in ``.sources``; chrony silently ignores any
# other suffix, which would leave the node unreachable with no error.
SOURCES_FILE = "/etc/chrony/sources.d/cycle-ntp.sources"
ALLOW_FILE = "/etc/chrony/conf.d/cycle-allow.conf"

# Pool file shipped by the package that carries the NTS pools which never sync
# on a filtered network. Renamed rather than deleted so the change is
# reversible from the node itself.
NTS_POOL_GLOB = "/etc/chrony/sources.d/ubuntu-ntp-pools.sources"


def sources_text(servers):
    """Render a chrony ``.sources`` file from a list of server addresses."""
    lines = [f'server {server.strip()} iburst' for server in servers if str(server).strip()]
    return "\n".join(lines) + "\n" if lines else ""


def allow_text(network):
    """Render a chrony ``allow`` line for the BMC subnet, or '' when unset."""
    network = str(network or '').strip()
    return f'allow {network}\n' if network else ""


def local_date_plausible(epoch_seconds, reference_epoch, tolerance=NODE_CLOCK_TOLERANCE_SECONDS):
    """True when a reported epoch is near the orchestrator's own clock."""
    if epoch_seconds is None or reference_epoch is None:
        return False
    try:
        return abs(int(epoch_seconds) - int(reference_epoch)) <= tolerance
    except (TypeError, ValueError):
        return False


def parse_epoch(text):
    """Parse a bare integer epoch from a command output, or None."""
    if not text:
        return None
    value = str(text).strip().splitlines()[0].strip() if str(text).strip() else ""
    try:
        return int(value)
    except ValueError:
        return None


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
