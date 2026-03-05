# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the solver

```bash
source venv/bin/activate
python solver.py
```

The solver runs for up to 30 seconds and writes a timestamped `planning_YYYYMMDD_HHMMSS.txt` file on success.

To check data consistency:
```bash
python data.py
```

To debug constraint feasibility incrementally:
```bash
python debug_faisabilite.py
```

## Environment

- Python venv at `venv/` (Python 3.13, ortools CP-SAT)
- VSCode launch config uses `venv/bin/python` directly (no activation needed from IDE)
- All scripts must be run from the project root (imports assume `data.py` is on the path)

## Architecture

The project solves a relay race scheduling problem: Lyon→Fessenheim, 440 km, 88 segments of 5 km, ~9 km/h, departing Wednesday 15h00. 14 runners must cover every segment (1 or 2 runners per segment).

**`data.py`** — All problem constants and derived data:
- `RUNNER_RELAYS`: dict mapping runner name → list of relay sizes in segments (expanded from `RUNNERS_RAW`)
- `RUNNERS_RAW`: raw engagements per runner as `[(km, count), ...]`
- `FLEXIBLE_RUNNERS`: set of runners whose relay sizes can be reduced
- `UNAVAILABILITY`: dict of per-runner exclusion windows `[(start_seg, end_seg), ...]`; absent = always available
- `COMPATIBLE`: symmetric dict of who can run together (binôme eligibility)
- `MANDATORY_PAIRS`: pairs that must share at least one relay
- `MULTI_NIGHT_ALLOWED`: runners exempt from the "at most 1 night relay" rule
- `OLIVIER_NIGHT1`, `OLIVIER_NIGHT2`: fixed night windows (0h–2h thu/fri) for Olivier's 30km relays; Alexis forced to same starts
- Time is measured in **segments** (1 seg = 5 km ≈ 33 min); `segment_start_hour(seg)` converts to hours from midnight Wednesday; `hour_to_seg(h)` converts hours-from-start to segment index

**`solver.py`** — CP-SAT model, broken into private `_add_*` functions:
1. Variables: `start[r][k]`, `end[r][k]` (segment index), interval vars
2. No-overlap intra-runner
3. `night_relay[r][k]` bool vars + at-most-1-night constraint
4. Rest constraints: REST_NORMAL=13 segs (7h) after day relay, REST_NIGHT=17 segs (9h) after night relay
5. Availability windows
6. `same_relay[(r,k,rp,kp)]` bool: 1 if two runners share exact same interval (binôme); 0 forces them disjoint
7. Coverage: every segment covered by ≥1 relay; cumulative capacity ≤2
8. Inter-runner no-overlap for incompatible pairs
9. `relais_solo[r][k]` bool + at-most-1-solo constraint
10. Mandatory pairs enforcement
- **Objective**: maximize number of `same_relay` vars = maximize binômes (paired relays)

**`print_solution.py`** — Display and verification after solving. Imported by `solver.py`. Also lives as a copy in `.vscode/print_solution.py` (used for IDE tooling).

**`debug_faisabilite.py`** — Standalone script that activates constraints one by one to isolate infeasibility.

## Key modeling details

- Segments are 0-indexed; segment `s` covers km `s*5` to `(s+1)*5`
- Two runners form a binôme only if same size relay AND same start segment AND listed in `COMPATIBLE`
- Incompatible pairs or different-size relays are forced disjoint via `add_no_overlap`
- Olivier's two 30km relays are pinned to specific night windows; Alexis is forced to the same start

## Commit instructions
- **DO NOT ADD** 'CoAuthored by:' footers or any other promotional content in commit messages
