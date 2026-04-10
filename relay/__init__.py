"""
relay -- CP-SAT relay race scheduler (waypoint model).

Solves a multi-day relay race scheduling problem (~440 km,
~180 GPS waypoints, 15 runners) using Google OR-Tools CP-SAT. Handles waypoint
coverage, runner compatibility, rest constraints, night limits, solo limits,
flexible relay sizes, forced pairings (binômes), planned pauses, and D+/D-
assignment by runner level.

Typical workflow
----------------
1. Declare race data in a script and call ``entry_point(c)``::

       from relay.constraints import Constraints, Preset
       from relay import entry_point

       R15 = Preset(km=15, min=13, max=17)
       c = Constraints(waypoints="gpx/relay_points.json", speed_kmh=9.0,
                       start_hour=14.0, compat_matrix="compat_coureurs.xlsx")
       alice = c.new_runner("Alice", lvl=4)
       alice.add_relay(R15, nb=3)
       entry_point(c)

2. Check theoretical bounds::

       python example.py data   # shows ub_score_target, ub_score_max, lb_solos

3. Optimise duo score::

       python example.py solve [--min-score N]

4. Save best solution to ``refs/``, then optimise D+ distribution::

       python example.py dplus --ref refs/solution.json --min-score N

5. Replan after data changes (injured runner, elapsed legs, shifted pause)::

       python example.py replanif --ref refs/solution.json [--min-score N]

Public API
----------
Constraints             Declare race parameters, runners, relays, and pauses.
Interval                Waypoint-index window; produced by Constraints.interval_*() factories.
SharedLeg               Shared relay for forced pairings (binômes).
model(constraints)      Factory: build a Model from a Constraints object.
Solver                  Streaming CP-SAT solver; yields Solution objects.
Solution                Verified solution with text/CSV/JSON/HTML/GPX/KML export.
solve(c)                Maximise duo compatibility score; save all solutions found.
optimise_dplus(c)       Maximise weighted D+/D- by runner level under a min-score constraint.
replanif(c)             Minimise differences with a reference solution.
entry_point(c)          CLI dispatcher (solve / data / diag / dplus / replanif).
"""

# Expose les fonctions élémentaires accessibles au niveau package
from .constraints import Constraints
from .model import build_model
from .solver import Solver
from .solution import Solution
from .feasibility import diag_faisabilite
from ._dirs import PLANNING_DIR, latest_solution_path, latest_solution

import os
from datetime import datetime


def _load_hint(m, hint_path):
    """Charge un fichier JSON de solution comme hint CP-SAT si le fichier existe."""
    if hint_path and os.path.exists(hint_path):
        ref_sol = Solution.from_json(hint_path)
        print(f"Hint chargé depuis {hint_path} ({len(ref_sol.relays)} relais)")
        m.add_hint_from_solution(ref_sol)
    elif hint_path:
        print(f"Hint ignoré : fichier introuvable ({hint_path})")


def _make_base(action: str) -> str:
    """Génère le chemin de base (sans extension) pour une résolution, fixé une fois pour toutes."""
    from pathlib import Path
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(PLANNING_DIR) / f"{ts}_{action}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return str(run_dir / "planning")


def _solve_and_save(m, constraints, *, base, action, timeout_sec, split):
    import sys
    import time
    from .verifications import check

    if base is None:
        base = _make_base(action)

    solver = Solver(m, constraints)
    start_time = time.time()
    solution_count = 0

    print(f"🚀 Démarrage de la résolution ({action})...")
    if timeout_sec:
        print(f"⏱️  Timeout : {timeout_sec:.0f} secondes")
    else:
        print(f"⏱️  Timeout : illimité")

    try:
        for sol in solver.solve(timeout_sec=timeout_sec):
            solution_count += 1
            elapsed = time.time() - start_time

            # Vérifier l'intégrité de la solution avant sauvegarde
            ok, check_output = check(sol)

            if not ok:
                print(check_output.getvalue())  # Afficher les résultats des vérifications
                raise RuntimeError("Solution invalide. Voir erreurs de vérification ci-dessus.")

            sol.save(base=base, split=split)

        elapsed_total = time.time() - start_time
        print(f"\n✨ Résolution terminée : {solution_count} solution(s) trouvée(s) en {elapsed_total:.1f}s")
        if solution_count == 0:
            print(f"⚠️  Aucune solution trouvée (modèle potentiellement infaisable)", file=sys.stderr)
            print(f"    Utiliser : python example.py diag", file=sys.stderr)

    except Exception as e:
        elapsed_total = time.time() - start_time
        print(f"\n❌ Erreur après {elapsed_total:.1f}s", file=sys.stderr)
        raise


def replanif(constraints, *, base=None, action="replanif", reference, min_score=None, timeout_sec=0, split=True):
    """Solve by minimising differences with a reference solution.

    Parameters
    ----------
    reference : str
        Path to a JSON reference solution file.
    min_score : int | None
        If given, add a minimum score constraint.
    """
    try:
        ref_sol = Solution.from_json(reference)
        print(f"Référence chargée depuis {reference} ({len(ref_sol.relays)} relais)")
        m = build_model(constraints, min_score=min_score)
        m.add_minimise_differences_with(ref_sol, constraints)
        _solve_and_save(m, constraints, base=base, action=action, timeout_sec=timeout_sec, split=split)
    except FileNotFoundError:
        raise FileNotFoundError(f"Fichier référence introuvable : {reference}")
    except ValueError as e:
        raise ValueError(f"Erreur lors de la replanification : {e}")


def solve(constraints, *, base=None, action="solve", min_score=None, hint=None, timeout_sec=0, split=True):
    """Build model, set objective, solve, and save each solution found."""
    try:
        m = build_model(constraints, min_score=min_score)
        m.add_optimisation_func(constraints)
        _load_hint(m, hint)
        _solve_and_save(m, constraints, base=base, action=action, timeout_sec=timeout_sec, split=split)
    except ValueError as e:
        raise ValueError(f"Erreur lors de la résolution : {e}")


def optimise_dplus(constraints, *, base=None, action="dplus", min_score=None, hint=None, timeout_sec=0, split=True):
    """Maximise sum(lvl[r] * (D+ + D-)) sous contrainte de score minimal.

    Parameters
    ----------
    min_score : int | None
        Score binôme minimal à respecter. Si None, aucune contrainte de score.
        Passer le score optimal issu d'un premier appel à solve() pour obtenir
        un planning maximisant le dénivelé tout en préservant la qualité des binômes.
    hint : str | None
        Chemin vers un fichier JSON de solution à fournir comme hint initial au solveur.
    """
    try:
        m = build_model(constraints, min_score=min_score)
        m.add_optimise_dplus(constraints)
        _load_hint(m, hint)
        _solve_and_save(m, constraints, base=base, action=action, timeout_sec=timeout_sec, split=split)
    except ValueError as e:
        raise ValueError(f"Erreur lors de l'optimisation D+ : {e}")


def entry_point(constraints):
    """CLI entry point: python example.py [action] [--options]

    action (positional, optionnel) :
      data      Afficher le résumé des données
      solve     Résoudre (défaut si absent)
      dplus     Maximiser le dénivelé pondéré D+/D-
      replanif  Replanifier par rapport à --ref (obligatoire)
      diag      Analyser la faisabilité

    options :
      --split   Exporter des fichiers GPX/KML individuels par relais après résolution
    """
    import sys
    import argparse

    parser = argparse.ArgumentParser(
        description="Relay race scheduler",
        usage="%(prog)s [action] [--options]",
    )
    parser.add_argument(
        "action",
        nargs="?",
        default="solve",
        choices=["data", "solve", "dplus", "replanif", "diag"],
        help="Action à effectuer (défaut : solve)",
    )
    parser.add_argument("--min-score", type=int, default=None, metavar="N",
                        help="Score binôme minimal")
    parser.add_argument("--ref", metavar="JSON", default=None,
                        help="Fichier solution JSON : hint pour solve/dplus, référence obligatoire pour replanif")
    parser.add_argument("--no-split", action="store_true", default=False,
                        help="Desactiver l'export des fichiers GPX/KML individuels par relais après résolution")

    args = parser.parse_args(sys.argv[1:])

    split = not args.no_split

    try:
        if args.action == "data":
            constraints.print_summary()
        elif args.action == "diag":
            diag_faisabilite(constraints)
        elif args.action == "replanif":
            if args.ref is None:
                parser.error("replanif requiert --ref <fichier.json>")
            replanif(constraints, reference=args.ref, min_score=args.min_score, split=split)
        elif args.action == "dplus":
            optimise_dplus(constraints, hint=args.ref, min_score=args.min_score,  split=split)
        else:  # solve
            solve(constraints, hint=args.ref, min_score=args.min_score, split=split)

    except ValueError as e:
        print(f"❌ Configuration invalide:\n{e}", file=sys.stderr)
        print("\nConsulter : docs/ERRORS.md pour des solutions", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"❌ Fichier manquant : {e}", file=sys.stderr)
        print("\nVérifier les chemins dans example.py :", file=sys.stderr)
        print("  - parcours_gpx", file=sys.stderr)
        print("  - compat_matrix (fichier .xlsx)", file=sys.stderr)
        print("  - --ref (fichier JSON pour replanif/hint)", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"❌ Erreur runtime : {e}", file=sys.stderr)
        print("\nConsulter : docs/ERRORS.md pour des solutions", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Erreur inattendue : {type(e).__name__}: {e}", file=sys.stderr)
        print("\nConsulter : docs/ERRORS.md ou signaler le bug", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


__all__ = [
    "Constraints",
    "build_model",
    "Solver",
    "Solution",
    "diag_faisabilite",
    "replanif", "solve", "optimise_dplus", "entry_point",
    "PLANNING_DIR",
    "latest_solution_path", "latest_solution",
]
