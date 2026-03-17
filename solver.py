"""
Solveur CP-SAT — relais Lyon-Fessenheim.

Lance une résolution simple avec objectif de maximisation des binômes.
La construction du modèle est déléguée à constraint_model.
"""

import queue
import threading

from ortools.sat.python import cp_model
import solution

# Paramètres solveur
SOLVER_TIME_LIMIT = 5*3600.0  # secondes
SOLVER_NUM_WORKERS = 12

_SENTINEL = object()


def build_solution(model, constraints, solver) -> solution.RelaySolution:
    """Construit une RelaySolution à partir de l'état courant du solveur CP-SAT."""
    c = constraints
    segment_km = c.segment_km
    relais_list = []
    for r in c.runners:
        for k, (sz_declared, _flex) in enumerate(c.runners_data[r].relais):
            s = solver.value(model.start[r][k])
            e = solver.value(model.end[r][k])
            sz = solver.value(model.size[r][k])
            partner = None
            for key, bv in model.same_relay.items():
                if solver.value(bv) == 1:
                    if key[0] == r and key[1] == k:
                        partner = key[2]
                    elif key[2] == r and key[3] == k:
                        partner = key[0]
            relais_list.append(
                {
                    "runner": r,
                    "k": k,
                    "start": s,
                    "end": e,
                    "size": sz,
                    "km": sz * segment_km,
                    "flex": sz < sz_declared,
                    "solo": bool(solver.value(model.relais_solo[r][k])),
                    "night": bool(solver.value(model.relais_nuit[r][k])),
                    "partner": partner,
                }
            )
    relais_list.sort(key=lambda x: (x["start"], x["runner"]))

    # Calcul du temps de repos après chaque relais (None pour le dernier relais du coureur)
    by_runner = {}
    for rel in relais_list:
        by_runner.setdefault(rel["runner"], []).append(rel)
    for r_rels in by_runner.values():
        r_rels.sort(key=lambda x: x["start"])
        for i, rel in enumerate(r_rels):
            if i < len(r_rels) - 1:
                rel["rest_h"] = (
                    c.segment_start_hour(r_rels[i + 1]["start"])
                    - c.segment_start_hour(rel["end"])
                )
            else:
                rel["rest_h"] = None

    return solution.RelaySolution(relais_list, c, score=solver.objective_value)


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
        self._q.put(build_solution(self._relay_model, self._constraints, self))
        self._count += 1
        if self._max_count and self._count >= self._max_count:
            self.stop_search()
        if self._target_score and self.objective_value >= self._target_score:
            self.stop_search()


class RelaySolver:
    def __init__(self, model, constraints):
        self.model = model
        self.constraints = constraints

    def add_optimisation_func(self):
        self.model.add_optimisation_func(self.constraints)

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


if __name__ == "__main__":
    from data import build_constraints
    from model import build_model
    c = build_constraints()
    m = build_model(c)
    s = RelaySolver(m, c)
    s.add_optimisation_func()


    for sol in s.solve(target_score=0, timeout_sec=SOLVER_TIME_LIMIT):
        sol.save(verbose=solution.STATS)

