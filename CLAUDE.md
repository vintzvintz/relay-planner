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
python example.py --dplus      # solve maximising weighted D+/D- (requires profil_csv= and lvl= on runners)
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
- Declarative API: `c = Constraints(...)`, then `c.new_runner(name, lvl)` → `RunnerBuilder`, then `runner.set_options(...)` and `runner.add_relay(size, nb=, window=, pinned=, dplus_max=)`
- `c.new_relay(size)` → `SharedLeg`: pass to two runners' `add_relay()` to force a binôme
- `Intervals([(start, end), ...])`: named availability/window objects in **active** segment indices; `c.hour_to_seg(h, jour=)` and `c.km_to_seg(km)` return active segment indices; `c.last_active_seg` is the upper bound for "until the end"; `c.night_windows()` returns all nocturnal intervals in active indices
- `python example.py` delegates to `relay.entry_point(c)` which dispatches `--summary`, `--diag`, `--model`, `--replanif`, or default solve
- See [CONSTRAINTS.md](CONSTRAINTS.md) for the full constraint declaration API reference

**`relay/constraints.py`** — `Constraints` class and supporting types (also defines relay-type constants):
- Relay-type string constants: `R10`, `R15`, `R20`, `R30`, `R13_F`, `R15_F` — pass to `add_relay()` as `size`
- `make_relay_types(nb_segments, total_km, enable_flex)` — computes segment-count sets per relay type; called internally by `Constraints.__init__`
- `Constraints.__init__`: accepts `total_km`, `nb_segments`, `speed_kmh`, `start_hour`, `compat_matrix` (explicit `dict[tuple[str,str], int]` — lower triangle), `solo_max_km`, `solo_max_default`, `nuit_max_default`, `repos_jour_heures`, `repos_nuit_heures`, `nuit_debut`, `nuit_fin`, `solo_autorise_debut`, `solo_autorise_fin`, `max_same_partenaire`, `enable_flex`, `allow_flex_flex` (default `True`; if `False`, two flex runners forming a binôme are each forced to their own nominal size — no reduction allowed), `profil_csv` (optional path to altitude CSV, default `None`), `acces_csv` (optional path to `access_points.csv`, lazy-loaded as `constraints.acces`), `lvl_max` (default 5); `solo_autorise_debut`/`solo_autorise_fin` define the time window (hours) in which solo relays are permitted — segments outside this window set `relais_solo_interdit[r][k]=1`; pauses are declared via `add_pause()` (not via constructor); `segment_start_hour()` and `hour_to_seg()` account for cumulative pause offsets
- `add_pause(seg, duree)`: declares a planned race halt after active segment `seg` (int), with duration `duree` hours; raises `RuntimeError` if called after `new_runner()` (runtime check, not assert); inserts inactive segments into the time-space timeline; exposes `inactive_ranges`, `inactive_segments`, `active_segments`; `nb_segments` grows with each call (total time-space segments); `nb_active_segments` stays fixed
- `add_inaccessible(*kms)`: declares one or more km positions that are forbidden as relay handover points; forbids `start[r][k] == s` and `end[r][k] == s` in the CP-SAT model; stored in `inaccessible_segments` (time-space indices)
- `new_runner(name, lvl)` → `RunnerBuilder` (validates name against compat matrix; `lvl` (int, 1..`lvl_max`) is stored in `options.lvl` and used as weight in the `--dplus` objective; runner options set via `set_options()`)
- `new_relay(size)` → `SharedLeg` (forced binôme between two runners)
- `add_max_binomes(runner1, runner2, nb)`: limits to at most `nb` binômes between two runners across the whole planning (stored in `once_max`)
- `night_windows()` → `Intervals` covering all nocturnal segments, in **active** segment indices
- `RunnerBuilder.add_relay(size, *, nb, window, pinned, dplus_max)` → `self` (chainable; `size` is a relay-type string or `SharedLeg`; `window` and `pinned` accept **active** segment indices and are converted to time-space indices internally; `dplus_max` is an optional int limit in metres on D+ + D− for that relay — requires `profil_csv=`)
- `RunnerBuilder.set_options(*, solo_max, nuit_max, repos_jour, repos_nuit, max_same_partenaire)` → `self`: sets per-runner overrides (note: `lvl` is now set via `new_runner(name, lvl)` directly, not via `set_options`)
- `RelaySpec` dataclass: `size`, `paired_with`, `window`, `pinned`, `dplus_max`; supports `to_dict()` / `from_dict()`
- `RunnerOptions` dataclass: `solo_max`, `nuit_max`, `repos_jour`, `repos_nuit`, `max_same_partenaire`, `lvl` (all `int | None`); used for per-runner overrides and `Constraints.defaults`; supports `to_dict()` / `from_dict()`
- `Coureur` dataclass: `relais: list[RelaySpec]`, `options: RunnerOptions`
- `Intervals` dataclass: `intervals: list[tuple[int,int]]`
- Properties: `runners`, `relay_sizes`, `relay_types`, `defaults` (global `RunnerOptions`), `night_segments`, `segment_km`, `segment_duration`, `paired_relays`, `solo_max_size`, `has_flex`, `solo_forbidden_segments`, `last_active_seg` (= `nb_active_segments` — upper bound for `Intervals`, replaces `nb_segments` in the declarative API), `profil` (lazy-loaded `Profile` instance from `profil_csv`, or `None`), `acces` (lazy-loaded `AccessPoints` instance from `acces_csv`, or `None`), `lp_bounds` (lazy LP relaxation result — `.upper_bound`, `.solo_nb`, `.solo_km`)
- Methods: `segment_start_hour(seg)` (purely linear in the time-space model), `is_night(seg)`, `is_active(seg)`, `compat_score(r1, r2)` (replaces removed `is_compatible()` — use `compat_score() > 0`), `hour_to_seg(h, jour=0)` (returns **active** segment index — converts via `time_seg_to_active()`), `km_to_seg(km)` (returns **active** segment index directly), `active_to_time_seg(active_idx)`, `time_seg_to_active(seg)`, `duration_to_segs(hours)`, `size_of(relay_name)`, `print_summary()`
- Serialization: `to_dict()` / `to_json(filename)` / `from_dict(data)` / `from_json(path)` — full round-trip serialization of constraints (runners, relays, pauses, compat_matrix, inaccessible_segments); `relay_types` is not serialized (redundant with segment counts in `RelaySpec`)

**`compat.py`** — `COMPAT_MATRIX: dict[tuple[str, str], int]` — explicit compatibility scores (0, 1, or 2) for every runner pair. Stores only the lower triangle; `Constraints` reconstructs full symmetry at load time. Passed as `compat_matrix=COMPAT_MATRIX` to `Constraints.__init__`. Auto-generated by `utils/refresh_compat.py` from `compat_coureurs.xlsx`; do not edit manually.

**`relay/model.py`** — CP-SAT model builder:
- `Model`: holds the `cp_model.CpModel` instance and all CP-SAT variables:
  - `start[r][k]`, `end[r][k]`, `size[r][k]` (IntVar); for flexible runners `size` has a domain including compatible partner sizes
  - `same_relay[(r,k,rp,kp)]` (BoolVar): 1 if the pair forms a binôme (same start + same effective size)
  - `relais_solo[r][k]`, `relais_nuit[r][k]`, `relais_solo_interdit[r][k]` (BoolVar)
- `build(constraints)`: calls `_add_variables`, `_add_symmetry_breaking`, `_add_fixed_relays`, `_add_night_relay`, `_add_solo_intervals`, `_add_rest_constraints`, `_add_availability`, `_add_same_relay`, `_add_pause_constraints`, `_add_coverage`, `_add_inter_runner_no_overlap`, `_add_solo_constraints`, `_add_forced_pairings`, `_add_once_max`, `_add_max_same_partenaire`, `_add_dplus_max_constraints`, `_add_inaccessible_constraints`
- `_add_inaccessible_constraints`: for each segment in `constraints.inaccessible_segments`, forbids `start[r][k] == s` and `end[r][k] == s` for every relay — no-op if `inaccessible_segments` is empty
- `_add_symmetry_breaking`: for each runner, groups identical non-pinned non-shared relays and enforces `start[r][k] <= start[r][k']` for consecutive indices — reduces search space by a factorial factor
- `_add_pause_constraints`: for each inactive range `(a, b)` in `constraints.inactive_ranges`, forbids any relay that overlaps it (enforces `end[r][k] <= a` OR `start[r][k] >= b` via a BoolVar disjunction)
- `_add_same_relay`: now also filters out pairs whose feasible start ranges don't overlap (temporal pre-filter before building BoolVars); for two fixed-size relays, only creates a `same_relay` var if they share the exact same size; `_feasible_start_ranges(spec, nb_segments)` and `_ranges_overlap()` are static helpers
- `_add_coverage`: uses a cumulative constraint (demand=1, capacity=2) plus a BoolVar per relay×active segment to enforce at least 1 runner per segment
- `_iv_index`: dict `(r, k) → interval_var` for O(1) lookup (replaces linear scans in `_add_inter_runner_no_overlap`)
- `add_optimisation_func(constraints)`: maximizes the objective expression (weighted binôme sum minus flex penalty)
- `_add_fixed_relays`: enforces `pinned` entries as equality constraints on `start`; size domain comes from the relay's set
- Objective: mixed — maximizes weighted binôme sum minus a flex penalty (`sum(sz_max - size[r][k])` over flex relays); this penalty discourages two flex runners from pairing at a size below both their maxima (double-flex binôme), since both would be penalized
- `_add_dplus_max_constraints`: for each `RelaySpec` with `dplus_max` set, builds cumulative D+/D− lookup vars (same approach as `add_optimise_dplus`) and adds `(dp_end - dp_start) + (dm_end - dm_start) <= dplus_max`; no-op if no relay carries a `dplus_max`; raises `RuntimeError` if `profil_csv=` is missing
- `add_optimise_dplus(constraints)`: alternative objective — maximizes `sum(lvl[r] * (D+[r][k] + D-[r][k]))` over all relays; uses pre-computed cumulative table + `AddElement` lookups; raises if no runner has `lvl` set
- `add_minimise_differences_with(reference)`: sets the objective to minimize total distance (sum of `|start[r][k] - ref_start|`) with a reference `Solution`; used for replanning
- `add_hint(solution)`: injects CP-SAT hints (warm-start) from a `Solution`; sets hints on `start` variables
- `build_model(constraints)`: factory returning a built `Model`
- Public methods: `add_optimisation_func(constraints)`, `add_min_score(constraints, score)`, `add_optimise_dplus(constraints)`, `add_minimise_differences_with(reference)`, `add_hint(solution)`

**`relay/solver.py`** — Solver:
- `Solver(model, constraints)`: wraps CP-SAT solving; `solve(timeout_sec, target_score, max_count)` is a streaming iterator that yields `Solution` objects as they are found; solver runs in a background thread; solution extraction delegated to `Solution.from_cpsat()`
- After each valid solution, if `constraints.acces` is set, `Solver.solve()` calls `constraints.acces.enrich()` to replace relay km/GPS data with real access point positions
- Default: `SOLVER_TIME_LIMIT=0` (unlimited), `SOLVER_NUM_WORKERS=10`

**`relay/solution.py`** — `Solution`:
- `Solution(relays, constraints, score=None, skip_validation=False)`: `relays` is a `list[dict]`; `constraints` passed explicitly; constructor runs `verifications.check()` and sets `.valid`
  - `from_cpsat(solver)` (classmethod): extracts variable values from the CP-SAT callback state, computes `rest_h` and D+/D− from `constraints.profil`, and returns a `Solution`; signature takes the callback only (model and constraints accessed via `solver._relay_model` / `solver._constraints`)
  - `from_dict(data, skip_validation=False)` (classmethod): loads a solution from a dict (produced by `to_dict()`); reconstructs `Constraints` from `data["constraints"]` via `Constraints.from_dict()`
  - `from_json(path, skip_validation=False)` (classmethod): loads a JSON solution; `Constraints` is always reconstructed from the embedded JSON (self-contained)
  - `to_dict()` → `{"constraints": ..., "relays": [...]}` — full round-trip dict
  - `to_csv(filename)` / `to_json(filename)` / `to_html(filename)` — save to file
  - `save()` — saves timestamped `.txt`, `.csv`, `.json`, `.html` in `plannings/` and prints stats
  - `stats()` → `(score, n_binomes, n_solos, km_solos, n_flex, n_pinned, km_flex)` — `score` is the recalculated objective value; `km_flex` is km saved by flex relays running shorter than nominal
  - `to_text()` → full text planning (chrono + per-runner recap); day separators removed
- HTML output includes a Gantt-style grid per runner (colour-coded: green=binôme, pink=solo, blue=fixed relay, grey=mandatory rest, purple=unavail) with 6h time markers; runner order controlled by `formatters.TRI_GANTT` (`"decl"` / `"alpha"` / `"start"`)
- `_build_gantt()`: dedicated method returning `(header_row, rows_html)` for the Gantt table; CSS factored into classes (no inline styles)

**`relay/geography.py`** — GPS access point enrichment:
- `AccessPoints(rows)`: index of access points loaded from a CSV (columns: `jalon`, `km_cross`, `lat_cross`, `lon_cross`, `road_type`, `road_name`, `delta_km`, `acces`); groups rows by jalon (active segment index)
- `_choose(jalons_used, segment_km)` → `dict[int, dict | None]`: greedy selection of the best access point per jalon, minimising the deviation between real and theoretical segment lengths; returns `None` for jalons with no access point in the CSV
- `enrich(relays, segment_km, profil=None, time_seg_to_active=None)` → `list[dict]`: enriches relay dicts with `start_acces`, `end_acces` (dict with `km_cross`, `lat`, `lon`, `acces`, `road_type`, `road_name`, or `None`), recalculates `km` from real access point positions, and recomputes `d_plus`/`d_moins` from profil if provided; `time_seg_to_active` is required when the planning contains pauses
- `load_access_points(path)` → `AccessPoints`: loads CSV using `csv.DictReader` (no pandas dependency)
- Used via `constraints.acces` (lazy-loaded from `acces_csv` constructor arg); called by `Solver.solve()` after each valid solution

**`relay/profil.py`** — Altitude profile for the race route:
- `Profile(distances, altitudes)`: interpolates altitude along the route (binary search + linear interpolation)
  - `denivele(km_deb, km_fin) -> (d_plus, d_moins)`: integrates positive and negative elevation change between two kilometre marks; iterates directly over CSV profile points in the interval
- `load_profile(filename=DEFAULT_PROFILE) -> Profile`: loads `gpx/altitude.csv` (semicolon-separated distance/altitude pairs, one point per 100 m); skips comment lines starting with `;`
- `DEFAULT_PROFILE = "gpx/altitude.csv"`
- Used via `constraints.profil` (lazy-loaded from `profil_csv` constructor arg); `Solution.from_cpsat()` calls `profil.denivele()` to fill `d_plus`/`d_moins` in each relay dict

**`relay/__init__.py`** — package-level convenience functions:
- `replanif(constraints, *, reference, min_score=None, timeout_sec=0)`: loads a reference JSON, builds the model with `add_minimise_differences_with()`, optionally adds `add_min_score()`, then solves and saves
- `optimise_dplus(constraints, *, min_score=None, timeout_sec=0)`: builds model, calls `add_optimise_dplus()` (maximises weighted D+/D−), optionally adds `add_min_score()`, solves and saves
- `solve(constraints, *, timeout_sec=0)`: builds model, sets objective, solves, and saves each solution found
- `entry_point(constraints)`: CLI dispatcher — parses `sys.argv` for `--summary`, `--diag`, `--model`, `--dplus [--min-score <n>]`, `--replanif <file> [--min-score <n>]`, or defaults to `solve()`
- Exports: `Constraints`, `Intervals`, `RunnerBuilder`, `SharedLeg`, `Model`, `model`, `Solver`, `Solution`, `FeasibilityAnalyser`, `diagnose`, `solve`, `replanif`, `optimise_dplus`, `entry_point`

**`relay/feasibility.py`** — `FeasibilityAnalyser` for systematic infeasibility diagnosis:
- Builds partial models, disabling constraint families one at a time
- `analyse(constraints)` (aliased as `relay.diagnose()`) — shortcut entry point

**`relay/verifications.py`** — post-solve verification suite:
- `check(solution, constraints)`: validates coverage, relay sizes, rest constraints, night/solo limits, pairings, compatibility, and pause boundary crossings (`_check_pauses`)

**`replanif.py`** — Replanning script at the project root: same problem declaration as `example.py`, but delegates to `entry_point()` with `--replanif <file.json> [--min-score <n>]`.

**`utils/refresh_compat.py`** — regenerates `compat.py` from `compat_coureurs.xlsx`:
- Validates matrix structure (square, symmetric, diagonal=`X`, lower triangle only)
- Run after modifying the Excel file

**`utils/find_access_points.py`** — generates `gpx/access_points.csv` from the GPX trace and OSM road data:
- For each segment jalon, finds road crossings/nearby roads; outputs columns `jalon`, `km_cross`, `lat_cross`, `lon_cross`, `acces` (`cross`/`near`/`''`), `road_type`, `road_name`, `delta_km`
- Inaccessible jalons get an entry with `acces=''`

**`utils/reformat.py`** — regenerates HTML from existing JSON solution files (moved from `old/reformat.py`)

**`relay/formatters.py`** — rendering module (text, CSV, HTML):
- `TRI_GANTT` constant controls Gantt row order: `"decl"` (declaration order, default), `"alpha"` (alphabetical), `"start"` (first relay start time)
- Text report (`to_text()`) no longer emits day separators between chronological entries
- HTML segment number is a Google Maps satellite link (red if no access point); lat/lon read from `start_acces` dict; uses `km_reel` with fallback to `km` for display

**`old/`** — Legacy scripts (unmaintained, imports may be broken):
- `enumerate.py` — 3-phase solution enumerator
- `analyze_solutions.py` — per-runner histograms and HTML synthesis
- `check_configs_unique.py` — verify distinct binôme configurations
- `find_duplicate_solutions.py` — detect identical JSON solutions
- `replanif.py` — old replanning script (incompatible with current API; use root `replanif.py` instead)

## Key modeling details

- **Time-space model**: the segment timeline mixes active segments (race) and inactive segments (pauses). `nb_segments` is the total time-space length; `nb_active_segments` is the fixed count of race segments. All CP-SAT variables (`start`, `end`) use time-space indices; coverage constraints iterate over `active_segments` only.
- Segments are 0-indexed; active segment `s` covers km `time_seg_to_active(s) * segment_km`; `segment_start_hour(seg)` is purely linear (`start_hour + seg * segment_duration`) in the time-space model
- Pauses are encoded as `inactive_ranges`: contiguous blocks of inactive segments inserted into the timeline. Rest constraints need no pause credit — the gap `end[ka]` to `start[kb]` in time-space automatically spans any intervening pause.
- Two runners form a binôme if same effective relay size AND same start segment AND `compat_score > 0`: both flex and fixed runners can pair together; when two flex runners pair, the model allows any size in the intersection of their domains, but the flex penalty in the objective penalizes each runner running below their nominal size, making double-flex binômes at sub-maximal size costly; with `allow_flex_flex=False`, each runner in a flex+flex binôme is instead hard-constrained to its own nominal size (`max` of its domain)
- Incompatible pairs (or pairs with no `same_relay` var) are forced disjoint via `add_no_overlap`
- Solo relays are forbidden outside the `solo_autorise_debut`/`solo_autorise_fin` time window: `_add_solo_intervals` sets `relais_solo_interdit[r][k]=1` for segments outside this window, and `_add_solo_constraints` enforces `relais_solo[r][k] + relais_solo_interdit[r][k] <= 1`
- Flexible runners in solo are forced to the nominal size (`max` of their size set)
- Inaccessible segments: `constraints.inaccessible_segments` holds time-space indices where no relay boundary is allowed; declared via `add_inaccessible(*kms)`; model enforces `start[r][k] != s` and `end[r][k] != s` for each such segment
- Symmetry breaking: for identical non-pinned relays of the same runner, `start[r][k] <= start[r][k']` is enforced, reducing the search space by a factorial factor
- Solver time limit: unlimited by default (`SOLVER_TIME_LIMIT=0` in relay/solver.py); configurable via `timeout_sec` parameter in `solve()` / `Solver.solve()`

## Commit instructions
- **DO NOT ADD** 'CoAuthored by:' footers or any other promotional content in commit messages
