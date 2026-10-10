# Nello – caregiver assignment optimizer (hackathon MVP)

The "schedule optimization" box of the Nello flow: given the dependent's shared
agenda and each caregiver's personal agenda, assign one caregiver per activity,
balancing the weighted load over the month and keeping reassignments to a minimum.

## Run

```bash
pip install -r requirements.txt
python run_demo.py          # full 3-step scenario, regenerates data/
python optimizer.py         # one optimization on the current data/ files
```

## Files

| File | Role |
|---|---|
| `optimizer.py` | PuLP model: `load_problem()` reads the files, `optimize()` returns a dict |
| `ics_utils.py` | minimal .ics reader/writer (no external dependency) |
| `generate_demo_data.py` | builds `data/` (config + 5 .ics, one month) |
| `display.py` | console tables, load bars, notification texts |
| `run_demo.py` | step 1 balance the month · step 2 Luc's message · step 3 impossible IRM |

## Data contract

**Shared agenda** (`data/shared_dependent.ics`), one VEVENT per activity:

| Property | Meaning |
|---|---|
| `DTSTART` / `DTEND` | fixed times |
| `SUMMARY` | title (also used to match the copy in a personal agenda) |
| `CATEGORIES` | activity type, sets the load weight |
| `DESCRIPTION` | free note, copied into the notification |
| `X-NELLO-REQUIRES` | hard requirements, e.g. `car` |
| `X-NELLO-CAREGIVER` | current caregiver id (empty = unassigned) |

**Personal agendas** (`data/caregivers/<id>.ics`): every event is busy, except
an event with the same title and start time as a shared activity.

**`config.json`**: caregivers (`id`, `name`, `capabilities`, `dislikes`,
optional `max_load`) and `weights` per activity type.

## Model

```
x[c,a] ∈ {0,1}                         only for eligible pairs
Σ_c x[c,a] = 1                          every activity accompanied
x[c,a1] + x[c,a2] ≤ 1                   a1, a2 overlap
load[c] = Σ w(type)·hours·x[c,a]        ≤ max_load[c] if set
Lmin ≤ load[c] ≤ Lmax
min (Lmax − Lmin) + 0.5·#reassignments + 0.001·Lmax
```

Eligible = free during the activity, has every required tag, type not in
`dislikes`, not in `excluded`.

## Output of `optimize()`

- `status: "ok"` → `assignments` (caregiver, start, end, notes, `changed`, `new`),
  `loads`, `spread`
- `status: "conditions not met"` → `unassignable`, with the reason for each caregiver

## Hooks for later

- **Rejection loop:** `optimize(..., excluded={activity_uid: [caregiver_id]})`
  already removes a caregiver from one activity.
- **Different caps:** set `max_load` per caregiver in the config.

Note: PuLP 4 changed its API and dropped the bundled CBC solver, hence `pulp<3`.
