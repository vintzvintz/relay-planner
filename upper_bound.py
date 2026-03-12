"""
Calcule un majorant du nombre de binômes par relaxation LP.

Variables : b[r1, r2, s] ∈ [0, min(count(r1,s), count(r2,s))]
  pour chaque paire compatible (r1 < r2) et taille s.

Contraintes :
  (1) pour chaque coureur r et taille s : Σ_{r2} b[r,r2,s] ≤ count(r,s)
  (2) surplus exact : Σ_{r1,r2,s} s * b[r1,r2,s] = surplus

Objectif : maximiser Σ b[r1,r2,s]
"""

from collections import defaultdict
from data import RUNNERS_DATA, N_SEGMENTS
from compat import is_compatible


def count_by_size(relays: list[int]) -> dict[int, int]:
    counts = defaultdict(int)
    for s in relays:
        counts[s] += 1
    return dict(counts)


def compute_upper_bound() -> int:
    from ortools.linear_solver import pywraplp

    total_segs_engaged = sum(sum(c.relais) for c in RUNNERS_DATA.values())
    surplus = total_segs_engaged - N_SEGMENTS

    solver = pywraplp.Solver.CreateSolver("GLOP")

    counts = {r: count_by_size(c.relais) for r, c in RUNNERS_DATA.items()}
    runners = list(RUNNERS_DATA.keys())
    all_sizes = sorted({s for c in RUNNERS_DATA.values() for s in c.relais})

    # Variables b[r1, r2, s] avec r1 < r2 (ordre de la liste runners)
    b = {}
    for s in all_sizes:
        for i, r1 in enumerate(runners):
            if counts[r1].get(s, 0) == 0:
                continue
            for r2 in runners[i + 1:]:
                if counts[r2].get(s, 0) == 0:
                    continue
                if not is_compatible(r1, r2):
                    continue
                ub = min(counts[r1][s], counts[r2][s])
                b[(r1, r2, s)] = solver.NumVar(0.0, ub, f"b_{r1}_{r2}_{s}")

    # Contrainte (1) : capacité par coureur et taille
    for r in runners:
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

    obj = solver.Objective()
    for var in b.values():
        obj.SetCoefficient(var, 1.0)
    obj.SetMaximization()

    status = solver.Solve()
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        print("LP infaisable ou non borné")
        return 0

    bound = solver.Objective().Value()

    # Solos par coureur : relais non appariés dans la solution LP
    # binomes_r[r][s] = Σ b[r,r2,s] (relais de r engagés en binôme pour la taille s)
    binomes_r: dict[str, dict[int, float]] = {r: defaultdict(float) for r in runners}
    for (r1, r2, s), var in b.items():
        v = var.solution_value()
        binomes_r[r1][s] += v
        binomes_r[r2][s] += v

    solo_km = {r: sum((counts[r].get(s, 0) - binomes_r[r][s]) * s * 5 for s in all_sizes)
               for r in runners}
    solo_nb = {r: sum(max(0.0, counts[r].get(s, 0) - binomes_r[r][s]) for s in all_sizes)
               for r in runners}
    total_solo_nb = sum(solo_nb.values())
    total_solo_km = sum(solo_km.values())

    print(f"  Total segments engagés : {total_segs_engaged}  ({total_segs_engaged * 5} km)")
    print(f"  Segments à couvrir     : {N_SEGMENTS}  ({N_SEGMENTS * 5} km)")
    print(f"  Surplus                : {surplus} segments")
    print(f"\n  Majorant (relaxation LP) : {bound:.4f} → {int(bound)} binômes")
    print(f"  Solos (borne basse LP)   : {total_solo_nb:.2f} relais  ({total_solo_km:.0f} km)")
    return int(bound)


if __name__ == "__main__":
    compute_upper_bound()
