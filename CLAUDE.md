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
- `Coureur` dataclass: holds per-runner data — `relais` (list of relay sizes in segments), `compatible` (set of partner names), `dispo` (availability windows, empty = always available), `pinned_segments` (windows the runner must cover), `repos_jour`/`repos_nuit` (rest durations, per-runner overridable), `solo_max`, `nuit_max`, `flexible` (can shrink relay to match a non-flexible partner)
- `RUNNERS_DATA`: `dict[str, Coureur]` — single source of truth for all runner parameters (replaces separate `RUNNER_RELAYS`, `PARTIAL_AVAILABILITY`, `COMPATIBLE`, `MULTI_NIGHT_ALLOWED`, `PINNED_RUNNERS`, `FLEXIBLE_RUNNERS`)
- `MATCHING_CONSTRAINTS`: dict with keys `"pinned_binomes"` (list of `(r1, r2, start_seg, end_seg)`), `"pair_at_least_once"`, `"pair_at_most_once"` (replaces `PINNED_BINOMES` and `MANDATORY_PAIRS`)
- `ENABLE_FLEXIBILITY`: feature flag — when `True`, flexible runners can reduce relay size to form a binôme with a non-flexible partner; `MIN_RELAY_SIZE` sets the minimum allowed size
- `SOLO_MAX_DEFAULT`, `NUIT_MAX_DEFAULT`: global defaults (overridable per runner in `Coureur`)
- Time is measured in **segments** (1 seg = 5 km ≈ 33 min); `segment_start_hour(seg)` converts to hours from midnight Wednesday; `hour_to_seg(h)` converts hours-from-start to segment index
- `print_summary()`: prints a full human-readable summary of input data (runners, compatibilities, availability, constraints, upper bound)

**`constraint_model.py`** — CP-SAT model builder, broken into private `_add_*` functions:
1. Variables: `start[r][k]`, `end[r][k]`, `size[r][k]` (segment index / relay size); for flexible runners `size` is a CP-SAT int var with a reduced domain, otherwise a constant
2. No-overlap intra-runner
3. `night_relay[r][k]` bool vars + per-runner `nuit_max` constraint
4. Rest constraints: per-runner `repos_jour`/`repos_nuit` (defaults REST_NORMAL=13 segs, REST_NIGHT=17 segs)
5. Availability windows + pinned binômes + pinned runners (all read from `RUNNERS_DATA` / `MATCHING_CONSTRAINTS`)
6. `same_relay[(r,k,rp,kp)]` bool: 1 if two runners share same start AND same effective size (binôme); 0 forces disjoint; flexible×non-flexible binômes add a `size[flexible][k] == sz_partner` constraint
7. Coverage: every segment covered by ≥1 relay; cumulative capacity ≤2; flexible-size relays use auxiliary bool decomposition
8. Inter-runner no-overlap for incompatible pairs
9. `relais_solo[r][k]` bool + per-runner `solo_max` constraint; flexible runners in solo are forced to their declared size
10. `_add_no_solo_runners`: enforces `solo_max == 0` (solo forbidden) per runner
11. `pair_at_least_once` / `pair_at_most_once` enforcement (replaces `_add_mandatory_pairs`)

**`solver.py`** — Runs the CP-SAT solver with objective: maximize number of `same_relay` vars (binômes). Imports `constraint_model` and `solution_formatter`.

**`solution_formatter.py`** — Display and verification after solving. Saves `.txt`, `.csv`, and `.html` outputs (the HTML includes a visual Gantt-style grid per runner). Imported by `solver.py` and `enumerate_optimal_solutions.py`.

**`enumerate_optimal_solutions.py`** — Enumerates all optimal solutions in two phases: collect all distinct binôme configurations, then enumerate placements per configuration. Solutions are saved as CSV only (no `.txt`), named `run_<timestamp>_config_NNN_place_NN.csv`. Duplicate-placement detection uses no-good cuts refactored into `_add_cut()`. Tunable constants: `OPTIMAL_BINOMES_NUM`, `TIME_LIMIT_FIRST`, `TIME_LIMIT_ENUM`, `MAX_PER_CONFIG`, `MAX_CONFIGS`.

**`find_duplicate_solutions.py`** — Detects duplicate CSV solutions in `enumerate_solutions/` using a canonical SHA-256 hash (order-insensitive, binôme-pair-normalised).

**`analyze_solutions.py`** — Reads CSV solutions from `enumerate_solutions/` and generates per-runner histograms and HTML pages in `explore_solutions/`.

**`upper_bound.py`** — Computes an analytical upper bound on the number of binômes (bipartite matching + coverage constraint).

**`debug_faisabilite.py`** — Standalone script that activates constraints one by one to isolate infeasibility.

## Key modeling details

- Segments are 0-indexed; segment `s` covers km `s*5` to `(s+1)*5`
- Two runners form a binôme if same effective relay size AND same start segment AND listed as compatible: for flexible runners, their `size` CP-SAT var is constrained to match the partner's fixed size
- Incompatible pairs or non-overlapping sizes are forced disjoint via `add_no_overlap`
- All runner-specific constraints (rest, night limit, solo limit, availability, flexibility) live in `Coureur` fields in `RUNNERS_DATA`; `MATCHING_CONSTRAINTS` holds cross-runner constraints
- `solution_formatter.formatte_html()` generates an HTML planning with a per-runner Gantt grid, colour-coded by relay type (binôme/solo/repos/indispo), with day/time markers every 6h
- Stats footer reports total km of solo relays in addition to count
- Solver time limit: 180 s; enumerate time limits configurable in `enumerate_optimal_solutions.py`
- `analyze_solutions.py` now reads `run_*_config_*.csv` glob pattern (updated from `config_*.csv`)

## Commit instructions
- **DO NOT ADD** 'CoAuthored by:' footers or any other promotional content in commit messages
