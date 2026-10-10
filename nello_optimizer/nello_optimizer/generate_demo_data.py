"""Generate the demo dataset: one month (12 Oct - 8 Nov 2026).

  data/config.json
  data/shared_dependent.ics        the dependent's activities (shared on Nello)
  data/caregivers/<id>.ics         personal agendas

Caregivers
  Luc     no car, works Tue/Thu 9-17, school pick-up every weekday 16:30-17:00
  Marie   car, part-time Wed/Thu/Fri 9-15
  Michel  car, works Mon-Thu 10-19, football Wed evening
  Sophie  no car, classes Mon/Tue/Wed 9-13, Saturday job 9-13,
          does not go to medical appointments
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from ics_utils import write_ics

DATA = Path(__file__).parent / "data"
MONTH_START = date(2026, 10, 12)  # Monday
DAYS = 28

CONFIG = {
    "horizon": {"start": "2026-10-12", "end": "2026-11-08"},
    "weights": {
        "heavy_medical": 3.0,    # oncology, surgery
        "routine_medical": 2.0,  # GP, physio, blood test, cardio follow-up
        "admin": 1.5,
        "errand": 1.5,           # pharmacy, shopping
        "leisure": 1.0,          # walk, cinema
    },
    "caregivers": [
        {"id": "luc", "name": "Luc", "capabilities": [], "dislikes": []},
        {"id": "marie", "name": "Marie", "capabilities": ["car"], "dislikes": []},
        {"id": "michel", "name": "Michel", "capabilities": ["car"], "dislikes": []},
        {"id": "sophie", "name": "Sophie", "capabilities": [],
         "dislikes": ["heavy_medical", "routine_medical"]},
    ],
}

# (date, start, end, title, type, requires, notes, current caregiver)
SHARED = [
    ("2026-10-14", "15:00", "16:00", "Kiné", "routine_medical", "", "", "luc"),
    ("2026-10-15", "10:00", "11:00", "Promenade au parc", "leisure", "", "", "sophie"),
    ("2026-10-17", "10:00", "11:30", "Courses supermarché", "errand", "car", "prendre la voiture", "michel"),
    ("2026-10-20", "14:00", "16:00", "Oncologie - consultation", "heavy_medical", "car",
     "apporter les derniers résultats", "marie"),
    ("2026-10-21", "15:00", "16:00", "Kiné", "routine_medical", "", "", "luc"),
    ("2026-10-22", "10:00", "11:00", "Promenade au parc", "leisure", "", "", "sophie"),
    ("2026-10-23", "14:00", "15:00", "Dossier MDPH", "admin", "", "carte d'identité + justificatifs", "luc"),
    ("2026-10-24", "10:00", "11:30", "Courses supermarché", "errand", "car", "prendre la voiture", "marie"),
    ("2026-10-26", "08:00", "08:30", "Prise de sang", "routine_medical", "", "à jeun", "michel"),
    ("2026-10-28", "15:00", "16:00", "Kiné", "routine_medical", "", "", None),
    ("2026-10-31", "15:00", "17:30", "Cinéma", "leisure", "", "", "sophie"),
    ("2026-11-04", "15:00", "16:00", "Kiné", "routine_medical", "", "", None),
    ("2026-11-05", "10:00", "11:00", "Promenade au parc", "leisure", "", "", "sophie"),
    ("2026-11-06", "09:00", "13:00", "Oncologie - chimiothérapie", "heavy_medical", "car",
     "prévoir un repas léger", "michel"),
    ("2026-11-07", "10:00", "10:30", "Pharmacie", "errand", "", "ordonnance dans le tiroir", "luc"),
]

# weekly personal routines: id -> list of (weekday 0=Mon, start, end, title)
ROUTINES = {
    "luc": [(d, "09:00", "17:00", "Travail") for d in (1, 3)]
    + [(d, "16:30", "17:00", "Sortie d'école") for d in range(5)],
    "marie": [(d, "09:00", "15:00", "Travail") for d in (2, 3, 4)],
    "michel": [(d, "10:00", "19:00", "Travail") for d in range(4)] + [(2, "20:00", "22:00", "Foot")],
    "sophie": [(d, "09:00", "13:00", "Cours") for d in range(3)] + [(5, "09:00", "13:00", "Job")],
}

# one-off personal events
ONE_OFF = {
    "marie": [("2026-10-30", "10:00", "12:00", "Dentiste")],
    "luc": [("2026-11-02", "18:00", "20:00", "Réunion parents")],
}


def dt(d: str | date, hm: str) -> datetime:
    d = date.fromisoformat(d) if isinstance(d, str) else d
    h, m = map(int, hm.split(":"))
    return datetime(d.year, d.month, d.day, h, m)


def shared_events() -> list[dict]:
    events = []
    for i, (d, s, e, title, typ, req, notes, cur) in enumerate(SHARED, 1):
        events.append({
            "uid": f"shared-{i:03d}@nello",
            "dtstart": dt(d, s), "dtend": dt(d, e), "summary": title,
            "categories": typ, "x-nello-requires": req, "description": notes,
            "x-nello-caregiver": cur or "",
        })
    return events


def personal_events(cid: str, shared: list[dict]) -> list[dict]:
    events = []
    for k in range(DAYS):
        day = MONTH_START + timedelta(days=k)
        for wd, s, e, title in ROUTINES.get(cid, []):
            if day.weekday() == wd:
                events.append({"dtstart": dt(day, s), "dtend": dt(day, e), "summary": title})
    for d, s, e, title in ONE_OFF.get(cid, []):
        events.append({"dtstart": dt(d, s), "dtend": dt(d, e), "summary": title})
    # the activities already assigned to this caregiver also live in their own
    # agenda (different UID, same title + start) -> the optimizer must ignore them
    for ev in shared:
        if ev["x-nello-caregiver"] == cid:
            events.append({"dtstart": ev["dtstart"], "dtend": ev["dtend"], "summary": ev["summary"]})
    events.sort(key=lambda e: e["dtstart"])
    for i, ev in enumerate(events, 1):
        ev["uid"] = f"{cid}-{i:03d}@perso"
    return events


def generate() -> None:
    DATA.mkdir(exist_ok=True)
    (DATA / "config.json").write_text(json.dumps(CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
    shared = shared_events()
    write_ics(DATA / "shared_dependent.ics", shared, "Nello - agenda partagé")
    for c in CONFIG["caregivers"]:
        write_ics(DATA / "caregivers" / f"{c['id']}.ics", personal_events(c["id"], shared),
                  f"Agenda perso - {c['name']}")


if __name__ == "__main__":
    generate()
    print(f"Demo data written to {DATA}")
