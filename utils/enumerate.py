"""
Énumère les solutions optimales par exploration en 2 phases :

- Phase 1 : énumère toutes les configurations de binômes sur le modèle de référence
  et les enregistre en mémoire (liste de frozensets de clés actives).
- Phase 2 : pour chaque configuration, reconstruit le modèle avec les binômes fixés
  et cherche jusqu'à MAX_PER_CONFIG placements distincts.

Chaque solution est sauvegardée dans enumerate_solutions/ sous forme CSV/HTML.
Arrêt manuel possible avec Ctrl+C.
"""

import os
from datetime import datetime

from ortools.sat.python import cp_model
from data import build_constraints
from model import build_model
from solver import build_solution
import utils.analyze_solutions as analyze_solutions

OUTDIR = "enumerate_solutions"
SCORE_MINIMAL = 42        # 0 = recherche automatique, int = valeur connue
TIME_LIMIT_PHASE1 = 300.0 # secondes de recherche du meilleur score réalisable (seulement si SCORE_MINIMAL==0)
TIME_LIMIT_PHASE2 = 300.0 # secondes par recheche d'une configuration des binomes
TIME_LIMIT_PHASE3 = 60.0  # secondes par recherche d'un planning à configuration fixée
MAX_CONFIGS = 10          # configs max en phase 2 (None ou 0 = pas de limite)
MAX_PER_CONFIG = 10       # placements max par configuration de binômes (phase 3)
SOLVER_NUM_WORKERS = 10


def _make_solver(time_limit, log=False):
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = SOLVER_NUM_WORKERS
    solver.parameters.log_search_progress = log
    solver.parameters.max_time_in_seconds = time_limit
    return solver


def _save(relay_solution, run_ts, config_idx, place_idx):
    os.makedirs(OUTDIR, exist_ok=True)
    base = os.path.join(OUTDIR, f"run_{run_ts}_config_{config_idx:03d}_place_{place_idx:02d}")
    relay_solution.to_csv(base + ".csv")
    relay_solution.to_json(base + ".json")
    relay_solution.to_html(base + ".html")
    print(f"  → {base}.csv/.json/.html")


def _collect_configs(constraints, min_score, max_configs, run_ts):
    """Phase 2 : énumère toutes les configurations de binômes distinctes."""
    relay_model = build_model(constraints)
    relay_model.add_min_score(constraints, min_score)
    solver = _make_solver(time_limit=TIME_LIMIT_PHASE2)
    configs = []
    try:
        while True:
            status = solver.solve(relay_model.model)
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                print("\nPlus de configuration de binômes disponible.")
                break

            active_keys = frozenset(
                key for key, bv in relay_model.same_relay.items()
                if solver.boolean_value(bv)
            )
            configs.append(active_keys)
            config_idx = len(configs)
            relay_sol = build_solution(relay_model, constraints, solver)
            n_binomes, n_solos, km_solos, n_flex = relay_sol.stats()
            print(f"  Config {config_idx} trouvée — score:{relay_sol.score} binomes:{n_binomes} solos:{n_solos} ({km_solos:.1f} km) flex:{n_flex}")
            _save(relay_sol, run_ts, config_idx, 0)

            if max_configs and len(configs) >= max_configs:
                print(f"\nLimite sur nombre de configrations ({max_configs}) atteinte.")
                break

            relay_model.add_config_exclusion_cut(active_keys)

    except KeyboardInterrupt:
        print("\nArrêt manuel pendant la phase 2.")

    return configs


def _enumerate_placements(constraints, active_keys, optimal_score, config_idx, run_ts):
    """Phase 3 : énumère les placements distincts pour une configuration de binômes fixée."""
    relay_model = build_model(constraints)
    relay_model.add_min_score(constraints, optimal_score)
    relay_model.fix_binome_config(active_keys)
    solver = _make_solver(time_limit=TIME_LIMIT_PHASE3)

    n_places = 0
    for place_idx in range(1, MAX_PER_CONFIG + 1):
        status = solver.solve(relay_model.model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            break

        relay_sol = build_solution(relay_model, constraints, solver)
        _save(relay_sol, run_ts, config_idx, place_idx)
        relay_model.add_schedule_exclusion_cut(solver, constraints)
        n_places += 1

    return n_places


def enumerate_solutions(min_score):
    constraints = build_constraints()

    # --- Phase 1 : recherche d'un score minimal réalisable ---
    if min_score:
        print(f"Score minimal (fourni) : {min_score}\n")
    else:
        print(f"Recherche du meilleur score réalisable ({int(TIME_LIMIT_PHASE1)} s)...")
        relay_model = build_model(constraints)
        relay_model.add_optimisation_func(constraints)
        solver = _make_solver(TIME_LIMIT_PHASE1, log=True)
        status = solver.solve(relay_model.model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            print("Aucune solution trouvée.")
            return
        min_score = int(solver.objective_value)
        print(f"Meilleur score réalisable trouvé : {min_score}\n")

    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"Run timestamp : {run_ts}")

    # --- Phase 2 ---
    print(f"Phase 2 : collecte des configurations de binômes (score_min={min_score} limite {MAX_CONFIGS}configs X {TIME_LIMIT_PHASE2}sec)")
    configs = _collect_configs(constraints, min_score, MAX_CONFIGS, run_ts)
    print(f"\n{len(configs)} configuration(s) de binômes collectée(s).\n")
    if not configs:
        print("Aucune configuration trouvée.")
        return

    # --- Phase 3 ---
    print(f"Phase 3 : énumération des placements par configuration (limite={MAX_PER_CONFIG})...")
    n_total = 0
    try:
        for config_idx, active_keys in enumerate(configs, start=1):
            print(f"\nConfiguration {config_idx}/{len(configs)} ({len(active_keys)} binômes actifs) :")
            n_places = _enumerate_placements(constraints, active_keys, min_score, config_idx, run_ts)
            if n_places == 0:
                print("  Aucun placement trouvé pour cette configuration.")
            else:
                print(f"  {n_places} placement(s).")
            n_total += n_places

    except KeyboardInterrupt:
        print("\nArrêt manuel pendant la phase 3.")

    print(f"\nTotal : {n_total} solution(s) dans {len(configs)} configuration(s).")

    if n_total > 0:
        print("\nAnalyse des solutions...")
        analyze_solutions.main(constraints)


if __name__ == "__main__":
    print("L'énumération des solutions est bugguée - fix en cours ;)")
    # enumerate_solutions(min_score=SCORE_MINIMAL)
