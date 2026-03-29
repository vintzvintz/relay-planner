# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running tests

```bash
source venv/Scripts/activate
pytest tests/
```

Unit tests live in `tests/`. Each test file covers one module or feature (e.g. `test_relay_constraints.py`, `test_pauses.py`). Add new tests there, named `test_<feature>.py`. Shared fixtures go in `tests/conftest.py`.

The solver integration tests (`TestSolverRespects*`) use a short `timeout_sec` and a minimal problem to stay fast.

## Running the solver

```bash
source venv/Scripts/activate
python example.py
```

The solver runs up to a fixed timeout and writes timestamped `.txt`, `.csv`, `.json`, and `.html` files in `plannings/` on success.

CLI options (all via `example.py`, dispatched by `relay.entry_point()`):
```bash
python example.py              # solve (default)
python example.py --summary    # print data summary and LP upper bound
python example.py --diag       # run feasibility analyser
python example.py --model      # build model only (no solve)
python example.py --replanif ref.json              # replanify: minimise distance to reference
python example.py --replanif ref.json --min-score 88  # replanify with minimum score constraint
```

## Environment

- Python venv at `venv/` (Python 3.13, ortools CP-SAT)
- VSCode launch config uses `venv/bin/python` directly (no activation needed from IDE)
- All scripts must be run from the project root (imports assume `relay` package and `example.py` are on the path)

## Architecture

The project solves a relay race scheduling problem: Lyon→Fessenheim, 440 km, ~176 segments (2.5 km/segment), ~9 km/h, departing Wednesday 15h00. 15 runners must cover every segment (1 or 2 runners per segment).

**`relay/`** — Python package containing the core solver modules. Public API exported from `relay/__init__.py` with normalized names (`relay.Constraints`, `relay.Model`, `relay.Solver`, `relay.Solution`, etc.) — internal modules now use these same names directly (no alias layer). No internal module has a `__main__` block — all CLI entry points go through `relay.entry_point()`.

**`example.py`** — Problem constants, runner data, and entry point:
- Relay-type string constants imported from `relay`: `R10`, `R15`, `R20`, `R30`, `R13_F`, `R15_F`
- Declarative API: `c = Constraints(...)`, then `c.new_runner(name)` → `RunnerBuilder`, then `runner.set_options(...)` and `runner.add_relay(size, nb=, window=, pinned=)`
- `c.new_relay(size)` → `SharedLeg`: pass to two runners' `add_relay()` to force a binôme
- `Intervals([(start, end), ...])`: named availability/window objects in **active** segment indices; `c.hour_to_seg(h, jour=)` and `c.km_to_seg(km)` return active segment indices; `c.last_active_seg` is the upper bound for "until the end"; `c.night_windows()` returns all nocturnal intervals in active indices
- `python example.py` delegates to `relay.entry_point(c)` which dispatches `--summary`, `--diag`, `--model`, `--replanif`, or default solve
- See [CONSTRAINTS.md](CONSTRAINTS.md) for the full constraint declaration API reference

**`relay/constraints.py`** — `Constraints` class and supporting types (also defines relay-type constants):
- Relay-type string constants: `R10`, `R15`, `R20`, `R30`, `R13_F`, `R15_F` — pass to `add_relay()` as `size`
- `make_relay_types(nb_segments, total_km, enable_flex)` — computes segment-count sets per relay type; called internally by `Constraints.__init__`
- `Constraints.__init__`: accepts `total_km`, `nb_segments`, `speed_kmh`, `start_hour`, `compat_matrix`, `solo_max_km`, `solo_max_default`, `nuit_max_default`, `repos_jour_heures`, `repos_nuit_heures`, `nuit_debut`, `nuit_fin`, `solo_autorise_debut`, `solo_autorise_fin`, `max_same_partenaire`, `enable_flex`, `allow_flex_flex` (default `True`; if `False`, two flex runners forming a binôme are each forced to their own nominal size — no reduction allowed), `profil_csv` (optional path to altitude CSV, default `None`); `solo_autorise_debut`/`solo_autorise_fin` define the time window (hours) in which solo relays are permitted — segments outside this window set `relais_solo_interdit[r][k]=1`; pauses are declared via `add_pause()` (not via constructor); `segment_start_hour()` and `hour_to_seg()` account for cumulative pause offsets
- `add_pause(seg, duree)`: declares a planned race halt after active segment `seg` (int), with duration `duree` hours; raises `RuntimeError` if called after `new_runner()` (runtime check, not assert); inserts inactive segments into the time-space timeline; exposes `inactive_ranges`, `inactive_segments`, `active_segments`; `nb_segments` grows with each call (total time-space segments); `nb_active_segments` stays fixed
- `new_runner(name)` → `RunnerBuilder` (validates name against compat matrix; runner options set via `set_options()`)
- `new_relay(size)` → `SharedLeg` (forced binôme between two runners)
- `add_max_binomes(runner1, runner2, nb)`: limits to at most `nb` binômes between two runners across the whole planning (stored in `once_max`)
- `night_windows()` → `Intervals` covering all nocturnal segments, in **active** segment indices
- `RunnerBuilder.add_relay(size, *, nb, window, pinned)` → `self` (chainable; `size` is a relay-type string or `SharedLeg`; `window` and `pinned` accept **active** segment indices and are converted to time-space indices internally)
- `RunnerBuilder.set_options(*, solo_max, nuit_max, repos_jour, repos_nuit, max_same_partenaire)` → `self`: sets per-runner overrides (replaces former kwargs on `new_runner`)
- `RelaySpec` dataclass: `size`, `paired_with`, `window`, `pinned`
- `Coureur` dataclass: `relais`, `repos_jour`, `repos_nuit`, `solo_max`, `nuit_max`, `max_same_partenaire`
- `Intervals` dataclass: `intervals: list[tuple[int,int]]`
- Properties: `runners`, `relay_sizes`, `relay_types`, `runner_nuit_max`, `runner_solo_max`, `runner_repos_jour`, `runner_repos_nuit`, `night_segments`, `segment_km`, `segment_duration`, `paired_relays`, `solo_max_size`, `has_flex`, `solo_forbidden_segments`, `last_active_seg` (= `nb_active_segments` — upper bound for `Intervals`, replaces `nb_segments` in the declarative API), `profil` (lazy-loaded `Profile` instance from `profil_csv`, or `None`)
- Methods: `segment_start_hour(seg)` (purely linear in the time-space model), `is_night(seg)`, `is_active(seg)`, `is_compatible(r1, r2)`, `compat_score(r1, r2)`, `hour_to_seg(h, jour=0)` (returns **active** segment index — converts via `time_seg_to_active()`), `km_to_seg(km)` (returns **active** segment index directly), `active_to_time_seg(active_idx)`, `time_seg_to_active(seg)`, `duration_to_segs(hours)`, `size_of(relay_name)`, `compute_upper_bound()` (LP relaxation via GLOP — result memoized in `lp_upper_bound`, `lp_upper_bound_exact`, `lp_solo_nb`, `lp_solo_km`), `print_summary()`

**`compat.py`** — `COMPAT_MATRIX: dict[tuple[str, str], int]` — compatibility scores (0, 1, or 2) for every runner pair. Stores only the lower triangle (canonical key order from `RUNNERS`); `Constraints` reconstructs full symmetry at load time. Auto-generated by `utils/refresh_compat.py` from `compat_coureurs.xlsx`; do not edit manually.

**`relay/model.py`** — CP-SAT model builder:
- `Model`: holds the `cp_model.CpModel` instance and all CP-SAT variables:
  - `start[r][k]`, `end[r][k]`, `size[r][k]` (IntVar); for flexible runners `size` has a domain including compatible partner sizes
  - `same_relay[(r,k,rp,kp)]` (BoolVar): 1 if the pair forms a binôme (same start + same effective size)
  - `relais_solo[r][k]`, `relais_nuit[r][k]`, `relais_solo_interdit[r][k]` (BoolVar)
- `build(constraints)`: calls `_add_variables`, `_add_symmetry_breaking`, `_add_fixed_relays`, `_add_night_relay`, `_add_solo_intervals`, `_add_rest_constraints`, `_add_availability`, `_add_same_relay`, `_add_pause_constraints`, `_add_coverage`, `_add_inter_runner_no_overlap`, `_add_solo_constraints`, `_add_forced_pairings`, `_add_once_max`, `_add_max_same_partenaire`
- `_add_symmetry_breaking`: for each runner, groups identical non-pinned non-shared relays and enforces `start[r][k] <= start[r][k']` for consecutive indices — reduces search space by a factorial factor
- `_add_pause_constraints`: for each inactive range `(a, b)` in `constraints.inactive_ranges`, forbids any relay that overlaps it (enforces `end[r][k] <= a` OR `start[r][k] >= b` via a BoolVar disjunction)
- `_add_same_relay`: now also filters out pairs whose feasible start ranges don't overlap (temporal pre-filter before building BoolVars); for two fixed-size relays, only creates a `same_relay` var if they share the exact same size; `_feasible_start_ranges(spec, nb_segments)` and `_ranges_overlap()` are static helpers
- `_add_coverage`: uses a cumulative constraint (demand=1, capacity=2) plus a BoolVar per relay×active segment to enforce at least 1 runner per segment
- `_iv_index`: dict `(r, k) → interval_var` for O(1) lookup (replaces linear scans in `_add_inter_runner_no_overlap`)
- `add_optimisation_func(constraints)`: maximizes the objective expression (weighted binôme sum minus flex penalty)
- `_add_fixed_relays`: enforces `pinned` entries as equality constraints on `start`; size domain comes from the relay's set
- Objective: mixed — maximizes weighted binôme sum minus a flex penalty (`sum(sz_max - size[r][k])` over flex relays); this penalty discourages two flex runners from pairing at a size below both their maxima (double-flex binôme), since both would be penalized
- `add_minimise_differences_with(reference)`: sets the objective to minimize total distance (sum of `|start[r][k] - ref_start|`) with a reference `Solution`; used for replanning
- `add_hint(solution)`: injects CP-SAT hints (warm-start) from a `Solution`; sets hints on `start` variables
- `build_model(constraints)`: factory returning a built `Model`
- Public methods: `add_optimisation_func(constraints)`, `add_min_score(constraints, score)`, `add_minimise_differences_with(reference)`, `add_hint(solution)`

**`relay/solver.py`** — Solver:
- `Solver(model, constraints)`: wraps CP-SAT solving; `solve(timeout_sec, target_score, max_count)` is a streaming iterator that yields `Solution` objects as they are found; solver runs in a background thread; solution extraction delegated to `Solution.from_cpsat()`
- Default: `SOLVER_TIME_LIMIT=0` (unlimited), `SOLVER_NUM_WORKERS=12`

**`relay/solution.py`** — `Solution`:
- `Solution(relays, constraints, score=None)`: `relays` is a `list[dict]`; `constraints` passed explicitly; constructor runs `verifications.check()` and sets `.valid`
  - `from_cpsat(solver)` (classmethod): extracts variable values from the CP-SAT callback state, computes `rest_h` and D+/D− from `constraints.profil`, and returns a `Solution`; signature takes the callback only (model and constraints accessed via `solver._relay_model` / `solver._constraints`)
  - `from_json(path, constraints=None)` (classmethod): loads a JSON solution; returns a `Solution` (with `valid=None` if `constraints` is omitted)
  - `to_csv(filename)` / `to_json(filename)` / `to_html(filename)` — save to file
  - `save()` — saves timestamped `.txt`, `.csv`, `.json`, `.html` in `plannings/` and prints stats
  - `stats()` → `(score, n_binomes, n_solos, km_solos, n_flex, n_pinned, km_flex)` — `score` is the recalculated objective value; `km_flex` is km saved by flex relays running shorter than nominal
  - `to_text()` → full text planning (chrono + per-runner recap)
- HTML output includes a Gantt-style grid per runner (colour-coded: green=binôme, pink=solo, blue=fixed relay, grey=mandatory rest, purple=unavail) with 6h time markers; runners sorted alphabetically
- `_build_gantt()`: dedicated method returning `(header_row, rows_html)` for the Gantt table; CSS factored into classes (no inline styles)

**`relay/profil.py`** — Altitude profile for the race route:
- `Profile(distances, altitudes)`: interpolates altitude along the route (binary search + linear interpolation)
  - `denivele(km_deb, km_fin) -> (d_plus, d_moins)`: integrates positive and negative elevation change between two kilometre marks; iterates directly over CSV profile points in the interval
- `load_profile(filename=DEFAULT_PROFILE) -> Profile`: loads `gpx/altitude.csv` (semicolon-separated distance/altitude pairs, one point per 100 m); skips comment lines starting with `;`
- `DEFAULT_PROFILE = "gpx/altitude.csv"`
- Used via `constraints.profil` (lazy-loaded from `profil_csv` constructor arg); `Solution.from_cpsat()` calls `profil.denivele()` to fill `d_plus`/`d_moins` in each relay dict

**`relay/__init__.py`** — package-level convenience functions:
- `replanif(constraints, *, reference, min_score=None, timeout_sec=0)`: loads a reference JSON, builds the model with `add_minimise_differences_with()`, optionally adds `add_min_score()`, then solves and saves
- `solve(constraints, *, timeout_sec=0)`: builds model, sets objective, solves, and saves each solution found
- `entry_point(constraints)`: CLI dispatcher — parses `sys.argv` for `--summary`, `--diag`, `--model`, `--replanif <file> [--min-score <n>]`, or defaults to `solve()`
- Exports: `Constraints`, `Intervals`, `RunnerBuilder`, `SharedLeg`, `Model`, `model`, `Solver`, `Solution`, `FeasibilityAnalyser`, `diagnose`, `solve`, `replanif`, `entry_point`

**`relay/feasibility.py`** — `FeasibilityAnalyser` for systematic infeasibility diagnosis:
- Builds partial models, disabling constraint families one at a time
- `analyse(constraints)` (aliased as `relay.diagnose()`) — shortcut entry point

**`relay/verifications.py`** — post-solve verification suite:
- `check(solution, constraints)`: validates coverage, relay sizes, rest constraints, night/solo limits, pairings, compatibility, and pause boundary crossings (`_check_pauses`)

**`replanif/replanif.py`** — Replanning script: same problem declaration as `example.py`, but delegates to `entry_point()` with `--replanif <file.json> [--min-score <n>]`. The reference solution (`replanif/solution_reference.json`) lives alongside it.

**`utils/refresh_compat.py`** — regenerates `compat.py` from `compat_coureurs.xlsx`:
- Validates matrix structure (square, symmetric, diagonal=`X`, lower triangle only)
- Run after modifying the Excel file

**`old/`** — Legacy scripts (unmaintained, imports may be broken):
- `enumerate.py` — 3-phase solution enumerator
- `analyze_solutions.py` — per-runner histograms and HTML synthesis
- `reformat.py` — regenerate HTML from JSON solutions
- `check_configs_unique.py` — verify distinct binôme configurations
- `find_duplicate_solutions.py` — detect identical JSON solutions

## Key modeling details

- **Time-space model**: the segment timeline mixes active segments (race) and inactive segments (pauses). `nb_segments` is the total time-space length; `nb_active_segments` is the fixed count of race segments. All CP-SAT variables (`start`, `end`) use time-space indices; coverage constraints iterate over `active_segments` only.
- Segments are 0-indexed; active segment `s` covers km `time_seg_to_active(s) * segment_km`; `segment_start_hour(seg)` is purely linear (`start_hour + seg * segment_duration`) in the time-space model
- Pauses are encoded as `inactive_ranges`: contiguous blocks of inactive segments inserted into the timeline. Rest constraints need no pause credit — the gap `end[ka]` to `start[kb]` in time-space automatically spans any intervening pause.
- Two runners form a binôme if same effective relay size AND same start segment AND `compat_score > 0`: both flex and fixed runners can pair together; when two flex runners pair, the model allows any size in the intersection of their domains, but the flex penalty in the objective penalizes each runner running below their nominal size, making double-flex binômes at sub-maximal size costly; with `allow_flex_flex=False`, each runner in a flex+flex binôme is instead hard-constrained to its own nominal size (`max` of its domain)
- Incompatible pairs (or pairs with no `same_relay` var) are forced disjoint via `add_no_overlap`
- Solo relays are forbidden outside the `solo_autorise_debut`/`solo_autorise_fin` time window: `_add_solo_intervals` sets `relais_solo_interdit[r][k]=1` for segments outside this window, and `_add_solo_constraints` enforces `relais_solo[r][k] + relais_solo_interdit[r][k] <= 1`
- Flexible runners in solo are forced to the nominal size (`max` of their size set)
- Symmetry breaking: for identical non-pinned relays of the same runner, `start[r][k] <= start[r][k']` is enforced, reducing the search space by a factorial factor
- Solver time limit: unlimited by default (`SOLVER_TIME_LIMIT=0` in relay/solver.py); configurable via `timeout_sec` parameter in `solve()` / `Solver.solve()`

## Commit instructions
- **DO NOT ADD** 'CoAuthored by:' footers or any other promotional content in commit messages
