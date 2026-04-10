# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working conventions

**Package: `relay/`** — the only package in the repository. All development happens here.

## Running tests

```bash
python -m pytest tests/
```

## Running the solver

```bash
source venv/Scripts/activate
python example.py
```

The solver runs (no timeout by default) and writes all output into a timestamped subdirectory `plannings/<YYYYMMDD_HHMMSS>_<action>/`: `planning.json`, `planning.csv`, `planning.html`, `planning.txt` (and `planning.gpx` if `parcours=` is set). Individual GPX/KML per relay go into a `split/` subdirectory within that run directory.

CLI options (all via `example.py`, dispatched by `relay.entry_point()`):
```bash
python example.py                           # solve (default)
python example.py data                      # print data summary
python example.py diag                      # run feasibility analyser
python example.py dplus                     # solve maximising weighted D+/D-
python example.py replanif --ref ref.json   # replanify: minimise distance to reference
python example.py solve --min-score 88      # solve with min score constraint
python example.py solve --ref hint.json     # solve using hint from prior solution
python example.py dplus --ref hint.json     # dplus using hint
python example.py solve --no-split          # disable individual GPX/KML export per relay
```

The action is a **positional argument** (not a flag). `--ref <file>` serves dual purpose: hint for `solve`/`dplus`, required reference for `replanif`. Split export (individual GPX/KML per relay into a subdirectory under `plannings/`) is **enabled by default**; use `--no-split` to disable.

On Windows, use `exemple.cmd` (wrapper in project root) instead of `python example.py`.

## Environment

- Python venv at `venv/` (Python 3.13, ortools CP-SAT)
- VSCode launch config uses `venv/bin/python` directly (no activation needed from IDE)
- All scripts must be run from the project root (imports assume `relay` package and `example.py` are on the path)

## Architecture

The project solves a relay race scheduling problem. ~440 km, ~180 real waypoints (variable spacing), ~9 km/h, departing Wednesday 14h00. 15 runners must cover every arc between waypoints (1 or 2 runners per arc).

**`relay/`** — Python package. Public API exported from `relay/__init__.py`.

**`example.py`** — Problem constants, runner data, and entry point:
- `Preset` namedtuple: `Preset(km=15, min=13, max=17)` — reusable relay size templates
- `c = Constraints(parcours=, speed_kmh=, start_hour=, compat_matrix=, solo_max_km=, solo_max_default=, nuit_max_default=, repos_jour_heures=, repos_nuit_heures=, max_same_partenaire=)`, then `c.new_runner(name, lvl)` → `RunnerBuilder`; `parcours` accepts a GPX file path or a `Parcours` instance; `compat_matrix` accepts either a path to an xlsx file or a pre-built `dict[tuple[str,str], int]`
- `runner.add_relay(*presets, window=, pinned=, dplus_max=, solo=)` — one preset = simple relay; multiple presets = chained relays (end[k] == start[k+1], no rest between them); only `Preset` or `SharedLeg` accepted as positional args
- **Pinning via dedicated factory**: `c.new_pin(*, start_km=, start_wp=, start_time=, end_km=, end_wp=, end_time=)` → `Pin`; pass as `pinned=` kwarg to `add_relay()`; `start_*` and `end_*` are mutually exclusive within their group
- `c.interval_km(start_km, end_km)`, `c.interval_time(start_h, start_j, end_h, end_j)`, `c.interval_waypoints(start_wp, end_wp)` → `Interval`
- `c.new_shared_relay(preset)` → `SharedLeg` (also accepts `target_km=`, `min_km=`, `max_km=` kwargs): pass to two runners' `add_relay()` to force a binôme
- `c.add_max_duos(r1, r2, nb)`: limits binômes between two runners
- `c.add_pause(duree_heures, *, wp=|km=|heure=, jour=)`: inserts a rest arc (duration can be 0); must precede all interval factories; returns `self` (chainable)
- `c.add_night(interval)`: declare night periods (chainable); takes `Interval` from `interval_time()` or `interval_km()`
- `c.add_no_solo(interval)`: declare solo-forbidden zones (chainable); takes `Interval` from `interval_time()` or `interval_km()`
- `python example.py` delegates to `relay.entry_point(c)`

---

## `relay/` package modules

**`relay/parcours.py`** — `Parcours` class: geographic data (waypoints + altitude profile):
- `Parcours(waypoints, profile_distances, profile_altitudes, gpx_path=None)`: internal constructor
- `Parcours.from_raw(waypoints, profile_data=None, gpx_path=None)` → `Parcours` (classmethod)
- `load_gpx(gpx_path)` → `Parcours`: parse GPX file, extract waypoints and altitude profile
- Properties: `waypoints` (list of `{km, lat, lon, alt?, name?}`), `has_profile`, `gpx_path`
- `denivele(km_deb, km_fin)` → `(D+, D-)` in metres
- `svg_profile(...)` → SVG altitude profile string

**`relay/constraints.py`** — `Constraints` class and supporting types:
- `Preset` namedtuple: `(km, min, max)` — relay size template (all in km)
- `Interval` NamedTuple: `(lo, hi)` waypoint index window. Do not instantiate directly — use the factories below.
- `Pin` NamedTuple: `(start, end)` — pinning descriptor. Do not instantiate directly — use `c.new_pin()`.
- `Constraints.__init__`: accepts `parcours` (path to GPX **or** `Parcours` instance), `speed_kmh`, `start_hour`, `compat_matrix` (path to xlsx **or** pre-built `dict[tuple[str,str], int]`; read via `relay.compat.read_compat_matrix()` if a string is passed), `solo_max_km`, `solo_max_default`, `nuit_max_default`, `repos_jour_heures`, `repos_nuit_heures`, `max_same_partenaire`
- Internal units: distances in **metres** (int), times in **minutes** (int); `cumul_m` and `cumul_temps` are precomputed lookup tables
- `add_pause(duree_heures, *, wp=|km=|heure=, jour=)`: inserts a zero-km arc; duration can be 0 (phantom point without time shift); position by `wp` (user waypoint index), `km`, or `heure`+`jour`; shifts `cumul_temps` for all subsequent points; stored in `pause_arcs`; must be called before any `interval_*()` factory; returns `self` (chainable)
- `add_night(interval)` → `self`: declare night periods, accepts `Interval` from `interval_time()` or `interval_km()`, can be chained multiple times
- `add_no_solo(interval)` → `self`: declare solo-forbidden zones, accepts `Interval` from `interval_time()` or `interval_km()`, can be chained multiple times
- `new_runner(name, lvl)` → `RunnerBuilder`; `new_shared_relay(preset=None, *, target_km, min_km, max_km)` → `SharedLeg`; all created `SharedLeg` instances are tracked in `_shared_legs` for validation
- `new_pin(*, start_km, start_wp, start_time, end_km, end_wp, end_time)` → `Pin`: dedicated factory for pinning; `start_*` mutually exclusive, `end_*` mutually exclusive; either side can be `None`
- `validate()`: comprehensive pre-build validation — checks SharedLeg registration (exactly 2 runners), every runner has ≥1 relay, all runners exist in compat_matrix, Preset min ≤ max, window intervals valid and in bounds, pinned_start/end in bounds, solo_max_m ≤ total_km, night/no_solo intervals valid and in bounds; called automatically by `build_model()`
- `add_max_duos(runner1, runner2, nb)`: limits binômes between two runners (stored in `max_duos`)
- `RunnerBuilder.add_relay(*presets, window, pinned, dplus_max, solo)` → `self` (chainable); `presets` is one or more `Preset | SharedLeg`; single preset = simple relay, multiple = chained sequence (`chained_to_next=True` on all but last); `SharedLeg` items are registered automatically; `pinned` is a `Pin` from `c.new_pin()`; `solo` applied to `Preset` items, ignored for `SharedLeg`; `solo=True` incompatible with any `SharedLeg`
- `RunnerBuilder.set_options(*, solo_max, nuit_max, repos_jour, repos_nuit, max_same_partenaire)` → `self`
- `RelaySpec` dataclass: `target_m`, `min_m`, `max_m`, `paired_with`, `window`, `pinned_start`, `pinned_end`, `dplus_max`, `solo`; supports `to_dict()` / `from_dict()`
- `RunnerOptions` dataclass: `solo_max`, `nuit_max`, `repos_jour_min`, `repos_nuit_min`, `max_same_partenaire`, `lvl` (all `int | None`); rest times in **minutes**; supports `to_dict()` / `from_dict()`
- Interval factories (freeze arc indices, call after `add_pause()`): `interval_km(start_km, end_km)`, `interval_time(start_h, start_j, end_h, end_j)`, `interval_waypoints(start_wp, end_wp)` → `Interval`
- Properties: `runners`, `paired_relays`, `last_point`, `upper_bound`, `upper_bound_max` (lazy CP-SAT majorants), `cumul_dplus` (lazy D+/D− tables), `nb_points`, `nb_arcs`, `cumul_m`, `cumul_temps`, `waypoints_km`, `waypoints`, `pause_arcs`, `_intervals_night`, `_intervals_no_solo`
- Internal conversion methods (private): `_km_to_point(km)`, `_hour_to_point(h, j=0)`, `_point_km(pt)`, `_point_hour(pt)`, `min_arc_m()`, `compat_score(r1, r2)`, `_arcs_in_intervals(intervals)`
- Serialization: `to_dict()` / `to_json(filename)` / `from_dict(data)` / `from_json(path)` — full round-trip; `to_dict()` strips pause-inserted points from `waypoints` before serializing so `from_dict()` can safely replay `add_pause()` without double-inserting

**`relay/model.py`** — `Model` CP-SAT model builder:
- Variables per relay `(r, k)`: `start[r][k]` (point index), `end[r][k]` (point index), `nb_arcs_var[r][k]` (= end − start); `iv[r][k]` `IntervalVar` on point indices
- Derived variables via `AddElement` on `cumul_m`/`cumul_temps`: `dist_start`, `dist_end`, `dist`, `time_start`, `time_end`, `flex` (|dist − target_m|)
- BoolVars: `same_relay[(r,k,rp,kp)]`, `relais_nuit[(r,k)]`, `relais_solo[(r,k)]`
- Time-domain intervals: `iv_time[(r,k)]`, `iv_repos[(r,k)]`, `repos_end[(r,k)]` for no-overlap with rest
- D+/D− variables (created lazily by `_ensure_dplus_vars`): `dp_s`, `dp_e`, `dm_s`, `dm_e` per relay — shared between `dplus_max` constraints and `add_optimise_dplus`
- `build(c)`: calls all constraint families in order
- `CONSTRAINT_FAMILIES` list: `symmetry_breaking`, `fixed_relays`, `chained_relays`, `pause_constraints`, `coverage`, `same_relay`, `inter_runner_no_overlap`, `night_relay`, `solo`, `rest_intervals`, `availability`, `shared_relays`, `max_duos`, `max_same_partenaire`, `dplus_max`
- `add_pause_constraints`: forbids any relay from crossing a pause arc (via `b_after` BoolVar)
- `add_coverage`: `AddCumulative(capacity=2)` + per-arc coverage BoolVar sum ≥ 1 (pause arcs excluded)
- `add_same_relay`: `same_relay = 1` iff same `start` AND same `end` (exact match, both directions)
- `add_inter_runner_no_overlap`: incompatible pairs → global no-overlap; compatible pairs → conditional per-pair no-overlap when `same_relay=0`
- `add_night_relay`: checks `_intervals_night` (list of waypoint ranges); for each interval, tests relay overlap (start ≤ hi AND end > lo); nuit_max constraint per runner; no-op if `_intervals_night` is empty
- `add_solo_constraints`: `relais_solo = 1` iff no active `same_relay`; enforces distance cap (solo_max_m), overlap checks against `_intervals_no_solo` (forbidden solo zones), and per-relay `solo` constraints (`True` → `rs==1`, `False` → `rs==0`)
- `add_rest_intervals`: temporal `IntervalVar` per relay + repos interval; `AddNoOverlap` per runner
- `add_availability`: enforces `window` constraints (start/end within point ranges)
- `add_fixed_relays`: enforces `pinned_start`/`pinned_end` as equality constraints (each independent)
- `add_chained_relays`: enforces `end[r][k] == start[r][k+1]` for chained relay sequences
- `add_symmetry_breaking`: `start[r][ka] < start[r][kb]` for identical non-pinned non-shared relays
- `add_shared_relays`: forces `same_relay = 1` for `SharedLeg` pairs
- `add_max_duos`: enforces `sum(same_relay for pair) <= nb` from `c.max_duos`
- `add_max_same_partenaire`: per-runner limit on binômes with any single partner
- `add_dplus_max_constraints`: cumulative D+/D− via `AddElement` (shared vars); no-op if no `dplus_max` declared
- `add_optimisation_func(c)`: maximises `BINOME_WEIGHT * sum(compat_score * same_relay)`
- `add_min_score(c, score)`: adds `BINOME_WEIGHT * binome_score >= score`
- `add_optimise_dplus(c)`: maximises `sum(lvl[r] * (D+[r][k] + D-[r][k]))` using shared D+/D− vars
- `add_minimise_differences_with(ref_sol, constraints)`: minimises `sum(|start[r][k] - ref_start|)` in km for replanning
- `add_hint_from_solution(sol)`: loads a prior solution as CP-SAT hint
- `build_model(c, *, min_score)`: factory returning a built `Model`; calls `c.validate()` before building

**`relay/solver.py`** — `Solver`:
- `Solver(model, constraints)`: wraps CP-SAT solving; `solve(timeout_sec, max_count, log_progress)` is a streaming iterator yielding `Solution` objects; solver runs in a background thread
- Default: `SOLVER_TIME_LIMIT=0` (unlimited), `SOLVER_NUM_WORKERS=10`

**`relay/solution.py`** — `Solution`:
- `Solution(relays, constraints)`: `relays` is a `list[dict]`
  - `from_cpsat(callback)` (classmethod): extracts all relay fields including `km_start/end`, `lat/lon/alt_start/end`, `time_start/end_min`, `solo`, `night`, `partner`, `target_km`, `d_plus`, `d_moins`, `rest_min_h`, `rest_h`; automatically calls `check()` on the result
  - `from_dict(data)` / `from_json(path)` / `from_latest()` (classmethods): reconstruct `Constraints` from embedded JSON; automatically calls `check()` on the result
  - `to_dict()` → `{"constraints": ..., "relays": [...]}`; `to_json(filename)`, `to_text()` → `str`
  - `save(*, base, as_json, csv, html, txt, gpx, kml, split)`: writes `{base}.json`, `.csv`, `.html`, `.txt` files; `base` is the full path stem (without extension) pointing into the run subdirectory; also writes `.gpx` if `parcours` is set and `gpx=True`; `split=True` exports individual GPX/KML per relay into `{run_dir}/split/`
  - `stats()` → `SolutionStats` dataclass: `score_duos`, `nb_duos`, `nb_solo`, `km_solo`, `nb_pinned`, `flex_plus`, `flex_moins`, `score_dplus`, `ub_score_target`, `ub_score_max`, `lb_solos`
  - `print_summary()`: one-line console summary with duos score (with upper bounds), solos, flex ± and D+ score

**`relay/verifications.py`** — post-solve verification suite:
- `check(solution)` → `(bool, StringIO)`: runs all checks, returns ok flag and output buffer; called automatically by `Solution.from_cpsat()` and `Solution.from_dict()`
- Checks: `_check_unknown_runners`, `_check_start_end_order`, `_check_derived_fields`, `_check_coverage` (all non-pause arcs covered 1–2×), `_check_pauses` (no relay crosses a pause arc), `_check_relay_sizes` (min_m/max_m respected), `_check_rest` (rest gaps in minutes via `cumul_temps`), `_check_night_max`, `_check_solo_max`, `_check_solo_intervals` (relay overlaps a forbidden zone), `_check_no_overlap_between_runners`, `_check_pairings` (SharedLeg pairs honoured), `_check_compatibility_matrix`, `_check_max_duos`, `_check_max_same_partenaire`, `_check_solo` (per-relay `solo` constraint respected), `_check_chained`, `_check_availability`, `_check_pinned`, `_check_dplus_max`, `_check_night_vs_time`, `_check_solo_vs_partner`, `_check_partner_reciprocity`, `_check_km_consistency`
- `_contiguous_groups(sorted_arcs)`: groups a sorted arc list into contiguous `[(fa, fb), ...]` intervals

**`relay/feasibility.py`** — `FeasibilityAnalyser`:
- `FeasibilityAnalyser(constraints, timeout=10.0).run()`: 3-phase analysis
  - Phase 1: disable each constraint family one at a time
  - Phase 2: per-runner / per-relay drilldown for suspect families (`rest_intervals`, `availability`, `night_relay`, `fixed_relays`, `shared_relays`, `max_duos`, `max_same_partenaire`, `solo`)
  - Phase 3: try disabling pairs of families simultaneously
- `_PartialModel(Model)`: `build_without(c, skip_set)` with automatic dependency propagation via `_SKIP_DEPS`
- `diag_faisabilite(constraints, timeout=10.0)`: convenience entry point (called by `--diag`)

**`relay/formatters/`** — rendering subpackage (text, CSV, HTML, GPX/KML):
- `relay/formatters/text.py`: `to_text(solution)` → `str`
- `relay/formatters/commun.py`: `to_csv(solution, filename)`, shared data-building helpers (`summary_data`, `build_chrono_entries`, `build_runner_recaps`)
- `relay/formatters/html.py`: `to_html(solution)` → `str`, `build_gantt(solution)` → SVG Gantt HTML block; Gantt overlays night bands and pause arcs on the time axis
- `relay/formatters/gpx.py`: `to_gpx(solution, gpx_source, output_path)`, `to_kml(solution, gpx_source, output_path)`, `to_split(solution, gpx_source, outdir, gpx, kml)` — individual GPX/KML per relay with timestamp/partner/runner in filename; called automatically by `Solution.save()` when `parcours` is set

**`relay/upper_bound.py`** — CP-SAT score upper bound computation:
- `UpperBound` NamedTuple: `score`, `score_exact`, `n_binomes`, `n_solos`
- `compute_upper_bounds(constraints, timeout_sec=3.0)` → `(ub_target, ub_max)`: solves an aggregate CP-SAT model (no positional constraints) to compute two score majorants
  - `ub_target`: surplus with `size=target_m` — tight heuristic, not guaranteed
  - `ub_max`: surplus with `size=max_m` — guaranteed upper bound (always ≥ true optimum)
- Called lazily via `constraints.upper_bound` and `constraints.upper_bound_max` properties
- Results propagated to `SolutionStats.ub_score_target`, `ub_score_max`, `lb_solos` and shown in `print_summary()`

**`relay/_dirs.py`** — directory constants and utilities:
- `PLANNING_DIR = "plannings"` — output directory constant
- `latest_solution_path()` → `str`: path to `planning.json` in the most recent `YYYYMMDD_HHMMSS_<action>/` subdirectory of `PLANNING_DIR`
- `latest_solution()` → `Solution`: load and deserialize the most recent solution

**`relay/compat.py`** — compatibility matrix reader:
- `read_compat_matrix(path)` → `dict[tuple[str,str], int]`: reads xlsx lower-triangle matrix; canonical keys with `a < b` lexicographically; validates square matrix, diagonal, upper triangle empty, non-negative integer values

**`relay/__init__.py`** — package-level convenience functions:
- `solve(c, *, action, min_score, hint, timeout_sec, split=True)`: build model, set objective, optionally load hint, solve, save; split export enabled by default
- `replanif(c, *, action, reference, min_score, timeout_sec, split=True)`: load reference JSON, minimise differences
- `optimise_dplus(c, *, action, min_score, hint, timeout_sec, split=True)`: maximise weighted D+/D−, optionally load hint
- `_make_base(action)`: creates `plannings/<ts>_<action>/` directory and returns `plannings/<ts>_<action>/planning` as the base path; called once per solve run, shared across all iterative solutions
- `entry_point(c)`: CLI dispatcher via argparse — positional action (`solve`, `data`, `dplus`, `replanif`, `diag`) + `--min-score <n>`, `--ref <file>` (hint for solve/dplus, required reference for replanif), `--no-split` (disable per-relay GPX/KML export; split is on by default)
- Exports: `Constraints`, `build_model`, `Solver`, `Solution`, `diag_faisabilite`, `solve`, `replanif`, `optimise_dplus`, `entry_point`, `PLANNING_DIR`, `latest_solution_path`, `latest_solution`

---

## Key modeling details

- Relay handover points are chosen from a pre-defined list of GPS waypoints with variable spacing. `nb_points` is the number of points; `nb_arcs = nb_points - 1`. CP-SAT variables `start`/`end` are point indices; coverage iterates over all non-pause arcs.
- Internal units: distances in **metres** (int), times in **minutes** (int). `cumul_m[i]` and `cumul_temps[i]` are precomputed tables; derived quantities use `AddElement` lookups.
- Pauses insert a zero-km arc at a given point. `add_pause_constraints()` forbids any relay from crossing a pause arc by enforcing `end[r][k] <= ap` OR `start[r][k] >= ap+1`. Rest constraints need no special pause credit — the time gap between consecutive relays automatically spans the pause duration via `cumul_temps`. `add_pause()` accepts `wp=`, `km=`, or `heure=`+`jour=` for positioning. Duration can be 0 (phantom point, no time shift).
- Two runners form a binôme if `same_relay = 1` (same `start` AND same `end`). Incompatible pairs are forced disjoint via `add_no_overlap`.
- `flex[r][k]` = |dist − target_m| — the deviation variable. Used internally; no CLI action exposes it directly.
- `Preset(km, min, max)`: relay size template in km, converted to metres on `add_relay()`. No fixed relay-type constants — each problem declares its own presets in `example.py`.
- Pinning uses a dedicated factory: `c.new_pin(*, start_km=, start_wp=, start_time=, end_km=, end_wp=, end_time=)` → `Pin`; passed as `pinned=` kwarg to `add_relay()`. `pinned_start` / `pinned_end` in `RelaySpec` fix endpoints independently.
- Solo forbidden zones: declared via `c.add_no_solo(interval)` with `Interval` from time or km factories; a relay is forbidden solo if it **overlaps** any forbidden zone (not only if fully contained).
- Symmetry breaking: for identical non-pinned non-shared relays, `start[r][ka] < start[r][kb]` is enforced.
- Solver time limit: unlimited by default (`SOLVER_TIME_LIMIT=0`); configurable via `timeout_sec`.

---

## Code generation strategy

- Do not add retro-compatibility code for existing/legacy user-provided (exemple.py) or generated (solution.json) file.

---

## Data files

- `gpx/parcours_avec_waypoints.gpx` — full GPX trace with embedded waypoints; used as `parcours=` input and for GPX/KML export
- `compat_coureurs.xlsx` — source spreadsheet for compatibility scores; `utils/refresh_compat.py` reads it via `relay.compat.read_compat_matrix()` — pass the xlsx path directly to `Constraints(compat_matrix=...)`; do not edit `relay/compat.py` manually

---

## Commit instructions
- **DO NOT ADD** 'CoAuthored by:' footers or any other promotional content in commit messages
