"""Minimal .ics reader/writer for the Nello demo.

Only what the MVP needs: VEVENT blocks with floating local times
(YYYYMMDDTHHMMSS), SUMMARY, DESCRIPTION, CATEGORIES and the custom
X-NELLO-* properties. No timezone or RRULE handling (hackathon scope).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

DT_FMT = "%Y%m%dT%H%M%S"


def _unescape(v: str) -> str:
    return v.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _parse_dt(v: str) -> datetime:
    v = v.rstrip("Z")
    if "T" not in v:  # all-day event -> midnight
        v += "T000000"
    return datetime.strptime(v, DT_FMT)


def read_ics(path: str | Path) -> list[dict]:
    """Return a list of events as dicts with lowercase keys."""
    raw = Path(path).read_text(encoding="utf-8").splitlines()
    # RFC 5545 line unfolding: a line starting with space/tab continues the previous one
    lines: list[str] = []
    for line in raw:
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)

    events, cur = [], None
    for line in lines:
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            if cur is not None:
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            key, value = line.split(":", 1)
            key = key.split(";", 1)[0].upper()  # drop params like DTSTART;TZID=...
            if key in ("DTSTART", "DTEND"):
                cur[key.lower()] = _parse_dt(value)
            else:
                cur[key.lower()] = _unescape(value)
    return events


def write_ics(path: str | Path, events: list[dict], calname: str) -> None:
    """Write events (dicts from read_ics or built by hand) to a .ics file."""
    out = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Nello//Optimizer demo//FR",
        f"X-WR-CALNAME:{_escape(calname)}",
    ]
    for ev in events:
        out.append("BEGIN:VEVENT")
        out.append(f"UID:{ev['uid']}")
        out.append(f"DTSTART:{ev['dtstart'].strftime(DT_FMT)}")
        out.append(f"DTEND:{ev['dtend'].strftime(DT_FMT)}")
        out.append(f"SUMMARY:{_escape(ev['summary'])}")
        for key in ("description", "categories", "x-nello-requires", "x-nello-caregiver"):
            if ev.get(key):
                value = ev[key] if key == "categories" else _escape(ev[key])
                out.append(f"{key.upper()}:{value}")
        out.append("END:VEVENT")
    out.append("END:VCALENDAR")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\r\n".join(out) + "\r\n", encoding="utf-8")
