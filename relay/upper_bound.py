"""Calcul du majorant du score (relaxation LP GLOP ou modèle CP-SAT simplifié)."""

from collections import defaultdict
from typing import NamedTuple

BINOME_WEIGHT = 2  # dupliqué depuis model.py — voir commentaire là-bas


class LpBounds(NamedTuple):
    upper_bound: int
    upper_bound_exact: float
    solo_nb: float
    solo_km: float


def _count_by_size(relays: list[int]) -> dict[int, int]:
    counts: dict[int, int] = defaultdict(int)
    for s in relays:
        counts[s] += 1
    return dict(counts)


def _compute_upper_bound_glop(constraints) -> LpBounds | None:
    """
    Calcule un majorant du score par relaxation LP (GLOP).

    Variables : b[r1, r2, s] ∈ [0, min(count(r1,s), count(r2,s))]
    pour chaque paire compatible (r1 < r2) et taille s.

    Contraintes :
    (1) pour chaque coureur r et taille s : Σ_{r2} b[r,r2,s] ≤ count(r,s)
    (2) surplus exact : Σ_{r1,r2,s} s * b[r1,r2,s] = surplus

    Objectif : maximiser Σ BINOME_WEIGHT * compat_score * b[r1,r2,s]

    Retourne LpBounds ou None si la résolution échoue.
    """
    from ortools.linear_solver import pywraplp

    req_sizes = {r: [max(spec.size) for spec in cd.relais] for r, cd in constraints.runners_data.items()}
    total_segs_engaged = sum(sum(sizes) for sizes in req_sizes.values())
    surplus = total_segs_engaged - constraints.nb_active_segments

    solver = pywraplp.Solver.CreateSolver("GLOP")

    counts = {r: _count_by_size(sizes) for r, sizes in req_sizes.items()}
    all_sizes = sorted({s for sizes in req_sizes.values() for s in sizes})

    # Variables b[r1, r2, s] avec r1 < r2 (ordre de la liste runners)
    b = {}
    for s in all_sizes:
        for i, r1 in enumerate(constraints.runners):
            if counts[r1].get(s, 0) == 0:
                continue
            for r2 in constraints.runners[i + 1:]:
                if counts[r2].get(s, 0) == 0:
                    continue
                if constraints.compat_score(r1, r2) == 0:
                    continue
                ub = min(counts[r1][s], counts[r2][s])
                b[(r1, r2, s)] = solver.NumVar(0.0, ub, f"b_{r1}_{r2}_{s}")

    # Contrainte (1) : capacité par coureur et taille
    for r in constraints.runners:
        for s in all_sizes:
            c = counts[r].get(s, 0)
            if c == 0:
                continue
            terms = [var for (r1, r2, sz), var in b.items() if sz == s and (r1 == r or r2 == r)]
            if terms:
                ct = solver.Constraint(0.0, c)
                for v in terms:
                    ct.SetCoefficient(v, 1.0)

    # Contrainte (2) : surplus exact
    ct_surplus = solver.Constraint(surplus, surplus)
    for (r1, r2, s), var in b.items():
        ct_surplus.SetCoefficient(var, float(s))

    # ATTENTION : cette formule est dupliquée en quatre endroits — tout changement
    # doit être répercuté simultanément dans :
    #   - relay/model.py       : _objective_expr()      (fonction objectif CP-SAT)
    #   - relay/upper_bound.py : _compute_upper_bound_glop()  (relaxation LP GLOP)
    #   - relay/upper_bound.py : _compute_upper_bound_cpsat() (majorant CP-SAT)
    #   - relay/solution.py    : Solution.stats()              (recalcul post-solve)
    obj = solver.Objective()
    for (r1, r2, s), var in b.items():
        obj.SetCoefficient(var, float(BINOME_WEIGHT * constraints.compat_score(r1, r2)))
    obj.SetMaximization()

    status = solver.Solve()
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return None

    bound = solver.Objective().Value()

    binomes_r: dict[str, dict[int, float]] = {r: defaultdict(float) for r in constraints.runners}
    for (r1, r2, s), var in b.items():
        v = var.solution_value()
        binomes_r[r1][s] += v
        binomes_r[r2][s] += v

    solo_km = {
        r: sum((counts[r].get(s, 0) - binomes_r[r][s]) * s * constraints.segment_km for s in all_sizes)
        for r in constraints.runners
    }
    solo_nb = {
        r: sum(max(0.0, counts[r].get(s, 0) - binomes_r[r][s]) for s in all_sizes)
        for r in constraints.runners
    }

    return LpBounds(
        upper_bound=int(bound),
        upper_bound_exact=bound,
        solo_nb=sum(solo_nb.values()),
        solo_km=sum(solo_km.values()),
    )


def _compute_upper_bound_cpsat(constraints, timeout_sec: float = 3.0) -> LpBounds | None:
    """
    Calcule un majorant du score via un modèle CP-SAT simplifié (sans positionnement).

    Modèle :
    - nb_binomes[r1,r2,s] ∈ [0, min(count(r1,s), count(r2,s))] : nombre de binômes
      de taille s entre r1 et r2 (paires compatibles uniquement)
    - Contrainte de couplage : Σ_{r2} nb_binomes[r,r2,s] ≤ count(r,s) pour chaque r,s
    - Surplus ≤ : Σ_{r1,r2,s} s * nb_binomes[r1,r2,s] ≤ surplus
    - Solo interdit : relais de taille > solo_max_size doivent être en binôme

    Contraintes volontairement ignorées (pour un majorant plus rapide) :
    repos, pauses, limites nuit/solo par coureur, max_same_partenaire,
    once_max, paired_relays.

    Objectif : maximiser BINOME_WEIGHT * Σ compat_score(r1,r2) * nb_binomes[r1,r2,s]
    Retourne LpBounds ou None si la résolution échoue.
    """
    from ortools.sat.python import cp_model

    req_sizes = {r: [max(spec.size) for spec in cd.relais] for r, cd in constraints.runners_data.items()}
    total_segs_engaged = sum(sum(sizes) for sizes in req_sizes.values())
    surplus = total_segs_engaged - constraints.nb_active_segments
    counts = {r: _count_by_size(sizes) for r, sizes in req_sizes.items()}
    all_sizes = sorted({s for sizes in req_sizes.values() for s in sizes})

    model = cp_model.CpModel()

    # Variables nb_binomes[r1, r2, s] : nombre de binômes de taille s entre r1 et r2
    bv: dict[tuple[str, str, int], cp_model.IntVar] = {}
    for s in all_sizes:
        for i, r1 in enumerate(constraints.runners):
            c1 = counts[r1].get(s, 0)
            if c1 == 0:
                continue
            for r2 in constraints.runners[i + 1:]:
                c2 = counts[r2].get(s, 0)
                if c2 == 0:
                    continue
                if constraints.compat_score(r1, r2) == 0:
                    continue
                ub = min(c1, c2)
                bv[(r1, r2, s)] = model.new_int_var(0, ub, f"b_{r1}_{r2}_{s}")

    # Contrainte de couplage : Σ_r2 nb_binomes[r,r2,s] ≤ count(r,s)
    for r in constraints.runners:
        for s in all_sizes:
            c = counts[r].get(s, 0)
            if c == 0:
                continue
            terms = [var for (r1, r2, sz), var in bv.items() if sz == s and (r1 == r or r2 == r)]
            if not terms:
                continue
            model.add(sum(terms) <= c)

    # Contrainte surplus : les binômes ne peuvent pas couvrir plus que le surplus disponible
    surplus_terms = []
    for (r1, r2, s), var in bv.items():
        surplus_terms.append(s * var)
    model.add(sum(surplus_terms) <= surplus)

    # Solo interdit pour les relais de taille > solo_max_size :
    # ces relais DOIVENT être en binôme → nombre minimum de binômes par (coureur, taille)
    forced = {r: defaultdict(int) for r in constraints.runners}
    for r, cd in constraints.runners_data.items():
        for spec in cd.relais:
            s = max(spec.size)
            if s > constraints.solo_max_size:
                forced[r][s] += 1
    for r in constraints.runners:
        for s, nb in forced[r].items():
            terms = [var for (r1, r2, sz), var in bv.items() if sz == s and (r1 == r or r2 == r)]
            if terms:
                model.add(sum(terms) >= nb)

    # ATTENTION : cette formule est dupliquée en quatre endroits — tout changement
    # doit être répercuté simultanément dans :
    #   - relay/model.py       : _objective_expr()      (fonction objectif CP-SAT)
    #   - relay/upper_bound.py : _compute_upper_bound_glop()  (relaxation LP GLOP)
    #   - relay/upper_bound.py : _compute_upper_bound_cpsat() (majorant CP-SAT)
    #   - relay/solution.py    : Solution.stats()              (recalcul post-solve)
    obj_terms = []
    for (r1, r2, s), var in bv.items():
        w = BINOME_WEIGHT * constraints.compat_score(r1, r2)
        if w:
            obj_terms.append(w * var)
    model.maximize(sum(obj_terms))

    cp_solver = cp_model.CpSolver()
    cp_solver.parameters.max_time_in_seconds = timeout_sec
    cp_solver.parameters.num_workers = 1  # modèle petit, 1 worker suffit
    status = cp_solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    bound = cp_solver.objective_value

    # Solos par coureur
    binomes_r: dict[str, dict[int, float]] = {r: defaultdict(float) for r in constraints.runners}
    for (r1, r2, s), var in bv.items():
        v = cp_solver.value(var)
        binomes_r[r1][s] += v
        binomes_r[r2][s] += v

    solo_km = {
        r: sum((counts[r].get(s, 0) - binomes_r[r][s]) * s * constraints.segment_km for s in all_sizes)
        for r in constraints.runners
    }
    solo_nb = {
        r: sum(max(0.0, counts[r].get(s, 0) - binomes_r[r][s]) for s in all_sizes)
        for r in constraints.runners
    }

    return LpBounds(
        upper_bound=int(bound),
        upper_bound_exact=bound,
        solo_nb=sum(solo_nb.values()),
        solo_km=sum(solo_km.values()),
    )


def compute_upper_bound(constraints, method: str = "cpsat", timeout_sec: float = 3.0) -> None:
    """
    Calcule un majorant du score et le stocke dans constraints._lp_bounds.

    method : "glop" (défaut, relaxation LP, instantané) ou "cpsat" (modèle entier simplifié)
    timeout_sec : uniquement pour method="cpsat"

    Stocke le résultat dans constraints._lp_bounds et passe constraints._lp_computed à True.
    """
    result = None
    if method != "glop":
        result = _compute_upper_bound_cpsat(constraints, timeout_sec=timeout_sec)
    if result is None:
        result = _compute_upper_bound_glop(constraints)

    constraints._lp_bounds = result
    constraints._lp_computed = True
