"""Nello - caregiver assignment optimizer (PuLP).

Static "schedule optimization" box of the Nello flow:
  input : shared .ics of the dependent (activities, fixed times)
          one personal .ics per caregiver (every event = busy)
          config.json (caregivers, capabilities, dislikes, weights, caps)
  output: dict with status, one caregiver per activity, loads, changes.

Model
  x[c,a] in {0,1}                     caregiver c accompanies activity a
  sum_c x[c,a] = 1                    every activity is accompanied
  x[c,a] only exists if c is eligible (free, has required tags,
                                       does not dislike the type, not excluded)
  x[c,a1] + x[c,a2] <= 1              a1 and a2 overlap in time
  load[c] = sum_a w(type_a) * hours_a * x[c,a]   (<= max_load[c] if set)
  Lmin <= load[c] <= Lmax
  min  (Lmax - Lmin) + eps * #changed existing assignments
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations
from pathlib import Path

import pulp

from ics_utils import read_ics

CHANGE_PENALTY = 0.5  # cost of reassigning an already-assigned activity (load units)
TIE_BREAK = 0.001     # tiny push on Lmax so the solver also keeps the peak low


# ---------------------------------------------------------------- data model
@dataclass
class Activity:
    uid: str
    title: str
    start: datetime
    end: datetime
    type: str
    requires: list[str] = field(default_factory=list)
    notes: str = ""
    current: str | None = None  # caregiver id currently assigned, if any

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600


@dataclass
class Caregiver:
    id: str
    name: str
    capabilities: list[str] = field(default_factory=list)
    dislikes: list[str] = field(default_factory=list)
    max_load: float | None = None
    busy: list[tuple[datetime, datetime, str]] = field(default_factory=list)


def _key(title: str, start: datetime) -> tuple[str, datetime]:
    """Match a personal event to a shared activity (UIDs are not guaranteed)."""
    return title.strip().lower(), start


def _split(v: str | None) -> list[str]:
    return [s.strip() for s in (v or "").split(",") if s.strip()]


def load_problem(shared_ics: str | Path, caregivers_dir: str | Path, config_path: str | Path):
    """Read the .ics files + config into Activity / Caregiver objects."""
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))

    activities = [
        Activity(
            uid=ev["uid"],
            title=ev["summary"],
            start=ev["dtstart"],
            end=ev["dtend"],
            type=_split(ev.get("categories"))[0] if ev.get("categories") else "other",
            requires=_split(ev.get("x-nello-requires")),
            notes=ev.get("description", ""),
            current=ev.get("x-nello-caregiver") or None,
        )
        for ev in read_ics(shared_ics)
    ]
    shared_keys = {_key(a.title, a.start) for a in activities}

    caregivers = []
    for c in config["caregivers"]:
        cg = Caregiver(
            id=c["id"],
            name=c["name"],
            capabilities=c.get("capabilities", []),
            dislikes=c.get("dislikes", []),
            max_load=c.get("max_load"),
        )
        ics_path = Path(caregivers_dir) / f"{c['id']}.ics"
        if ics_path.exists():
            for ev in read_ics(ics_path):
                # the shared activity also appears in the assignee's personal
                # agenda: ignore it, otherwise it would block itself
                if _key(ev["summary"], ev["dtstart"]) in shared_keys:
                    continue
                cg.busy.append((ev["dtstart"], ev["dtend"], ev["summary"]))
        caregivers.append(cg)

    weights = config.get("weights", {})
    return activities, caregivers, weights


# ---------------------------------------------------------------- eligibility
def _overlaps(s1, e1, s2, e2) -> bool:
    return s1 < e2 and s2 < e1


def eligibility(a: Activity, c: Caregiver, excluded: dict[str, list[str]]) -> str | None:
    """Return None if c can take a, else a human-readable reason."""
    if c.id in excluded.get(a.uid, []):
        return "rejected this activity"
    missing = [r for r in a.requires if r not in c.capabilities]
    if missing:
        return f"missing: {', '.join(missing)}"
    if a.type in c.dislikes:
        return f"does not do '{a.type}'"
    for s, e, title in c.busy:
        if _overlaps(a.start, a.end, s, e):
            return f"busy: {title} {s:%H:%M}-{e:%H:%M}"
    return None


# ---------------------------------------------------------------- solver
def _var(prob: pulp.LpProblem, name: str, low=None, cat: str = "Continuous"):
    """Create a variable on PuLP 2.x (LpVariable) and PuLP 4 (prob.add_variable)."""
    if hasattr(prob, "add_variable"):
        return prob.add_variable(name, lowBound=low, cat=cat)
    return pulp.LpVariable(name, lowBound=low, cat=cat)


def _solver():
    available = pulp.listSolvers(onlyAvailable=True)
    for name in ("PULP_CBC_CMD", "HiGHS", "HiGHS_CMD", "COIN_CMD", "GLPK_CMD"):
        if name in available:
            return pulp.getSolver(name, msg=False)
    raise RuntimeError("No MILP solver found: pip install highspy (or pulp<3 for bundled CBC)")


def optimize(
    activities: list[Activity],
    caregivers: list[Caregiver],
    weights: dict[str, float],
    excluded: dict[str, list[str]] | None = None,
    change_penalty: float = CHANGE_PENALTY,
) -> dict:
    excluded = excluded or {}
    cg_by_id = {c.id: c for c in caregivers}
    w = lambda a: weights.get(a.type, 1.0) * a.hours  # noqa: E731

    # ---- pre-processing: who can take what
    eligible: dict[str, list[str]] = {}
    reasons: dict[str, dict[str, str]] = {}
    for a in activities:
        eligible[a.uid] = []
        reasons[a.uid] = {}
        for c in caregivers:
            why = eligibility(a, c, excluded)
            if why is None:
                eligible[a.uid].append(c.id)
            else:
                reasons[a.uid][c.id] = why

    impossible = [a for a in activities if not eligible[a.uid]]
    if impossible:
        return {
            "status": "conditions not met",
            "unassignable": [
                {"uid": a.uid, "title": a.title, "start": a.start, "end": a.end,
                 "reasons": reasons[a.uid]}
                for a in impossible
            ],
        }

    # ---- model
    prob = pulp.LpProblem("nello_caregiver_assignment", pulp.LpMinimize)
    x = {
        (c, a.uid): _var(prob, f"x_{c}_{i}", cat="Binary")
        for i, a in enumerate(activities)
        for c in eligible[a.uid]
    }
    l_max = _var(prob, "L_max", low=0)
    l_min = _var(prob, "L_min", low=0)

    # every activity accompanied by exactly one caregiver
    for a in activities:
        prob += pulp.lpSum(x[c, a.uid] for c in eligible[a.uid]) == 1, f"cover_{a.uid}"

    # one caregiver cannot be at two overlapping activities
    for a1, a2 in combinations(activities, 2):
        if _overlaps(a1.start, a1.end, a2.start, a2.end):
            for c in set(eligible[a1.uid]) & set(eligible[a2.uid]):
                prob += x[c, a1.uid] + x[c, a2.uid] <= 1

    # loads, caps, balance
    loads = {}
    for c in caregivers:
        loads[c.id] = pulp.lpSum(w(a) * x[c.id, a.uid] for a in activities if (c.id, a.uid) in x)
        prob += loads[c.id] <= l_max
        prob += loads[c.id] >= l_min
        if c.max_load is not None:
            prob += loads[c.id] <= c.max_load, f"cap_{c.id}"

    # stability: penalise moving an already-assigned activity
    changes = []
    for a in activities:
        if a.current in cg_by_id:
            changes.append(1 - x[a.current, a.uid] if (a.current, a.uid) in x else 1)

    prob += (l_max - l_min) + change_penalty * pulp.lpSum(changes) + TIE_BREAK * l_max

    prob.solve(_solver())
    if pulp.LpStatus[prob.status] != "Optimal":
        # every activity has someone, but not simultaneously (overlaps / caps)
        return {"status": "conditions not met", "unassignable": [],
                "detail": f"solver status: {pulp.LpStatus[prob.status]}"}

    # ---- read solution
    assignments = []
    for a in activities:
        chosen = next(c for c in eligible[a.uid] if x[c, a.uid].value() > 0.5)
        assignments.append({
            "uid": a.uid, "title": a.title, "start": a.start, "end": a.end,
            "type": a.type, "notes": a.notes, "requires": a.requires,
            "caregiver": chosen, "previous": a.current,
            "changed": a.current is not None and a.current != chosen,
            "new": a.current is None,
        })
    return {
        "status": "ok",
        "assignments": sorted(assignments, key=lambda r: r["start"]),
        "loads": {c.id: round(pulp.value(loads[c.id]) or 0, 2) for c in caregivers},
        "spread": round(l_max.value() - l_min.value(), 2),
    }


def run(shared_ics, caregivers_dir, config_path, excluded=None) -> dict:
    activities, caregivers, weights = load_problem(shared_ics, caregivers_dir, config_path)
    return optimize(activities, caregivers, weights, excluded)


if __name__ == "__main__":
    from display import print_result

    p = argparse.ArgumentParser(description="Nello caregiver assignment optimizer")
    p.add_argument("--shared", default="data/shared_dependent.ics")
    p.add_argument("--caregivers", default="data/caregivers")
    p.add_argument("--config", default="data/config.json")
    args = p.parse_args()

    acts, cgs, wts = load_problem(args.shared, args.caregivers, args.config)
    print_result(optimize(acts, cgs, wts), {c.id: c.name for c in cgs})
