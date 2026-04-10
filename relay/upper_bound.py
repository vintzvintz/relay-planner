"""
relay/upper_bound.py

Majorant du score binôme via un modèle CP-SAT agrégé (sans positionnement).

Inspiré de relay/upper_bound.py::_compute_upper_bound_cpsat(), adapté au modèle waypoint.

Deux variantes de surplus sont calculées via deux résolutions CP-SAT distinctes,
en partageant la construction du modèle (variables, couplage, no-solo, objectif) :
  - target : taille = target_m  → borne heuristique, serrée mais non garantie
  - max    : taille = max_m     → borne garantie (toujours ≥ optimum réel)

Modèle :
  - nb_binomes[r1, r2] ∈ [0, min(nb_relais_r1, nb_relais_r2)] : entier agrégé
  - Couplage   : Σ_{r2} nb_binomes[r, r2] ≤ nb_relais[r]  pour chaque r
  - Surplus    : Σ_{r1,r2} size_saved * nb_binomes[r1,r2] ≤ surplus_m
  - No solo    : relais dont size > solo_max_m → nb_binomes_r ≥ nb_forced[r]

  Contraintes ignorées (majorant, pas score exact) :
    positionnement, couverture, repos, nuit, disponibilités, dplus_max,
    relais épinglés, max_same_partenaire, max_duos.

  Objectif : maximiser Σ compat_score(r1, r2) * nb_binomes[r1, r2]

Usage :
    from relay.upper_bound import compute_upper_bounds
    ub_target, ub_max = compute_upper_bounds(constraints, timeout_sec=3.0)
"""

from __future__ import annotations

from typing import NamedTuple

from ortools.sat.python import cp_model

from .constraints import Constraints


class UpperBound(NamedTuple):
    score: int          # majorant entier du score binôme
    score_exact: float  # valeur exacte retournée par le solveur
    n_binomes: int      # nombre de binômes dans la solution du majorant
    n_solos: int        # nombre de relais solo dans la solution du majorant


def _solve(
    constraints: Constraints,
    sizes: dict[str, list[int]],
    nb_relais: dict[str, int],
    nb_forced: dict[str, int],
    surplus_m: int,
    timeout_sec: float,
) -> UpperBound | None:
    """Résout le modèle agrégé pour un jeu de tailles et un surplus donnés."""
    c = constraints
    runners = c.runners

    model = cp_model.CpModel()

    bv: dict[tuple[str, str], cp_model.IntVar] = {}
    for i, r1 in enumerate(runners):
        for r2 in runners[i + 1:]:
            if nb_relais[r1] == 0 or nb_relais[r2] == 0:
                continue
            if c.compat_score(r1, r2) == 0:
                continue
            bv[(r1, r2)] = model.new_int_var(0, min(nb_relais[r1], nb_relais[r2]), f"nb_{r1}_{r2}")

    for r in runners:
        terms = [var for (ra, rb), var in bv.items() if ra == r or rb == r]
        if terms:
            model.add(sum(terms) <= nb_relais[r])

    surplus_terms = []
    for (r1, r2), var in bv.items():
        avg_r1 = sum(sizes[r1]) // nb_relais[r1]
        avg_r2 = sum(sizes[r2]) // nb_relais[r2]
        surplus_terms.append(max(avg_r1, avg_r2) * var)
    if surplus_terms:
        model.add(sum(surplus_terms) <= surplus_m)

    for r in runners:
        nb = nb_forced[r]
        if nb == 0:
            continue
        terms = [var for (ra, rb), var in bv.items() if ra == r or rb == r]
        if terms:
            model.add(sum(terms) >= nb)

    obj_terms = [c.compat_score(r1, r2) * var for (r1, r2), var in bv.items()]
    if obj_terms:
        model.maximize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout_sec
    solver.parameters.num_workers = 1
    solver.parameters.log_search_progress = False

    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    score_exact = solver.objective_value
    n_binomes = sum(solver.value(var) for var in bv.values())
    n_solos = sum(nb_relais.values()) - 2 * n_binomes
    return UpperBound(score=int(score_exact), score_exact=score_exact, n_binomes=n_binomes, n_solos=n_solos)


def compute_upper_bounds(
    constraints: Constraints,
    timeout_sec: float = 3.0,
) -> tuple[UpperBound | None, UpperBound | None]:
    """Calcule les deux majorants du score binôme.

    Retourne (ub_target, ub_max) :
      - ub_target : surplus avec taille=target_m — heuristique, serré mais non garanti
      - ub_max    : surplus avec taille=max_m    — garanti (toujours ≥ optimum réel)

    Chaque élément est None si le solveur n'a pas trouvé de solution.
    """
    c = constraints
    runners = c.runners
    parcours_m = c.cumul_m[-1]

    sizes_target: dict[str, list[int]] = {
        r: [spec.size_m(use_max=False) for spec in coureur.relais]
        for r, coureur in c.runners_data.items()
    }
    sizes_max: dict[str, list[int]] = {
        r: [spec.size_m(use_max=True) for spec in coureur.relais]
        for r, coureur in c.runners_data.items()
    }
    nb_relais: dict[str, int] = {r: len(sizes_target[r]) for r in runners}

    nb_forced: dict[str, int] = {
        r: sum(1 for s in sizes_target[r] if s > c.solo_max_m)
        for r in runners
    }
    for r, coureur in c.runners_data.items():
        if coureur.options.solo_max is not None and coureur.options.solo_max == 0:
            nb_forced[r] = nb_relais[r]

    surplus_target = sum(sum(s) for s in sizes_target.values()) - parcours_m
    surplus_max    = sum(sum(s) for s in sizes_max.values())    - parcours_m

    ub_target = _solve(c, sizes_target, nb_relais, nb_forced, surplus_target, timeout_sec)
    ub_max    = _solve(c, sizes_max,    nb_relais, nb_forced, surplus_max,    timeout_sec)
    return ub_target, ub_max
