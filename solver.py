"""
Solveur CP-SAT — relais Lyon-Fessenheim.

Lance une résolution simple avec objectif de maximisation des binômes.
La construction du modèle est déléguée à model_builder.
"""

from ortools.sat.python import cp_model
from constraint_model import build_model
from solution_formatter import save_solution

# Paramètres solveur
SOLVER_TIME_LIMIT = 300.0  # secondes
SOLVER_NUM_WORKERS = 8
ACCEPTABLE_BINOME_COUNT = None  # arrête la recherche dès qu'une solution atteint ce nombre de binômes



class _BinomeTargetCallback(cp_model.CpSolverSolutionCallback):
    """Sauvegarde chaque solution trouvée et stoppe dès ACCEPTABLE_BINOME_COUNT binômes."""

    def __init__(self, target, start, same_relay, relais_solo, night_relay):
        super().__init__()
        self._target = target
        self._start = start
        self._same_relay = same_relay
        self._relais_solo = relais_solo
        self._night_relay = night_relay

    def on_solution_callback(self):
        save_solution(self, self._start, self._same_relay, self._relais_solo, self._night_relay)
        if self._target and (self.objective_value >= self._target):
            self.stop_search()


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

    print("Résolution en cours...", flush=True)
    callback = _BinomeTargetCallback(
        ACCEPTABLE_BINOME_COUNT, start, same_relay, relais_solo, night_relay
    )
    status = solver.solve(model, callback)

    print(f"\nStatut : {solver.status_name(status)}")
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("Aucune solution trouvée.")

    return solver, status


if __name__ == "__main__":
    build_and_solve()
