"""
Tests unitaires pour relay/constraints.py (modèle waypoint).
"""

import pytest
from relay.constraints import Constraints, Preset
from relay.parcours import Parcours


COMPAT_2 = {("A", "B"): 2}


def _make_parcours(n_points: int = 11, total_km: float = 10.0) -> Parcours:
    """Parcours synthétique : n_points uniformément espacés sur total_km km."""
    step = total_km / (n_points - 1)
    waypoints = [
        {"km": round(i * step, 6), "lat": 45.0, "lon": 4.0 + i * 0.01, "alt": 200.0}
        for i in range(n_points)
    ]
    waypoints[-1]["km"] = total_km
    return Parcours.from_raw(waypoints)


def _simple_c(n_points: int = 11, total_km: float = 10.0) -> Constraints:
    return Constraints(
        parcours=_make_parcours(n_points, total_km),
        speed_kmh=10.0,
        start_hour=0.0,
        compat_matrix=COMPAT_2,
        solo_max_km=5.0,
        solo_max_default=1,
        nuit_max_default=1,
        repos_jour_heures=1.0,
        repos_nuit_heures=2.0,
        max_same_partenaire=None,
    )


# ------------------------------------------------------------------
# Arc lengths and cumul tables
# ------------------------------------------------------------------

def test_arc_lengths():
    c = _simple_c(n_points=6, total_km=10.0)
    assert c.nb_points == 6
    assert c.nb_arcs == 5
    assert len(c.arc_km) == 5
    for km in c.arc_km:
        assert abs(km - 2.0) < 1e-6

    assert c.cumul_m[0] == 0
    assert c.cumul_m[-1] == 10000

    # speed=10 km/h → 6 min/km; point 1 = 2 km → 12 min
    assert c.cumul_temps[0] == 0
    assert c.cumul_temps[1] == 12


def test_cumul_m_matches_waypoints():
    c = _simple_c()
    for i, km in enumerate(c.waypoints_km):
        assert c.cumul_m[i] == round(km * 1000)


# ------------------------------------------------------------------
# Pause shifts cumul_temps
# ------------------------------------------------------------------

def test_pause_shifts_time():
    # 6 points, 5 arcs de 2 km, speed=10 km/h → 12 min/arc
    # cumul_temps = [0, 12, 24, 36, 48, 60]
    c = _simple_c(n_points=6, total_km=10.0)
    assert c.cumul_temps[3] == 36

    orig_3 = c.cumul_temps[3]
    orig_4 = c.cumul_temps[4]

    c.add_pause(0.5, wp=2)  # 30 min

    assert c.cumul_temps[0] == 0
    assert c.cumul_temps[1] == 12
    assert c.cumul_temps[2] == 24

    # Index interne 3 = point fictif de pause (km du point 2, +30 min)
    assert c.cumul_temps[3] == 24 + 30

    # Anciens points utilisateur 3..5 sont maintenant aux indices internes 4..6
    assert c.cumul_temps[4] == orig_3 + 30
    assert c.cumul_temps[5] == orig_4 + 30
    assert c.cumul_temps[6] == 60 + 30


# ------------------------------------------------------------------
# interval_km factory
# ------------------------------------------------------------------

def test_interval_km():
    c = _simple_c(n_points=6, total_km=10.0)
    assert c.interval_km(0.0, 10.0).lo == 0
    assert c.interval_km(0.0, 10.0).hi == 5
    assert c.interval_km(2.0, 2.0).lo == 1
    # 3.1 km : plus proche est point 2 (4km), pas point 1 (2km)
    assert c.interval_km(3.1, 3.1).lo == 2


def test_interval_km_nearest():
    c = _simple_c(n_points=11, total_km=10.0)
    for i in range(11):
        assert c.interval_km(float(i), float(i)).lo == i
    idx = c.interval_km(0.5, 0.5).lo
    assert idx in (0, 1)


# ------------------------------------------------------------------
# RunnerBuilder
# ------------------------------------------------------------------

def test_relay_builder_target_m():
    c = _simple_c()
    c.new_runner("A", 3).add_relay(Preset(km=5.0, min=1, max=9))
    spec = c.runners_data["A"].relais[0]
    assert spec.target_m == 5000


def test_relay_builder_window():
    c = _simple_c(n_points=11, total_km=10.0)
    # step=1km → point 3 = 3km, point 7 = 7km
    win = c.interval_waypoints(3, 7)
    c.new_runner("A", 3).add_relay(Preset(km=2.0, min=1, max=4), window=win)
    spec = c.runners_data["A"].relais[0]
    assert spec.window == [(3, 7)]


def test_relay_builder_multiple_relays():
    c = _simple_c()
    p = Preset(km=5.0, min=1, max=9)
    c.new_runner("A", 3).add_relay(p).add_relay(p).add_relay(p)
    assert len(c.runners_data["A"].relais) == 3
    for spec in c.runners_data["A"].relais:
        assert spec.target_m == 5000


def test_unknown_runner():
    c = _simple_c()
    with pytest.raises(ValueError):
        c.new_runner("Z", 3)
