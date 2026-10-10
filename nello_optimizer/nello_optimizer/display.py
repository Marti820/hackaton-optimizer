"""Console rendering of optimizer results."""
from __future__ import annotations

import sys

_COLOR = sys.stdout.isatty()
DAYS_FR = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]


def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def title(text: str) -> None:
    print("\n" + c("═" * 78, "36"))
    print(c(f"  {text}", "1;36"))
    print(c("═" * 78, "36"))


def _when(start, end) -> str:
    return f"{DAYS_FR[start.weekday()]} {start:%d/%m} {start:%H:%M}-{end:%H:%M}"


def print_result(result: dict, names: dict[str, str], only_changes: bool = False,
                 before: dict | None = None) -> None:
    if result["status"] != "ok":
        print(c("\n  ✗ CONDITIONS NOT MET", "1;31"))
        for u in result.get("unassignable", []):
            print(f"\n  {c(u['title'], '1')}  ({_when(u['start'], u['end'])})  - nobody can go:")
            for cid, why in u["reasons"].items():
                print(f"    · {names.get(cid, cid):<8} {why}")
        if result.get("detail"):
            print(f"  {result['detail']}")
        print(c("\n  → notify everyone + offer external search (associations, aides-soignants)", "33"))
        return

    rows = [r for r in result["assignments"] if not only_changes or r["changed"] or r["new"]]
    print(f"\n  {'When':<23} {'Activity':<28} {'Caregiver':<9} Change")
    print("  " + "─" * 76)
    for r in rows:
        if r["changed"]:
            tag = c(f"moved from {names[r['previous']]}", "33")
        elif r["new"]:
            tag = c("new", "32")
        else:
            tag = c("kept", "2")
        who = names[r["caregiver"]]
        print(f"  {_when(r['start'], r['end']):<23} {r['title'][:27]:<28} {c(f'{who:<9}', '1')} {tag}")

    print_loads(result["loads"], names, before=before)
    n_changed = sum(r["changed"] for r in result["assignments"])
    print(f"\n  Spread (max - min load): {result['spread']}   ·   reassignments: {n_changed}")


def print_loads(loads: dict[str, float], names: dict[str, str], before: dict | None = None) -> None:
    print("\n  Load over the month (weight × hours)")
    top = max(loads.values()) or 1
    for cid, val in loads.items():
        bar = "█" * round(24 * val / top)
        prev = f"  (was {before[cid]})" if before else ""
        print(f"    {names[cid]:<8} {c(bar, '36'):<24} {val:>6.2f}{prev}")


def print_notifications(result: dict, names: dict[str, str]) -> None:
    """What the AI orchestrator would send (one proposal per change)."""
    todo = [r for r in result["assignments"] if r["changed"] or r["new"]]
    if not todo:
        print("\n  No notification to send.")
        return
    print(c("\n  Notifications to send", "1"))
    for r in todo:
        note = f", note : {r['notes']}" if r["notes"] else ""
        print(f"    → {names[r['caregiver']]:<7} « {r['title']}, {DAYS_FR[r['start'].weekday()]} "
              f"{r['start']:%d/%m} {r['start']:%Hh%M}-{r['end']:%Hh%M}{note}. Accepter / Refuser »")
