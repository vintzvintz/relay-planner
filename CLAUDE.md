# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running tests

```bash
source venv/bin/activate
pytest tests/
```

Unit tests live in `tests/`. Each test file covers one module or feature (e.g. `test_relay_constraints.py`, `test_pauses.py`). Add new tests there, named `test_<feature>.py`. Shared fixtures go in `tests/conftest.py`.

The solver integration tests (`TestSolverRespects*`) use a short `timeout_sec` and a minimal problem to stay fast.

## Running the solver

```bash
source venv/bin/activate
python solver.py
```

The solver runs up to a fixed timeout and writes timestamped `.txt`, `.csv`, `.json`, and `.html` files in `plannings/` on success.

To check data consistency:
```bash
python data.py
```

## Environment

- Python venv at `venv/` (Python 3.13, ortools CP-SAT)
- VSCode launch config uses `venv/bin/python` directly (no activation needed from IDE)
- All scripts must be run from the project root (imports assume `data.py` is on the path)

## Architecture

The project solves a relay race scheduling problem: Lyon→Fessenheim, 440 km, ~176 segments (2.5 km/segment), ~9 km/h, departing Wednesday 15h00. 15 runners must cover every segment (1 or 2 runners per segment).

**`data.py`** — Problem constants, runner data, and entry point:
- Relay-type string constants imported from `constraints.py`: `R10`, `R15`, `R20`, `R30`, `R13_F`, `R15_F`
- Declarative API: `c = RelayConstraints(...)`, then `c.new_runner(name)` → `RunnerBuilder`, then `runner.set_options(...)` and `runner.add_relay(size, nb=, window=, pinned=)`
- `c.new_relay(size)` → `SharedRelay`: pass to two runners' `add_relay()` to force a binôme
- `RelayIntervals([(start, end), ...])`: named availability/window objects; `c.hour_to_seg(h, jour=)` converts hours to segment index; `c.night_windows()` returns all nocturnal intervals
- `build_constraints()`: returns the module-level `RelayConstraints` object; `python data.py` prints a full summary
- See [CONSTRAINTS.md](CONSTRAINTS.md) for the full constraint declaration API reference

**`constraints.py`** — `RelayConstraints` class and supporting types (also defines relay-type constants):
- Relay-type string constants: `R10`, `R15`, `R20`, `R30`, `R13_F`, `R15_F` — pass to `add_relay()` as `size`
- `make_relay_types(nb_segments, total_km, enable_flex)` — computes segment-count sets per relay type; called internally by `RelayConstraints.__init__`
- `RelayConstraints.__init__`: accepts `total_km`, `nb_segments`, `speed_kmh`, `start_hour`, `compat_matrix`, `solo_max_km`, `solo_max_default`, `nuit_max_default`, `repos_jour_heures`, `repos_nuit_heures`, `nuit_debut`, `nuit_fin`, `solo_autorise_debut`, `solo_autorise_fin`, `max_same_partenaire`, `enable_flex`, `allow_flex_flex` (default `True`; if `False`, two flex runners forming a binôme are each forced to their own nominal size — no reduction allowed); `solo_autorise_debut`/`solo_autorise_fin` define the time window (hours) in which solo relays are permitted — segments outside this window set `relais_solo_interdit[r][k]=1`; pauses are declared via `add_pause()` (not via constructor); `segment_start_hour()` and `hour_to_seg()` account for cumulative pause offsets
- `add_pause(seg, duree)`: declares a planned race halt at segment boundary `seg` (int) with duration `duree` hours; must be called before `new_runner()`; computes and appends to `pause_segments`, `pause_hours`, `pause_duration_hours`, `pause_seg_durations`; also exposes `segment_end_hour(seg)` which excludes pauses starting at `seg`
- `new_runner(name)` → `RunnerBuilder` (validates name against compat matrix; runner options set via `set_options()`)
- `new_relay(size)` → `SharedRelay` (forced binôme between two runners)
- `add_max_binomes(runner1, runner2, nb)`: limits to at most `nb` binômes between two runners across the whole planning (stored in `once_max`)
- `night_windows()` → `RelayIntervals` covering all nocturnal segments
- `RunnerBuilder.add_relay(size, *, nb, window, pinned)` → `self` (chainable; `size` is a relay-type string or `SharedRelay`)
- `RunnerBuilder.set_options(*, solo_max, nuit_max, repos_jour, repos_nuit, max_same_partenaire)` → `self`: sets per-runner overrides (replaces former kwargs on `new_runner`)
- `RelaySpec` dataclass: `size`, `paired_with`, `window`, `pinned`
- `Coureur` dataclass: `relais`, `repos_jour`, `repos_nuit`, `solo_max`, `nuit_max`, `max_same_partenaire`
- `RelayIntervals` dataclass: `intervals: list[tuple[int,int]]`
- Properties: `runners`, `relay_sizes`, `relay_types`, `runner_nuit_max`, `runner_solo_max`, `runner_repos_jour`, `runner_repos_nuit`, `night_segments`, `segment_km`, `segment_duration`, `paired_relays`, `solo_max_size`
- Methods: `segment_start_hour(seg)`, `is_night(seg)`, `is_compatible(r1, r2)`, `compat_score(r1, r2)`, `hour_to_seg(h, jour=0)`, `duration_to_segs(hours)`, `km_to_seg(km)`, `size_of(relay_name)`, `compute_upper_bound()` (LP relaxation via GLOP — result memoized in `lp_upper_bound`, `lp_upper_bound_exact`, `lp_solo_nb`, `lp_solo_km`), `print_summary()`

**`compat.py`** — `COMPAT_MATRIX: dict[tuple[str, str], int]` — compatibility scores (0, 1, or 2) for every runner pair. Stores only the lower triangle (canonical key order from `RUNNERS`); `RelayConstraints` reconstructs full symmetry at load time. Auto-generated by `refresh_compat.py` from `compat_coureurs.xlsx`; do not edit manually.

**`model.py`** — CP-SAT model builder:
- `RelayModel`: holds the `cp_model.CpModel` instance and all CP-SAT variables:
  - `start[r][k]`, `end[r][k]`, `size[r][k]` (IntVar); for flexible runners `size` has a domain including compatible partner sizes
  - `same_relay[(r,k,rp,kp)]` (BoolVar): 1 if the pair forms a binôme (same start + same effective size)
  - `relais_solo[r][k]`, `relais_nuit[r][k]`, `relais_solo_interdit[r][k]` (BoolVar)
- `build(constraints)`: calls `_add_variables`, `_add_fixed_relays`, `_add_night_relay`, `_add_solo_intervals`, `_add_rest_constraints`, `_add_availability`, `_add_same_relay`, `_add_pause_constraints`, `_add_coverage`, `_add_inter_runner_no_overlap`, `_add_solo_constraints`, `_add_forced_pairings`, `_add_once_max`, `_add_max_same_partenaire`
- `_add_pause_constraints`: for each pause boundary `ps` in `constraints.pause_segments`, forbids any relay that spans it (enforces `end[r][k] <= ps` OR `start[r][k] >= ps` via a BoolVar disjunction)
- `_add_same_relay`: now also filters out pairs whose feasible start ranges don't overlap (temporal pre-filter before building BoolVars); for two fixed-size relays, only creates a `same_relay` var if they share the exact same size; `_feasible_start_ranges(spec, nb_segments)` and `_ranges_overlap()` are static helpers
- `_add_coverage`: dispatches to `_add_coverage_fixed` (sum of sizes = nb_segments + overlap; exact, fast) when all relay sizes are fixed; otherwise falls back to `_add_coverage_flex` (BoolVar per relay×segment)
- `_iv_index`: dict `(r, k) → interval_var` for O(1) lookup (replaces linear scans in `_add_inter_runner_no_overlap`)
- `add_optimisation_func(constraints, name=None)`: when `name` is `None`, defaults to `OPTIM_FUNC_BASIQUE` if `enable_flex=False`, else `OPTIM_FUNC_MIXTE`
- `_add_fixed_relays`: enforces `pinned` entries as equality constraints on `start`; size domain comes from the relay's set
- Objective: mixed — maximizes weighted binôme sum (`_weighted_binome_sum`) minus a flex penalty (`sum(sz_max - size[r][k])` over flex relays); this penalty discourages two flex runners from pairing at a size below both their maxima (double-flex binôme), since both would be penalized
- `build_model(constraints)`: factory returning a built `RelayModel`
- Public methods: `add_optimisation_func(constraints, name)`, `add_min_score(constraints, name, score)`

**`solver.py`** — Solver and solution builder:
- `build_solution(model, constraints, solver) -> RelaySolution`: extracts variable values, computes `rest_h` (rest time in hours after each relay), and constructs a `RelaySolution`; `fixe` flag set when `pinned` is not None
- `RelaySolver(model, constraints)`: wraps CP-SAT solving; `solve(timeout_sec, target_score, max_count)` is a streaming iterator that yields `RelaySolution` objects as they are found; solver runs in a background thread
- `relay_model.add_optimisation_func(constraints, name=OPTIM_FUNC_MIXTE)` sets the objective on the model before solving
- Default: `SOLVER_TIME_LIMIT=5*3600s`, `SOLVER_NUM_WORKERS=12`

**`solution.py`** — `RelaySolution(relais_list, constraints, score=None)`:
- Constructor runs `verifications.check()` and sets `.valid`
- `stats()` → `(n_binomes, n_solos, km_solos, n_flex, n_fixes, km_flex)` — `km_flex` is km saved by flex relays running shorter than nominal
- `to_text()` → full text planning (chrono + per-runner recap)
- `to_csv(filename)` / `to_json(filename)` / `to_html(filename)` — save to file
- `save(verbose=STATS)` — saves timestamped `.txt`, `.csv`, `.json`, `.html` in `plannings/`; verbosity levels: `QUIET=0`, `STATS=1`, `DETAIL=2`
- HTML output includes a Gantt-style grid per runner (colour-coded: green=binôme, pink=solo, blue=fixed relay, grey=mandatory rest, purple=unavail) with 6h time markers; runners sorted alphabetically
- `_build_gantt()`: dedicated method returning `(header_row, rows_html)` for the Gantt table; CSS factored into classes (no inline styles)

**`enumerate.py`** — 3-phase solution enumerator:
- Phase 1: finds the best achievable score (skipped if `SCORE_MINIMAL` is set)
- Phase 2: enumerates up to `MAX_CONFIGS` distinct binôme configurations at that score using `add_config_exclusion_cut`
- Phase 3: for each configuration, enumerates up to `MAX_PER_CONFIG` distinct placements using `add_schedule_exclusion_cut`
- Each solution saved as `.csv`, `.json`, `.html` in `enumerate_solutions/` (named `run_<ts>_config_NNN_place_NN`)
- Calls `analyze_solutions.main()` at the end; Ctrl+C stops gracefully at each phase

**`verifications.py`** — post-solve verification suite:
- `check(solution, constraints)`: validates coverage, relay sizes, rest constraints, night/solo limits, pairings, compatibility, and pause boundary crossings (`_check_pauses`)

**`refresh_compat.py`** — regenerates `compat.py` from `compat_coureurs.xlsx`:
- Validates matrix structure (square, symmetric, diagonal=`X`, lower triangle only)
- Run after modifying the Excel file

**`analyze_solutions.py`** — loads `.json` files from `enumerate_solutions/`, generates per-runner histograms (PNG) and HTML pages, plus a synthesis and diversity page. Outputs to `explore_solutions/`. Reads `RelayConstraints` directly.

**`utils/check_configs_unique.py`** — verifies that all phase-2 binôme configurations in `enumerate_solutions/` are distinct (loads `place_00.json` fingerprints). Optional `run_ts` argument to filter a specific run.

**`utils/find_duplicate_solutions.py`** — detects identical JSON solutions in `enumerate_solutions/` using a canonical SHA-256 hash (order-insensitive, binôme pairs normalized).

**`utils/reformat.py`** — reloads the most recent JSON solution from `plannings/` and regenerates the HTML. Accepts an optional path argument.

## Key modeling details

- Segments are 0-indexed; segment `s` covers km `s * segment_km` to `(s+1) * segment_km`
- Two runners form a binôme if same effective relay size AND same start segment AND `compat_score > 0`: both flex and fixed runners can pair together; when two flex runners pair, the model allows any size in the intersection of their domains, but the flex penalty in the objective penalizes each runner running below their nominal size, making double-flex binômes at sub-maximal size costly; with `allow_flex_flex=False`, each runner in a flex+flex binôme is instead hard-constrained to its own nominal size (`max` of its domain)
- Incompatible pairs (or pairs with no `same_relay` var) are forced disjoint via `add_no_overlap`
- Solo relays are forbidden outside the `solo_autorise_debut`/`solo_autorise_fin` time window: `_add_solo_intervals` sets `relais_solo_interdit[r][k]=1` for segments outside this window, and `_add_solo_constraints` enforces `relais_solo[r][k] + relais_solo_interdit[r][k] <= 1`
- Flexible runners in solo are forced to the nominal size (`max` of their size set)
- Solver time limit: 5h (solver.py) / configurable per phase in enumerate.py

## Commit instructions
- **DO NOT ADD** 'CoAuthored by:' footers or any other promotional content in commit messages
