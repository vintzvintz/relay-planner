# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the solver

```bash
source venv/bin/activate
python solver.py
```

The solver runs for up to 180 seconds and writes timestamped `.txt`, `.csv`, and `.html` files in `plannings/` on success.

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
- `RUNNER_RELAYS`: dict mapping runner name → list of relay sizes in segments (direct, no longer expanded from `RUNNERS_RAW`)
- `FLEXIBLE_RUNNERS`: set of runners whose relay sizes can be reduced (not implemented in solver)
- `PARTIAL_AVAILABILITY`: dict of per-runner availability windows `[(start_seg, end_seg), ...]`; absent = always available (replaces old `UNAVAILABILITY` exclusion windows — now uses inclusion windows)
- `PINNED_BINOMES`: list of `((r1, r2), [start_seg, end_seg])` — forces a pair to share a relay covering that window (replaces `OLIVIER_NIGHT1`/`OLIVIER_NIGHT2` hard-coding)
- `PINNED_RUNNERS`: list of `(runner, [start_seg, end_seg])` — forces a single runner to have a relay covering that window
- `COMPATIBLE`: symmetric dict of who can run together (binôme eligibility); checked at import via `check_compatible_symmetric()`
- `MANDATORY_PAIRS`: pairs that must share at least one relay
- `MULTI_NIGHT_ALLOWED`: runners exempt from the "at most 1 night relay" rule
- Time is measured in **segments** (1 seg = 5 km ≈ 33 min); `segment_start_hour(seg)` converts to hours from midnight Wednesday; `hour_to_seg(h)` converts hours-from-start to segment index

**`constraint_model.py`** — CP-SAT model builder, broken into private `_add_*` functions:
1. Variables: `start[r][k]`, `end[r][k]` (segment index), interval vars
2. No-overlap intra-runner
3. `night_relay[r][k]` bool vars + at-most-1-night constraint
4. Rest constraints: REST_NORMAL=13 segs (7h) after day relay, REST_NIGHT=17 segs (9h) after night relay
5. Partial availability windows (inclusion-based) + pinned binômes + pinned runners
6. `same_relay[(r,k,rp,kp)]` bool: 1 if two runners share exact same interval (binôme); 0 forces them disjoint
7. Coverage: every segment covered by ≥1 relay; cumulative capacity ≤2
8. Inter-runner no-overlap for incompatible pairs
9. `relais_solo[r][k]` bool + at-most-1-solo constraint
10. Mandatory pairs enforcement

**`solver.py`** — Runs the CP-SAT solver with objective: maximize number of `same_relay` vars (binômes). Imports `constraint_model` and `solution_formatter`.

**`solution_formatter.py`** — Display and verification after solving. Saves `.txt`, `.csv`, and `.html` outputs (the HTML includes a visual Gantt-style grid per runner). Imported by `solver.py` and `enumerate_optimal_solutions.py`.

**`enumerate_optimal_solutions.py`** — Enumerates all optimal solutions in two phases: collect all distinct binôme configurations, then enumerate placements per configuration.

**`analyze_solutions.py`** — Reads CSV solutions from `enumerate_solutions/` and generates per-runner histograms and HTML pages in `explore_solutions/`.

**`upper_bound.py`** — Computes an analytical upper bound on the number of binômes (bipartite matching + coverage constraint).

**`debug_faisabilite.py`** — Standalone script that activates constraints one by one to isolate infeasibility.

## Key modeling details

- Segments are 0-indexed; segment `s` covers km `s*5` to `(s+1)*5`
- Two runners form a binôme only if same size relay AND same start segment AND listed in `COMPATIBLE`
- Incompatible pairs or different-size relays are forced disjoint via `add_no_overlap`
- Night pinning for Olivier+Alexis is now expressed via `PINNED_BINOMES` (generalized mechanism); `OLIVIER_NIGHT1`/`OLIVIER_NIGHT2` constants are removed
- `PARTIAL_AVAILABILITY` uses inclusion windows (runner must start within one of the listed windows); replaces the old exclusion-based `UNAVAILABILITY`
- `solution_formatter.formatte_html()` generates an HTML planning with a per-runner Gantt grid, colour-coded by relay type (binôme/solo/repos/indispo), with day/time markers every 6h
- Stats footer now reports total km of solo relays in addition to count
- Solver time limit raised to 180 s (was 60 s)

## Commit instructions
- **DO NOT ADD** 'CoAuthored by:' footers or any other promotional content in commit messages
