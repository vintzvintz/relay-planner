"""
Solveur CP-SAT — relais Lyon-Fessenheim.

Lance une résolution simple avec objectif de maximisation des binômes.
La construction du modèle est déléguée à constraint_model.
"""

import queue
import threading

from ortools.sat.python import cp_model
from .solution import Solution


# Paramètres solveur
SOLVER_TIME_LIMIT = 0        # secondes
SOLVER_NUM_WORKERS = 8

_SENTINEL = object()


class _SolveCallback(cp_model.CpSolverSolutionCallback):
    """Pousse chaque solution dans une queue et stoppe selon les critères max_count / target_score."""

    def __init__(self, relay_model, constraints, target_score, max_count, q):
        super().__init__()
        self._relay_model = relay_model
        self._constraints = constraints
        self._target_score = target_score
        self._max_count = max_count
        self._q = q
        self._count = 0

    def on_solution_callback(self):
        sol = Solution.from_cpsat(self)
        self._q.put(sol)
        self._count += 1
        if self._max_count and self._count >= self._max_count:
            self.stop_search()
        if self._target_score and self.objective_value >= self._target_score:
            self.stop_search()


class Solver:
    def __init__(self, model, constraints):
        self.model = model
        self.constraints = constraints

    def solve(self, timeout_sec=0, target_score=0, max_count=0, log_progress=True):
        """Itérateur streaming sur les solutions CP-SAT.

        Yields chaque solution sous forme de list[dict] dès qu'elle est trouvée.
        Le solveur tourne dans un thread séparé ; les solutions transitent par une queue.
        S'arrête dès que l'un des critères actifs est atteint :
        - max_count   : nombre maximal de solutions yielded (0 = illimité)
        - target_score: score objectif suffisant (0 = désactivé)
        - timeout_sec : limite de temps en secondes (0 = illimité)
        """
        solver = cp_model.CpSolver()
        if timeout_sec:
            solver.parameters.max_time_in_seconds = float(timeout_sec)
        solver.parameters.log_search_progress = log_progress
        solver.parameters.num_workers = SOLVER_NUM_WORKERS

        q = queue.Queue()
        callback = _SolveCallback(self.model, self.constraints, target_score, max_count, q)

        def _run():
            solver.solve(self.model.model, callback)
            q.put(_SENTINEL)

        print(f"Résolution en cours timeout={timeout_sec}s target_score={target_score}, max_count={max_count}")
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        while True:
            solu = q.get()
            if solu is _SENTINEL:
                break
            if not solu.valid:
                # remplacer l'exception par "continue' pour poursuivre la résolution malgré l'erreur
                raise ValueError("solution invalide")
            yield solu

        thread.join()



