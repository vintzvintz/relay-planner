"""
Énumère les solutions optimales (20 binômes) par exploration en 2 étapes successives :

- Étape 1 : énumère toutes les configurations de binômes sur le modèle de référence
  et les enregistre en mémoire (liste d'ensembles de clés actives).
- Étape 2 : pour chaque configuration, reconstruit le modèle avec les binômes fixés
  et cherche jusqu'à MAX_PER_CONFIG placements.

Chaque solution est sauvegardée dans enumerate_solutions/ sous forme de fichier
CSV. Arrêt manuel possible avec Ctrl+C.
"""

import os
from datetime import datetime

from ortools.sat.python import cp_model
from solution_formatter import _parse_relais, _save_csv
from constraint_model import build_model, build_model_fixed_config, RUNNERS
from data import RUNNERS_DATA
import analyze_solutions

OUTDIR = "enumerate_solutions"
OPTIMAL_BINOMES_NUM = 19  # None = recherche automatique, int = valeur connue
TIME_LIMIT_FIRST = 300.0  # secondes pour trouver le score optimal (si OPTIMAL_BINOMES_NUM is None)
TIME_LIMIT_ENUM = 300.0    # secondes par itération d'énumération
MAX_PER_CONFIG = 5       # placements max par configuration de binômes
MAX_CONFIGS = 2         # configs max en phase 1 (None ou 0 = pas de limite)
SOLVER_NUM_WORKERS = 8


def _save_one(solver, start, size, same_relay, relais_solo, night_relay, run_ts, config_idx, place_idx):
    os.makedirs(OUTDIR, exist_ok=True)
    base = os.path.join(OUTDIR, f"run_{run_ts}_config_{config_idx:03d}_place_{place_idx:02d}")

    relais_list = _parse_relais(solver, start, size, same_relay, relais_solo, night_relay)
    _save_csv(relais_list, base + ".csv")

    print(f"  → {base}.csv")


def _collect_configs(model, start, size, same_relay, relais_solo, night_relay, solver, optimal_score, run_ts):
    """Étape 1 : énumère toutes les configurations de binômes, sauvegarde place_00 et retourne la liste."""
    model.add(sum(same_relay.values()) >= optimal_score)
    solver.parameters.max_time_in_seconds = TIME_LIMIT_ENUM

    configs = []  # liste de active_keys

    try:
        while True:
            status = solver.solve(model)
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                print("\nPlus de configuration de binômes disponible.")
                break

            config_idx = len(configs) + 1
            active_keys = frozenset(key for key, bv in same_relay.items() if solver.boolean_value(bv))
            configs.append(active_keys)
            print(f"  Config {config_idx} trouvée ({len(active_keys)} binômes actifs)")

            _save_one(solver, start, size, same_relay, relais_solo, night_relay, run_ts, config_idx, 0)

            if MAX_CONFIGS and len(configs) >= MAX_CONFIGS:
                print(f"\nLimite de {MAX_CONFIGS} configurations atteinte.")
                break

            # Coupure : la prochaine config doit changer au moins un binôme actif
            active_bvs = [bv for key, bv in same_relay.items() if key in active_keys]
            model.add_bool_or([~b for b in active_bvs])

    except KeyboardInterrupt:
        print("\nArrêt manuel pendant l'étape 1.")

    return configs


def enumerate_solutions():
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = SOLVER_NUM_WORKERS
    solver.parameters.log_search_progress = False

    # --- Étape 1 : trouver le score optimal puis collecter les configurations de binômes ---
    print("Construction du modèle de référence...")
    model, start, size, same_relay, relais_solo, night_relay = build_model()

    if OPTIMAL_BINOMES_NUM is not None:
        optimal_score = OPTIMAL_BINOMES_NUM
        print(f"Score optimal (fourni) : {optimal_score} binômes\n")
    else:
        print("Recherche du score optimal...")
        model.maximize(sum(same_relay.values()))
        solver.parameters.max_time_in_seconds = TIME_LIMIT_FIRST
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            print("Aucune solution trouvée.")
            return
        optimal_score = int(solver.objective_value)
        print(f"Score optimal : {optimal_score} binômes\n")
        model.clear_objective()

    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"Run timestamp : {run_ts}")

    print("Étape 1 : collecte des configurations de binômes...")
    print("  Ctrl-C (1 fois) pour stopper la phase 1 et passer à la phase 2")
    configs = _collect_configs(model, start, size, same_relay, relais_solo, night_relay, solver, optimal_score, run_ts)
    print(f"\n{len(configs)} configuration(s) de binômes collectée(s).\n")

    if not configs:
        print("Aucune configuration trouvée.")
        return

    # --- Étape 2 : pour chaque configuration, énumérer les placements ---
    print("Étape 2 : énumération des placements par configuration...")
    print("  Ctrl-C pour terminer")
    n_total = 0

    try:
        for config_idx, active_keys in enumerate(configs, start=1):
            print(f"\nConfiguration {config_idx}/{len(configs)} ({len(active_keys)} binômes actifs) :")

            model_f, start_f, size_f, same_relay_f, relais_solo_f, night_relay_f = build_model_fixed_config(
                active_keys, optimal_score
            )
            solver_f = cp_model.CpSolver()
            solver_f.parameters.num_workers = SOLVER_NUM_WORKERS
            solver_f.parameters.log_search_progress = False
            solver_f.parameters.max_time_in_seconds = TIME_LIMIT_ENUM

            status = solver_f.solve(model_f)
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                print("  Aucun placement trouvé pour cette configuration.")
                continue

            n_total += 1
            _save_one(solver_f, start_f, size_f, same_relay_f, relais_solo_f, night_relay_f, run_ts, config_idx, 1)

            def _add_cut(model_f, start_f, place_idx):
                """Ajoute une contrainte excluant le placement courant du solveur."""
                start_vals = {r: [solver_f.value(start_f[r][k]) for k in range(len(RUNNERS_DATA[r].relais))]
                              for r in RUNNERS}
                cut_lits = []
                for r in RUNNERS:
                    for k in range(len(RUNNERS_DATA[r].relais)):
                        val = start_vals[r][k]
                        b = model_f.new_bool_var(f"cut_{place_idx}_{r}_{k}")
                        model_f.add(start_f[r][k] != val).only_enforce_if(b)
                        model_f.add(start_f[r][k] == val).only_enforce_if(~b)
                        cut_lits.append(b)
                model_f.add_bool_or(cut_lits)

            _add_cut(model_f, start_f, 1)
            n_places = 1
            for place_idx in range(2, MAX_PER_CONFIG + 1):
                status = solver_f.solve(model_f)
                if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    break

                n_total += 1
                n_places += 1
                _save_one(solver_f, start_f, size_f, same_relay_f, relais_solo_f, night_relay_f, run_ts, config_idx, place_idx)
                _add_cut(model_f, start_f, place_idx)

            print(f"  {n_places} placement(s) pour la configuration {config_idx}.")

    except KeyboardInterrupt:
        print("\nArrêt manuel pendant l'étape 2.")

    print(f"\nTotal : {n_total} solution(s) sauvegardée(s) dans {len(configs)} configuration(s).")

    if n_total > 0:
        print("\nLancement de l'analyse des solutions...")
        analyze_solutions.main()


if __name__ == "__main__":
    enumerate_solutions()
