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


# ------------------------------------------------------------------
# Multiple pauses — index coherence
# ------------------------------------------------------------------

def test_two_pauses_nb_points():
    # 6 points + 2 pauses → 8 points internes
    c = _simple_c(n_points=6, total_km=10.0)
    c.add_pause(0.5, wp=1)
    c.add_pause(1.0, wp=3)
    assert c.nb_points == 8
    assert c.nb_arcs == 7


def test_two_pauses_pause_arcs():
    # pause après user-wp=1 → arc interne 1
    # pause après user-wp=3 → dans le tableau reconstruit c'est arc interne 4 (3 user + 1 fictif déjà inséré)
    c = _simple_c(n_points=6, total_km=10.0)
    c.add_pause(0.5, wp=1)
    c.add_pause(1.0, wp=3)
    assert 1 in c.pause_arcs
    assert 4 in c.pause_arcs
    assert len(c.pause_arcs) == 2


def test_two_pauses_cumul_temps():
    # 6 pts, 2 km/arc, speed=10 → 12 min/arc
    # cumul_temps base = [0, 12, 24, 36, 48, 60]
    # pause 30 min après user-wp 1 (km 2)
    # pause 60 min après user-wp 3 (km 6)
    c = _simple_c(n_points=6, total_km=10.0)
    c.add_pause(0.5, wp=1)   # 30 min
    c.add_pause(1.0, wp=3)   # 60 min
    # indices internes :
    #  0  → user 0, km 0   → t=0
    #  1  → user 1, km 2   → t=12
    #  2  → fictif pause1, km 2 → t=12+30=42
    #  3  → user 2, km 4   → t=24+30=54
    #  4  → user 3, km 6   → t=36+30=66
    #  5  → fictif pause2, km 6 → t=36+30+60=126
    #  6  → user 4, km 8   → t=48+30+60=138
    #  7  → user 5, km 10  → t=60+30+60=150
    assert c.cumul_temps[0] == 0
    assert c.cumul_temps[1] == 12
    assert c.cumul_temps[2] == 42    # fictif pause1
    assert c.cumul_temps[3] == 54    # user 2
    assert c.cumul_temps[4] == 66    # user 3
    assert c.cumul_temps[5] == 126   # fictif pause2
    assert c.cumul_temps[6] == 138   # user 4
    assert c.cumul_temps[7] == 150   # user 5


def test_two_pauses_cumul_m_unchanged():
    # Les km ne changent pas avec les pauses
    c = _simple_c(n_points=6, total_km=10.0)
    c.add_pause(0.5, wp=1)
    c.add_pause(1.0, wp=3)
    # km aux points fictifs = km du point précédent (arc de 0 km)
    assert c.cumul_m[1] == c.cumul_m[2]   # pause1 : km identique
    assert c.cumul_m[4] == c.cumul_m[5]   # pause2 : km identique
    assert c.cumul_m[7] == 10000           # dernier point inchangé


def test_pause_order_independence():
    # Déclarer les pauses dans l'ordre inverse doit produire le même résultat
    c1 = _simple_c(n_points=6, total_km=10.0)
    c1.add_pause(0.5, wp=1)
    c1.add_pause(1.0, wp=3)

    c2 = _simple_c(n_points=6, total_km=10.0)
    c2.add_pause(1.0, wp=3)
    c2.add_pause(0.5, wp=1)

    assert c1.cumul_temps == c2.cumul_temps
    assert c1.cumul_m == c2.cumul_m
    assert c1.pause_arcs == c2.pause_arcs


def test_two_pauses_same_wp():
    # Deux pauses au même waypoint fusionnées en un seul point fictif
    c = _simple_c(n_points=6, total_km=10.0)
    c.add_pause(0.5, wp=2)
    c.add_pause(0.5, wp=2)
    # Un seul point fictif inséré → 7 points internes
    assert c.nb_points == 7
    assert len(c.pause_arcs) == 1
    # Durée totale = 60 min sur le point fictif
    fictif_idx = 3   # user 0,1,2 → indices 0,1,2 ; fictif → 3
    assert c.cumul_temps[fictif_idx] == c.cumul_temps[fictif_idx - 1] + 60


def test_interval_km_after_two_pauses():
    # interval_km doit retourner les bons indices internes après 2 pauses
    c = _simple_c(n_points=6, total_km=10.0)
    c.add_pause(0.5, wp=1)
    c.add_pause(1.0, wp=3)
    # km 4 → user-wp 2 → index interne 3 (après un fictif)
    iv = c.interval_km(4.0, 4.0)
    assert iv.lo == 3
    assert iv.hi == 3
    # km 0 et km 10 → bornes absolues
    iv2 = c.interval_km(0.0, 10.0)
    assert iv2.lo == 0
    assert iv2.hi == 7


def test_interval_time_after_two_pauses():
    # speed=10, start_hour=0
    # après pauses : user-wp 4 (km 8) → cumul_temps[6] = 138 min = 2h18
    c = _simple_c(n_points=6, total_km=10.0)
    c.add_pause(0.5, wp=1)
    c.add_pause(1.0, wp=3)
    # heure 2h18 = 138 min depuis start_hour 0
    iv = c.interval_time(2.3, 0, 2.3, 0)
    assert iv.lo == 6
    assert iv.hi == 6


def test_add_pause_after_interval_raises():
    c = _simple_c(n_points=6, total_km=10.0)
    c.interval_km(0.0, 10.0)
    with pytest.raises(RuntimeError):
        c.add_pause(0.5, wp=2)


def test_three_pauses_nb_points():
    c = _simple_c(n_points=6, total_km=10.0)
    c.add_pause(0.25, wp=0)
    c.add_pause(0.5, wp=2)
    c.add_pause(0.75, wp=4)
    assert c.nb_points == 9
    assert len(c.pause_arcs) == 3


def test_three_pauses_time_accumulation():
    # Vérifie que les décalages s'accumulent correctement
    c = _simple_c(n_points=6, total_km=10.0)
    c.add_pause(1.0, wp=0)   # 60 min
    c.add_pause(1.0, wp=2)   # 60 min
    c.add_pause(1.0, wp=4)   # 60 min
    # user-wp 5 (dernier) = index interne 8
    # temps base = 60 min + 3 × 60 min de pause = 240 min
    assert c.cumul_temps[8] == 60 + 3 * 60
