"""
Solveur CP-SAT — relais Lyon-Fessenheim.

Lance une résolution simple avec objectif de maximisation des binômes.
La construction du modèle est déléguée à constraint_model.
"""

from ortools.sat.python import cp_model
from data import build_constraints
from constraint_model import build_model

# Paramètres solveur
SOLVER_TIME_LIMIT = 300.0  # secondes
SOLVER_NUM_WORKERS = 8
ACCEPTABLE_BINOME_COUNT = (
    None  # arrête la recherche dès qu'une solution atteint ce nombre de binômes
)


class _BinomeTargetCallback(cp_model.CpSolverSolutionCallback):
    """Sauvegarde chaque solution trouvée et stoppe dès ACCEPTABLE_BINOME_COUNT binômes."""

    def __init__(self, target, relay_model):
        super().__init__()
        self._target = target
        self._relay_model = relay_model

    def on_solution_callback(self):
        self._relay_model.solver = self
        self._relay_model.save_solution()
        if self._target and (self.objective_value >= self._target):
            self.stop_search()


def build_and_solve():
    """Construit le modèle CP-SAT et lance la résolution.

    Retourne (relay_model, solver, status) après résolution.
    """
    constraints = build_constraints()
    relay_model = build_model(constraints)
    relay_model.model.maximize(sum(relay_model.same_relay.values()))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_TIME_LIMIT
    solver.parameters.log_search_progress = True
    solver.parameters.num_workers = SOLVER_NUM_WORKERS

    print("Résolution en cours...", flush=True)
    callback = _BinomeTargetCallback(ACCEPTABLE_BINOME_COUNT, relay_model)
    status = solver.solve(relay_model.model, callback)

    relay_model.solver = solver
    print(f"\nStatut : {solver.status_name(status)}")
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("Aucune solution trouvée.")

    return relay_model, solver, status


if __name__ == "__main__":
    build_and_solve()
