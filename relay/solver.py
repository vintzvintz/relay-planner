
from .model import Model
from .constraints import Constraints
from .solution import Solution

# Paramètres solveur
SOLVER_TIME_LIMIT = 0        # secondes
SOLVER_NUM_WORKERS = 10


class Solver:
    """Solveur CP-SAT pour le modèle waypoint.

    Usage :
        solver = Solver(model, constraints)
        for sol in solver.solve(timeout_sec=60):
            sol.print_summary()
    """

    def __init__(self, model: "Model", constraints: "Constraints"):
        self.model = model
        self.constraints = constraints

    def solve(self, timeout_sec: float = SOLVER_TIME_LIMIT, max_count: int = 0, log_progress: bool = True):
        import queue
        import threading
        from ortools.sat.python import cp_model

        _SENTINEL = object()
        q: queue.Queue = queue.Queue()
        relay_model = self.model
        c = self.constraints

        class _Callback(cp_model.CpSolverSolutionCallback):
            def __init__(self):
                super().__init__()
                self._relay_model = relay_model
                self._constraints = c
                self._count = 0

            def on_solution_callback(self):
                sol = Solution.from_cpsat(self)
                self._count += 1
                q.put(sol)
                if max_count and self._count >= max_count:
                    self.stop_search()

        solver = cp_model.CpSolver()
        if timeout_sec:
            solver.parameters.max_time_in_seconds = float(timeout_sec)
        solver.parameters.log_search_progress = log_progress
        solver.parameters.num_workers = SOLVER_NUM_WORKERS

        callback = _Callback()

        def _run():
            solver.solve(relay_model.model, callback)
            q.put(_SENTINEL)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        while True:
            item = q.get()
            if item is _SENTINEL:
                break
            yield item

        thread.join()
