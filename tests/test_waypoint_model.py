"""
Tests d'intégration pour relay/model.py (modèle waypoint).

Chaque test utilise un problème minimaliste (peu de points, peu de coureurs)
avec un timeout court, et vérifie des propriétés de la solution obtenue.
"""

import pytest

from relay.constraints import Constraints, Preset
from relay.model import build_model, Model
from relay.parcours import Parcours
from relay.solution import Solution


COMPAT_AB = {("A", "B"): 2}
COMPAT_6 = {
    ("A", "B"): 2, ("A", "C"): 1, ("A", "D"): 1, ("A", "E"): 1, ("A", "F"): 1,
    ("B", "C"): 1, ("B", "D"): 1, ("B", "E"): 1, ("B", "F"): 1,
    ("C", "D"): 2, ("C", "E"): 1, ("C", "F"): 1,
    ("D", "E"): 2, ("D", "F"): 1,
    ("E", "F"): 2,
}


def _make_parcours(nb_arcs: int, total_km: float) -> Parcours:
    n = nb_arcs + 1
    step = total_km / nb_arcs
    waypoints = [
        {"km": round(i * step, 6), "lat": 45.0, "lon": 4.0 + i * 0.01, "alt": 200.0}
        for i in range(n)
    ]
    waypoints[-1]["km"] = total_km
    return Parcours.from_raw(waypoints)


def _tiny_c(nb_arcs: int = 5, total_km: float = 10.0, compat=None) -> Constraints:
    if compat is None:
        compat = COMPAT_AB
    return Constraints(
        parcours=_make_parcours(nb_arcs, total_km),
        speed_kmh=10.0,
        start_hour=8.0,
        compat_matrix=compat,
        solo_max_km=total_km,
        solo_max_default=99,
        nuit_max_default=99,
        repos_jour_heures=0.0,
        repos_nuit_heures=0.0,
        max_same_partenaire=None,
    )


def _solve_first(m: Model, c: Constraints, timeout: float = 5.0) -> Solution | None:
    from relay.solver import Solver
    for sol in Solver(m, c).solve(timeout_sec=timeout, max_count=1, log_progress=False):
        return sol
    return None


# ------------------------------------------------------------------
# Coverage
# ------------------------------------------------------------------

def test_coverage_feasible():
    """2 coureurs, 5 arcs — couverture satisfaisable."""
    c = _tiny_c(nb_arcs=5, total_km=10.0)
    p = Preset(km=5.0, min=1, max=9)
    c.new_runner("A", 3).add_relay(p).add_relay(p)
    c.new_runner("B", 3).add_relay(p).add_relay(p)

    m = build_model(c)
    m.add_optimisation_func(c)
    sol = _solve_first(m, c)
    assert sol is not None, "Devrait être faisable"

    arcs_cover = [0] * c.nb_arcs
    for r in sol.relays:
        for a_idx in range(r["start"], r["end"]):
            arcs_cover[a_idx] += 1
    for a_idx, cnt in enumerate(arcs_cover):
        assert 1 <= cnt <= 2, f"Arc {a_idx} couvert {cnt} fois"


# ------------------------------------------------------------------
# Binôme forcé (SharedLeg)
# ------------------------------------------------------------------

def test_binome_same_start_end():
    """Binôme forcé → même start et même end."""
    c = _tiny_c(nb_arcs=10, total_km=10.0)
    p = Preset(km=5.0, min=1, max=9)
    shared = c.new_shared_relay(target_km=5.0)
    c.new_runner("A", 3).add_relay(shared).add_relay(p)
    c.new_runner("B", 3).add_relay(shared).add_relay(p)

    m = build_model(c)
    m.add_optimisation_func(c)
    sol = _solve_first(m, c)
    assert sol is not None

    relay_a = next(r for r in sol.relays if r["runner"] == "A" and r["k"] == 0)
    relay_b = next(r for r in sol.relays if r["runner"] == "B" and r["k"] == 0)
    assert relay_a["start"] == relay_b["start"]
    assert relay_a["end"] == relay_b["end"]
    assert relay_a["partner"] == "B"
    assert relay_b["partner"] == "A"


# ------------------------------------------------------------------
# Repos
# ------------------------------------------------------------------

def test_rest_constraint():
    """Repos de 30 min entre deux relais d'un même coureur."""
    # 40 arcs, 40 km, speed=10 km/h → 6 min/km
    # A fait 2×5km (30min chacun) avec 30min de repos → 90 min < 240 min total → faisable
    c = _tiny_c(nb_arcs=40, total_km=40.0)
    p5 = Preset(km=5.0, min=1, max=9)
    p20 = Preset(km=20.0, min=10, max=30)

    c.new_runner("A", 3).set_options(repos_jour=0.5).add_relay(p5).add_relay(p5)
    c.new_runner("B", 3).add_relay(p20).add_relay(p20)

    m = build_model(c)
    m.add_optimisation_func(c)
    sol = _solve_first(m, c)
    assert sol is not None

    relays_a = sorted([r for r in sol.relays if r["runner"] == "A"], key=lambda r: r["start"])
    for i in range(len(relays_a) - 1):
        gap = relays_a[i + 1]["time_start_min"] - relays_a[i]["time_end_min"]
        assert gap >= 30, f"Repos insuffisant : {gap} min < 30 min"


# ------------------------------------------------------------------
# Solo max distance
# ------------------------------------------------------------------

def test_solo_max_dist():
    """Solo ne dépasse pas solo_max_km."""
    c = Constraints(
        parcours=_make_parcours(nb_arcs=20, total_km=20.0),
        speed_kmh=10.0,
        start_hour=8.0,
        compat_matrix=COMPAT_AB,
        solo_max_km=6.0,
        solo_max_default=2,
        nuit_max_default=99,
        repos_jour_heures=0.0,
        repos_nuit_heures=0.0,
        max_same_partenaire=None,
    )
    p = Preset(km=5.0, min=1, max=9)
    c.new_runner("A", 3).add_relay(p).add_relay(p)
    c.new_runner("B", 3).add_relay(p).add_relay(p)

    m = build_model(c)
    m.add_optimisation_func(c)
    sol = _solve_first(m, c)
    assert sol is not None

    for r in sol.relays:
        if r["solo"]:
            assert r["km"] <= 6.0 + 0.01, f"Solo trop long : {r['km']:.2f} km > 6 km"


# ------------------------------------------------------------------
# flex variable = |dist - target|
# ------------------------------------------------------------------

def test_distance_ecart():
    """Minimiser l'écart : le solver choisit des longueurs dans [min, max]."""
    # 10 arcs de 1 km chacun ; 2 coureurs, 2 relais chacun
    # Preset tight : cible=5km, min=4km, max=6km → chaque relais dans [4,6]
    c = _tiny_c(nb_arcs=10, total_km=10.0)
    p = Preset(km=5.0, min=4, max=6)
    c.new_runner("A", 3).add_relay(p).add_relay(p)
    c.new_runner("B", 3).add_relay(p).add_relay(p)

    m = build_model(c)
    m.add_optimise_flex()  # minimise sum(|dist - target|)

    sol = _solve_first(m, c)
    assert sol is not None

    for r in sol.relays:
        assert 4.0 - 0.01 <= r["km"] <= 6.0 + 0.01, (
            f"Relais {r['runner']}[{r['k']}] : {r['km']:.2f} km hors [4,6]"
        )
