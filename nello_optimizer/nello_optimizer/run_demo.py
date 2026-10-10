"""End-to-end console demo of the optimization box.

  Step 1  balance the month as it stands
  Step 2  Luc's message: "rdv cardio lundi 11h-12h, je ne peux pas y aller,
          je dois récupérer les enfants. Il faut y aller en voiture. Il faut
          aussi passer à la pharmacie mardi matin"
          -> the orchestrator (simulated here) adds Luc's busy block and the
             two activities, then calls the optimizer
  Step 3  Luc becomes busy during his physio + new IRM -> forced reassignment
  Step 4  (python run_demo.py --with-failure) an activity nobody can take

Every step writes the result back into the .ics files (shared agenda +
the caregivers' personal agendas), so you can open them in any calendar app.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import generate_demo_data
from display import print_loads, print_notifications, print_result, title
from ics_utils import read_ics, write_ics
from optimizer import load_problem, optimize

DATA = Path(__file__).parent / "data"
SHARED = DATA / "shared_dependent.ics"
CG_DIR = DATA / "caregivers"
CONFIG = DATA / "config.json"


def solve():
    acts, cgs, weights = load_problem(SHARED, CG_DIR, CONFIG)
    return optimize(acts, cgs, weights), {c.id: c.name for c in cgs}


def apply_result(result: dict) -> None:
    """'Agendas updated with event and associated caregiver' box."""
    by_uid = {r["uid"]: r for r in result["assignments"]}
    shared = read_ics(SHARED)
    for ev in shared:
        ev["x-nello-caregiver"] = by_uid[ev["uid"]]["caregiver"]
    write_ics(SHARED, shared, "Nello - agenda partagé")

    keys = {(r["title"].lower(), r["start"]): r for r in result["assignments"]}
    for path in CG_DIR.glob("*.ics"):
        cid = path.stem
        # drop copies of shared activities, then re-add the ones assigned to cid
        events = [e for e in read_ics(path) if (e["summary"].lower(), e["dtstart"]) not in keys]
        for r in result["assignments"]:
            if r["caregiver"] == cid:
                events.append({"uid": f"{r['uid']}-{cid}", "dtstart": r["start"], "dtend": r["end"],
                               "summary": r["title"], "description": r["notes"]})
        events.sort(key=lambda e: e["dtstart"])
        write_ics(path, events, f"Agenda perso - {cid}")


def add_event(path: Path, calname: str, **ev) -> None:
    events = read_ics(path)
    ev.setdefault("uid", f"demo-{len(events) + 1:03d}-{path.stem}@nello")
    events.append(ev)
    write_ics(path, sorted(events, key=lambda e: e["dtstart"]), calname)


def main() -> None:
    generate_demo_data.generate()

    # ---------------------------------------------------------------- step 1
    title("STEP 1 - Balance the month (12/10 - 08/11) as it stands")
    _, cgs, weights = load_problem(SHARED, CG_DIR, CONFIG)
    acts, _, _ = load_problem(SHARED, CG_DIR, CONFIG)
    names = {c.id: c.name for c in cgs}
    before = {c.id: 0.0 for c in cgs}
    for a in acts:
        if a.current:
            before[a.current] += weights.get(a.type, 1.0) * a.hours
    print("\n  Current situation (2 physio sessions still without a caregiver)")
    print_loads({k: round(v, 2) for k, v in before.items()}, names)

    res1 = optimize(acts, cgs, weights)
    print(f"\n  Optimized plan  [{res1['status']}]")
    print_result(res1, names)
    apply_result(res1)
    print_notifications(res1, names)

    # ---------------------------------------------------------------- step 2
    title("STEP 2 - Luc: « rdv cardio lundi 11h-12h, je ne peux pas y aller... »")
    print("\n  Orchestrator sub-tasks:")
    print("    1. Luc busy  lun 12/10 11:00-12:00  (récupérer les enfants)")
    print("    2. Cardiologue lun 12/10 11:00-12:00  requires: car")
    print("    3. Pharmacie   mar 13/10 09:00-09:30")
    add_event(CG_DIR / "luc.ics", "Agenda perso - luc", summary="Récupérer les enfants",
              dtstart=datetime(2026, 10, 12, 11), dtend=datetime(2026, 10, 12, 12))
    add_event(SHARED, "Nello - agenda partagé", summary="Cardiologue",
              dtstart=datetime(2026, 10, 12, 11), dtend=datetime(2026, 10, 12, 12),
              categories="routine_medical", **{"x-nello-requires": "car"},
              description="prendre la voiture")
    add_event(SHARED, "Nello - agenda partagé", summary="Pharmacie",
              dtstart=datetime(2026, 10, 13, 9), dtend=datetime(2026, 10, 13, 9, 30),
              categories="errand", description="récupérer les médicaments")

    res2, names = solve()
    print(f"\n  Re-optimized plan, changes only  [{res2['status']}]")
    print_result(res2, names, only_changes=True)
    print_notifications(res2, names)
    apply_result(res2)

    # ---------------------------------------------------------------- step 3
    title("STEP 3 - Luc: « mercredi j'ai une réunion de 14h à 17h » + new IRM")
    print("\n  Orchestrator sub-tasks:")
    print("    1. Luc busy  mer 14/10 14:00-17:00  (réunion)  -> conflicts with his Kiné")
    print("    2. IRM       jeu 22/10 16:00-17:00  requires: car")
    before = res2["loads"]
    add_event(CG_DIR / "luc.ics", "Agenda perso - luc", summary="Réunion",
              dtstart=datetime(2026, 10, 14, 14), dtend=datetime(2026, 10, 14, 17))
    add_event(SHARED, "Nello - agenda partagé", summary="IRM",
              dtstart=datetime(2026, 10, 22, 16), dtend=datetime(2026, 10, 22, 17),
              categories="heavy_medical", **{"x-nello-requires": "car"},
              description="prendre la voiture, carte vitale")
    res3, names = solve()
    print(f"\n  Re-optimized plan, changes only  [{res3['status']}]")
    print_result(res3, names, only_changes=True, before=before)
    print_notifications(res3, names)
    apply_result(res3)

    # ---------------------------------------------------------------- step 4
    if "--with-failure" in sys.argv:
        title("STEP 4 - New appointment nobody can take")
        print("\n  IRM de contrôle jeu 29/10 11:00-12:00, requires: car")
        add_event(SHARED, "Nello - agenda partagé", summary="IRM de contrôle",
                  dtstart=datetime(2026, 10, 29, 11), dtend=datetime(2026, 10, 29, 12),
                  categories="heavy_medical", **{"x-nello-requires": "car"})
        res4, names = solve()
        print_result(res4, names)

    print(f"\n  .ics files updated in {DATA}\n")


if __name__ == "__main__":
    main()
