"""
relay -- CP-SAT relay race scheduler.

Solves a multi-day relay race scheduling problem (e.g. Lyon-Fessenheim, 440 km,
15 runners) using Google OR-Tools CP-SAT.  Handles segment coverage, runner
compatibility, rest constraints, night limits, solo limits, flexible relay
sizes, forced pairings, and planned pauses.

Quick start
-----------
::

    from relay import Constraints, Intervals, R10, R15, R20, R30
    from compat import COMPAT_MATRIX

    c = Constraints(
        total_km=440, nb_segments=176, speed_kmh=9.0, start_hour=15.0,
        compat_matrix=COMPAT_MATRIX, solo_max_km=17, solo_max_default=1,
        nuit_max_default=1, repos_jour_heures=7, repos_nuit_heures=9,
        nuit_debut=23.5, nuit_fin=6.0,
    )
    runner = c.new_runner("Alice")
    runner.add_relay(R15, nb=3)
    # ... declare more runners ...

    solve(c)                           # build, optimise, save solutions

Public API
----------
Constraints         Declare race parameters, runners, relays, and pauses.
Intervals           Segment-index windows for runner availability.
SharedLeg           Shared relay for forced pairings (binomes).
model(constraints)  Factory: build a Model from a Constraints object.
Solver              Streaming CP-SAT solver; yields Solution objects.
Solution            Verified solution with text/CSV/JSON/HTML export.
solve(c)            Build model, optimise, solve, and save all solutions.
R10 .. R15_F        Relay-type string constants.
"""

# -- constraints ----------------------------------------------------------
from relay.constraints import Constraints
from relay.constraints import Intervals
from relay.constraints import SharedLeg
from relay.constraints import R10, R15, R20, R30, R13_F, R15_F

# -- model ----------------------------------------------------------------
from relay.model import build_model as model

# -- solver ---------------------------------------------------------------
from relay.solver import Solver

# -- solution -------------------------------------------------------------
from relay.solution import Solution

# -- feasibility (internal use via entry_point) ---------------------------
from relay.feasibility import analyse as diagnose

# -- gpx export -----------------------------------------------------------
from relay.gpx import solution_to_gpx, solution_to_kml

def replanif(constraints, *, reference, min_score=None, timeout_sec=0):
    """Solve by minimising differences with a reference solution.

    Parameters
    ----------
    reference : str
        Path to a JSON reference solution file.
    min_score : int | None
        If given, add a minimum score constraint.
    """
    ref_sol = Solution.from_json(reference)
    print(f"Référence chargée depuis {reference} ({len(ref_sol.relays)} relais)")
    m = model(constraints)
    m.add_minimise_differences_with(ref_sol)
    if min_score is not None:
        m.add_min_score(constraints, min_score)
        print(f"Score minimal fixé à {min_score}")
    solver = Solver(m, constraints)
    for sol in solver.solve(timeout_sec=timeout_sec):
        sol.save()

def solve(constraints, *, min_score=None, timeout_sec=0):
    """Build model, set objective, solve, and save each solution found."""
    m = model(constraints)
    m.add_optimisation_func(constraints)
    if min_score is not None:
        m.add_min_score(constraints, min_score)
        print(f"Score minimal fixé à {min_score}")
    solver = Solver(m, constraints)
    for sol in solver.solve(timeout_sec=timeout_sec):
        sol.save()


def optimise_dplus(constraints, *, min_score=None, timeout_sec=0):
    """Maximise sum(lvl[r] * (D+ + D-)) sous contrainte de score minimal.

    Parameters
    ----------
    min_score : int | None
        Score binôme minimal à respecter. Si None, aucune contrainte de score.
        Passer le score optimal issu d'un premier appel à solve() pour obtenir
        un planning maximisant le dénivelé tout en préservant la qualité des binômes.
    """
    m = model(constraints)
    if min_score is not None:
        m.add_min_score(constraints, min_score)
    m.add_optimise_dplus(constraints)
    solver = Solver(m, constraints)
    for sol in solver.solve(timeout_sec=timeout_sec):
        sol.save()


def _parse_replanif(argv):
    """Parse --replanif <file> [--min-score <n>] from argv.

    Returns (reference_path, min_score) or None if --replanif not present.
    """
    if "--replanif" not in argv:
        return None
    idx = argv.index("--replanif")
    if idx + 1 >= len(argv) or argv[idx + 1].startswith("--"):
        raise ValueError("--replanif nécessite un fichier JSON en argument")
    reference = argv[idx + 1]
    min_score = None
    if "--min-score" in argv:
        ms_idx = argv.index("--min-score")
        if ms_idx + 1 >= len(argv):
            raise ValueError("--min-score nécessite une valeur numérique")
        min_score = int(argv[ms_idx + 1])
    return reference, min_score


def entry_point(constraints):
    """CLI entry point: dispatch --summary, --diag, --model, --replanif, --dplus, or default solve."""
    import sys
    argv = sys.argv
    if "--summary" in argv:
        constraints.print_summary()
    elif "--diag" in argv:
        diagnose(constraints)
    elif "--model" in argv:
        model(constraints)
    elif "--replanif" in argv:
        reference, min_score = _parse_replanif(argv)
        replanif(constraints, reference=reference, min_score=min_score)
    elif "--dplus" in argv:
        min_score = None
        if "--min-score" in argv:
            idx = argv.index("--min-score")
            if idx + 1 >= len(argv):
                raise ValueError("--min-score nécessite une valeur numérique")
            min_score = int(argv[idx + 1])
        optimise_dplus(constraints, min_score=min_score)
    else:
        solve(constraints)


__all__ = [
    "Constraints", "Intervals", "SharedLeg",
    "R10", "R15", "R20", "R30", "R13_F", "R15_F",
    "model",
    "Solver",
    "Solution",
    "replanif", "solve", "optimise_dplus", "entry_point",
]
