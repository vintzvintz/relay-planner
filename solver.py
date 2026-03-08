"""
Solveur CP-SAT — relais Lyon-Fessenheim.

Lance une résolution simple avec objectif de maximisation des binômes.
La construction du modèle est déléguée à model_builder.
"""

from ortools.sat.python import cp_model
from constraint_model import build_model
from solution_formatter import save_solution

# Paramètres solveur
SOLVER_TIME_LIMIT = 180.0  # secondes
SOLVER_NUM_WORKERS = 12


def build_and_solve():
    """Construit le modèle CP-SAT et lance la résolution.

    Retourne (solver, status) après résolution.
    """
    model, start, same_relay, relais_solo, night_relay = build_model()
    model.maximize(sum(same_relay.values()))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_TIME_LIMIT
    solver.parameters.log_search_progress = True
    solver.parameters.num_workers = SOLVER_NUM_WORKERS

    print("Résolution en cours...")
    status = solver.solve(model)

    print(f"\nStatut : {solver.status_name(status)}")
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print(f"Binômes : {int(solver.objective_value)}\n")
        save_solution(solver, start, same_relay, relais_solo, night_relay)
    else:
        print("Aucune solution trouvée.")

    return solver, status


if __name__ == "__main__":
    build_and_solve()
