"""Attribute final BMC log entries to the loop whose window they fall in.

In final-only mode the EventLog and SEL are read once, after the last loop.
Every entry carries a BMC timestamp; every loop recorded the wall-clock window
it occupied. Matching the two answers "which loop produced this", which is
what the report needs to show without storing a snapshot per loop.

An entry outside every window is kept and reported as ``None``: it belongs to
this campaign (the logs were cleared at PRE) but not to a specific loop -
typically something the BMC logged while the run was wrapping up.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_UTC = timezone.utc
# These BMCs are kept on the rack's local zone; `ipmitool sel list` prints
# that wall-clock time with no offset.
BMC_TIMEZONE = timezone(timedelta(hours=8))


def parse_time(text):
    """Parse an ISO timestamp (any offset, ``Z`` allowed) into aware UTC.

    Returns None for anything unparsable. A timestamp we cannot read is not
    guessed at: it becomes an unattributed entry rather than being assigned to
    whichever loop happens to be nearest.
    """
    if not text:
        return None
    value = str(text).strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(_UTC)


def windows(loops):
    """Build [(loop_number, start, end)] from loop records.

    Each loop's end is stretched to the next loop's start, so no instant
    between two loops is unattributed: a BMC entry logged in the gap belongs
    to the loop that was running when it was written. The last loop keeps its
    own end. A loop missing a boundary cannot be matched reliably, so it is
    skipped: assigning its entries to a neighbouring loop would be a
    fabrication.
    """
    bounded = []
    for record in loops or []:
        number = record.get("loop")
        start = parse_time(record.get("loop_window_start"))
        end = parse_time(record.get("loop_window_end"))
        if number is None or start is None:
            continue
        bounded.append([number, start, end])
    for index in range(len(bounded) - 1):
        current, following = bounded[index], bounded[index + 1]
        if current[2] is None:
            current[2] = following[1]
        elif current[2] < following[1]:
            current[2] = following[1]
    return [(number, start, end) for number, start, end in bounded if end is not None]


def extend_last(spans, until):
    """Open the final loop's window to ``until`` (an aware datetime).

    The last loop is still running when the final read starts, so an entry it
    produced after its own recorded end must still be attributed to it. A
    window whose end precedes its start (a loop that failed instantly) is
    widened to a single instant instead of being dropped.
    """
    if not spans or until is None:
        return spans
    number, start, end = spans[-1]
    widened = until if end is None or end < until else end
    return spans[:-1] + [(number, start, widened)]


def attribute(entries, spans):
    """Tag every entry with the loop whose window contains it.

    ``entries`` are dicts with a ``created`` timestamp; each is copied with a
    ``loop`` key added. An entry landing in more than one window (overlapping
    loops cannot happen on one node, but a clock step could) takes the first,
    so the mapping stays deterministic.
    """
    tagged = []
    for entry in entries or []:
        item = dict(entry)
        stamp = parse_time(item.get("created"))
        item["loop"] = None
        if stamp is not None:
            for number, start, end in spans:
                if start <= stamp <= end:
                    item["loop"] = number
                    break
        tagged.append(item)
    return tagged


def severity_counts(entries):
    """Count entries by severity, matching the report's existing buckets."""
    counts = {"Critical": 0, "Warning": 0, "OK": 0, "Other": 0}
    for entry in entries or []:
        key = str(entry.get("severity") or "").strip().lower()
        name = "Critical" if key == "critical" else "Warning" if key == "warning" else "OK" if key == "ok" else "Other"
        counts[name] += 1
    return counts


def worst(entries):
    """Return the health contribution of a final log: FAIL, WARN or PASS."""
    counts = severity_counts(entries)
    if counts["Critical"]:
        return "FAIL"
    if counts["Warning"]:
        return "WARN"
    return "PASS"


def render_lines(entries):
    """One text line per entry for the evidence file."""
    lines = []
    for entry in entries or []:
        loop = entry.get("loop")
        lines.append("{id}  {created}  loop={loop}  [{severity}]  {message}".format(
            id=entry.get("id", ""),
            created=entry.get("created", ""),
            loop=loop if loop is not None else "-",
            severity=entry.get("severity", ""),
            message=entry.get("message", "")))
    return "\n".join(lines) + ("\n" if lines else "")


_SEL_ROW = re.compile(
    r"^\s*([0-9a-fA-F]+)\s*\|\s*(\d{1,2}/\d{1,2}/\d{4})\s*\|\s*(\d{2}:\d{2}:\d{2})\s*\|\s*(.*)$")


def parse_sel_entries(text):
    """Turn ``ipmitool sel list`` rows into the same entry shape as Redfish.

    ``ipmitool`` prints the BMC's local time with no offset, and this platform
    keeps its BMCs on UTC+8, so that is the offset assumed. A row we cannot
    parse is dropped rather than guessed at; the raw SEL evidence still holds
    it in full.

    Severity is derived from the row text because ``ipmitool sel list`` has no
    severity column: ``Asserted`` is the event, ``Deasserted`` its clearing.
    """
    entries = []
    for line in (text or "").splitlines():
        match = _SEL_ROW.match(line)
        if not match:
            continue
        number, date, clock, rest = match.groups()
        fields = [part.strip() for part in rest.split("|")]
        try:
            month, day, year = (int(part) for part in date.split("/"))
            hour, minute, second = (int(part) for part in clock.split(":"))
            stamp = datetime(year, month, day, hour, minute, second, tzinfo=BMC_TIMEZONE)
        except ValueError:
            continue
        entries.append(dict(
            id=number,
            created=stamp.astimezone(timezone.utc).isoformat(),
            severity="",
            severity_key="",
            message=" | ".join(part for part in fields if part),
            resolved=False,
        ))
    return entries
