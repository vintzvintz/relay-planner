"""
Tests pour relay/verifications.py

Vérifie que check() détecte correctement les violations et valide les solutions
correctes. Les solutions sont construites manuellement (pas de solver).
"""

from relay.constraints import Constraints, Preset
from relay.parcours import Parcours
from relay.solution import Solution
from relay.verifications import check


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_parcours(nb_arcs=6, total_km=12.0):
    """Crée un Parcours minimal avec des waypoints régulièrement espacés."""
    n = nb_arcs + 1
    step = total_km / nb_arcs
    waypoints = [
        {"km": round(i * step, 6), "lat": 45.0, "lon": 4.0 + i * 0.01, "alt": 200.0}
        for i in range(n)
    ]
    waypoints[-1]["km"] = total_km
    return Parcours.from_raw(waypoints)


def _make_constraints(
    nb_arcs=6,
    total_km=12.0,
    compat=None,
    repos_jour=0.0,
    repos_nuit=0.0,
    solo_max_default=10,
    nuit_max_default=10,
    max_same_partenaire=None,
):
    if compat is None:
        compat = {("A", "B"): 1, ("A", "C"): 1, ("B", "C"): 1}
    parcours = _make_parcours(nb_arcs, total_km)
    return Constraints(
        parcours=parcours,
        speed_kmh=10.0,
        start_hour=8.0,
        compat_matrix=compat,
        solo_max_km=total_km,
        solo_max_default=solo_max_default,
        nuit_max_default=nuit_max_default,
        repos_jour_heures=repos_jour,
        repos_nuit_heures=repos_nuit,
        max_same_partenaire=max_same_partenaire,
    )


# Presets utilitaires (en km)
P6 = Preset(km=6, min=1, max=12)
P12 = Preset(km=12, min=1, max=12)
P3 = Preset(km=3, min=1, max=6)


def _relay(runner, k, start, end, c, partner=None, solo=None, night=False):
    """Construit un dict relais minimal à partir des indices de points."""
    dist_m = c.cumul_m[end] - c.cumul_m[start]
    t_start = c.cumul_temps[start]
    t_end = c.cumul_temps[end]
    spec = c.runners_data[runner].relais[k]
    if solo is None:
        solo = partner is None
    return {
        "runner": runner,
        "k": k,
        "start": start,
        "end": end,
        "km": dist_m / 1000.0,
        "km_start": c.waypoints_km[start],
        "km_end": c.waypoints_km[end],
        "target_km": spec.target_m / 1000.0,
        "flex_m": abs(dist_m - spec.target_m),
        "time_start_min": t_start,
        "time_end_min": t_end,
        "solo": solo,
        "night": night,
        "partner": partner,
        "pinned": None,
        "rest_h": None,
        "d_plus": None,
        "d_moins": None,
    }


def _check(sol):
    """Appelle check() et retourne (ok, texte)."""
    ok, out = check(sol)
    return ok, out.getvalue()


# ------------------------------------------------------------------
# Coverage
# ------------------------------------------------------------------

def test_coverage_ok():
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("A", 1, 3, 6, c),
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Couverture     : OK" in text


def test_coverage_gap():
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("A", 1, 4, 6, c),  # gap à l'arc 3
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 4, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "ERREUR" in text


def test_coverage_over():
    """Plus de 2 coureurs sur un même arc → erreur."""
    c = _make_constraints(nb_arcs=6, compat={("A", "B"): 1, ("A", "C"): 1, ("B", "C"): 1})
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    c.new_runner("C", 3).add_relay(P6)
    # Trois coureurs couvrent les arcs 0-3 → over
    relays = [
        _relay("A", 0, 0, 3, c, partner="B", solo=False),
        _relay("B", 0, 0, 3, c, partner="A", solo=False),
        _relay("C", 0, 0, 3, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "over=" in text


# ------------------------------------------------------------------
# Pauses
# ------------------------------------------------------------------

def test_pause_not_crossed():
    c = _make_constraints(nb_arcs=6)
    c.add_pause(1.0, wp=3)
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    # arc 3 est la pause; les relais s'arrêtent à 3 et reprennent à 4
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("A", 1, 4, 7, c),
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 4, 7, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Pauses         : OK" in text


def test_pause_crossed():
    c = _make_constraints(nb_arcs=6)
    c.add_pause(1.0, wp=3)
    c.new_runner("A", 3).add_relay(P12)
    c.new_runner("B", 3).add_relay(P12)
    # Relais couvrant l'arc pause (0 → 7 traverse l'arc 3)
    relays = [
        _relay("A", 0, 0, 7, c),
        _relay("B", 0, 0, 7, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "PAUSE FRANCHIE" in text


def test_pause_boundary_ok():
    """Relais s'arrêtant pile au point de pause (end == pause point) → pas de franchissement."""
    c = _make_constraints(nb_arcs=6)
    c.add_pause(1.0, wp=3)  # insère pause arc à l'index 3
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    # end=3 signifie que les arcs couverts sont [0,1,2] — l'arc 3 (pause) n'est pas couvert
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("A", 1, 4, 7, c),
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 4, 7, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Pauses         : OK" in text


# ------------------------------------------------------------------
# Relay sizes
# ------------------------------------------------------------------

def test_relay_size_ok():
    c = _make_constraints(nb_arcs=6, total_km=12.0)
    p = Preset(km=6, min=5, max=7)
    c.new_runner("A", 3).add_relay(p)
    c.new_runner("B", 3).add_relay(p)
    relays = [
        _relay("A", 0, 0, 3, c),  # 6 km
        _relay("B", 0, 3, 6, c),  # 6 km
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Tailles relais : OK" in text


def test_relay_size_too_large():
    c = _make_constraints(nb_arcs=6, total_km=12.0)
    p = Preset(km=6, min=1, max=4)
    c.new_runner("A", 3).add_relay(p)
    c.new_runner("B", 3).add_relay(p)
    relays = [
        _relay("A", 0, 0, 3, c),  # 6 km > max 4 km
        _relay("B", 0, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "TAILLE" in text


def test_relay_size_too_small():
    c = _make_constraints(nb_arcs=6, total_km=12.0)
    p = Preset(km=6, min=8, max=12)
    c.new_runner("A", 3).add_relay(p)
    c.new_runner("B", 3).add_relay(p)
    relays = [
        _relay("A", 0, 0, 3, c),  # 6 km < min 8 km
        _relay("B", 0, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "TAILLE" in text


# ------------------------------------------------------------------
# No-overlap
# ------------------------------------------------------------------

def test_no_overlap_ok():
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("B", 0, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "No-overlap     : OK" in text


def test_no_overlap_violation():
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, partner=None),
        _relay("B", 0, 1, 4, c, partner=None),  # overlap avec A
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "OVERLAP" in text


def test_no_overlap_binome_ok():
    """Les binômes peuvent partager les mêmes arcs."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, partner="B", solo=False),
        _relay("B", 0, 0, 3, c, partner="A", solo=False),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "No-overlap     : OK" in text


# ------------------------------------------------------------------
# Compatibility
# ------------------------------------------------------------------

def test_compat_ok():
    c = _make_constraints(nb_arcs=6, compat={("A", "B"): 1, ("A", "C"): 1, ("B", "C"): 1})
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, partner="B", solo=False),
        _relay("B", 0, 0, 3, c, partner="A", solo=False),
        _relay("A", 1, 3, 6, c),
        _relay("B", 1, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Compatibilité  : OK" in text


def test_compat_violation():
    c = _make_constraints(nb_arcs=6, compat={("A", "B"): 0, ("A", "C"): 1, ("B", "C"): 1})
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, partner="B", solo=False),
        _relay("B", 0, 0, 3, c, partner="A", solo=False),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "INCOMPATIBLE" in text


# ------------------------------------------------------------------
# Rest
# ------------------------------------------------------------------

def test_rest_ok():
    c = _make_constraints(nb_arcs=6, repos_jour=0.0)
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("A", 1, 3, 6, c),
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Repos          : OK" in text


def test_rest_violation():
    # repos_jour = 2h = 120 min; les relais se touchent directement (gap=0)
    c = _make_constraints(nb_arcs=6, repos_jour=2.0)
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("A", 1, 3, 6, c),  # gap = 0 < 120 min
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "REPOS" in text


def test_rest_chained_exempt():
    """Les relais enchaînés (chained_to_next) ne sont pas soumis au repos."""
    c = _make_constraints(nb_arcs=6, repos_jour=2.0)
    c.new_runner("A", 3).add_relay(P3, P3)  # enchaînés
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 2, c),
        _relay("A", 1, 2, 4, c),  # gap = 0 mais chained → pas de violation
        _relay("B", 0, 0, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Repos          : OK" in text


def test_rest_nuit():
    """Le repos après un relais de nuit utilise repos_nuit (pas repos_jour)."""
    c = _make_constraints(nb_arcs=6, repos_jour=0.0, repos_nuit=2.0)
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, night=True),
        _relay("A", 1, 3, 6, c),  # gap = 0 < repos_nuit 120 min
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "REPOS" in text


# ------------------------------------------------------------------
# Unknown runner
# ------------------------------------------------------------------

def test_unknown_runner():
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    rel = _relay("A", 0, 0, 3, c)
    rel["runner"] = "INCONNU"
    sol = Solution([rel], c)
    ok, text = _check(sol)
    assert ok is False
    assert "COUREUR INCONNU" in text


# ------------------------------------------------------------------
# Night max
# ------------------------------------------------------------------

def test_night_max_ok():
    c = _make_constraints(nb_arcs=6, nuit_max_default=1)
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, night=True),   # 1 nuit
        _relay("A", 1, 3, 6, c, night=False),
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Nuit max       : OK" in text


def test_night_max_violation():
    c = _make_constraints(nb_arcs=6, nuit_max_default=1)
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, night=True),
        _relay("A", 1, 3, 6, c, night=True),   # 2 nuits > max 1
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "NUIT" in text


def test_night_max_per_runner_override():
    """set_options(nuit_max=) sur un coureur override la valeur par défaut."""
    c = _make_constraints(nb_arcs=6, nuit_max_default=1)
    c.new_runner("A", 3).set_options(nuit_max=2).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, night=True),
        _relay("A", 1, 3, 6, c, night=True),   # 2 nuits, max per-runner=2 → OK
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Nuit max       : OK" in text


# ------------------------------------------------------------------
# Solo max
# ------------------------------------------------------------------

def test_solo_max_ok():
    c = _make_constraints(nb_arcs=6, solo_max_default=2)
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, solo=True),
        _relay("A", 1, 3, 6, c, solo=True),  # 2 solos <= max 2
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Solo max       : OK" in text


def test_solo_max_violation():
    c = _make_constraints(nb_arcs=6, solo_max_default=1)
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, solo=True),
        _relay("A", 1, 3, 6, c, solo=True),  # 2 solos > max 1
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "SOLO" in text


def test_solo_max_per_runner_override():
    """set_options(solo_max=) sur un coureur override la valeur par défaut."""
    # default=1, mais A a override à 2 → A peut faire 2 solos
    # B ne fait que des binômes → pas de problème pour B
    c = _make_constraints(nb_arcs=8, total_km=16.0, solo_max_default=1)
    P4 = Preset(km=4, min=1, max=16)
    c.new_runner("A", 3).set_options(solo_max=2).add_relay(P4).add_relay(P4)
    c.new_runner("B", 3).add_relay(P4).add_relay(P4)
    relays = [
        _relay("A", 0, 0, 2, c, solo=True),
        _relay("B", 0, 2, 4, c, partner="A", solo=False),
        _relay("A", 1, 4, 6, c, solo=True),   # 2 solos pour A, OK car override=2
        _relay("B", 1, 6, 8, c, partner="A", solo=False),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Solo max       : OK" in text


# ------------------------------------------------------------------
# Solo intervals (zones interdites au solo)
# ------------------------------------------------------------------

def test_solo_intervals_ok():
    """Solo en dehors d'une zone interdite → OK."""
    c = _make_constraints(nb_arcs=6)
    # Zone interdite : arcs 3-6 (points 3 à 6)
    c.add_no_solo(c.interval_waypoints(3, 6))
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, solo=True),   # hors zone
        _relay("A", 1, 3, 6, c, partner="B", solo=False),
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 3, 6, c, partner="A", solo=False),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Intervalles solo" in text
    assert "OK" in text


def test_solo_intervals_violation():
    """Solo entièrement dans une zone interdite → erreur."""
    c = _make_constraints(nb_arcs=6)
    # Zone interdite : arcs 0-3 (points 0 à 3)
    c.add_no_solo(c.interval_waypoints(0, 3))
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, solo=True),   # dans la zone interdite
        _relay("A", 1, 3, 6, c),
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "zone solo" in text.lower() or "Relais en zone solo" in text


def test_solo_intervals_partial_overlap():
    """Solo qui déborde partiellement dans une zone interdite → erreur."""
    c = _make_constraints(nb_arcs=6)
    # Zone interdite : points 2-4
    c.add_no_solo(c.interval_waypoints(2, 4))
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, solo=True),   # [0,3[ chevauche [2,4]
        _relay("A", 1, 3, 6, c),
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "zone solo" in text.lower() or "Relais en zone solo" in text


# ------------------------------------------------------------------
# Solo forced (per-relay solo constraint)
# ------------------------------------------------------------------

def test_solo_forced_ok():
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6, solo=True)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, solo=True),
        _relay("B", 0, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Solo forcé     : OK" in text


def test_solo_forced_violation_should_be_solo():
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6, solo=True)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, partner="B", solo=False),  # devrait être solo
        _relay("B", 0, 0, 3, c, partner="A", solo=False),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "devrait être solo" in text


def test_solo_forced_violation_should_be_binome():
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6, solo=False)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, solo=True),  # devrait être en binôme
        _relay("B", 0, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "devrait être en binôme" in text


# ------------------------------------------------------------------
# Max duos
# ------------------------------------------------------------------

def test_max_duos_ok():
    c = _make_constraints(nb_arcs=6)
    ra = c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    rb = c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    c.add_max_duos(ra, rb, 1)
    relays = [
        _relay("A", 0, 0, 3, c, partner="B", solo=False),  # 1 binôme
        _relay("B", 0, 0, 3, c, partner="A", solo=False),
        _relay("A", 1, 3, 6, c, solo=True),
        _relay("B", 1, 3, 6, c, solo=True),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Max duos       : OK" in text


def test_max_duos_violation():
    c = _make_constraints(nb_arcs=6)
    ra = c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    rb = c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    c.add_max_duos(ra, rb, 1)
    relays = [
        _relay("A", 0, 0, 3, c, partner="B", solo=False),
        _relay("B", 0, 0, 3, c, partner="A", solo=False),
        _relay("A", 1, 3, 6, c, partner="B", solo=False),  # 2e binôme > max 1
        _relay("B", 1, 3, 6, c, partner="A", solo=False),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "MAX DUOS" in text


# ------------------------------------------------------------------
# Chained relays
# ------------------------------------------------------------------

def test_chained_ok():
    c = _make_constraints(nb_arcs=6)
    # Deux presets enchaînés : end[0] == start[1]
    c.new_runner("A", 3).add_relay(P3, P3)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 2, c),
        _relay("A", 1, 2, 4, c),   # end[0]=2 == start[1]=2
        _relay("B", 0, 0, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Enchaînements  : OK" in text


def test_chained_violation():
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P3, P3)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 2, c),
        _relay("A", 1, 3, 5, c),   # end[0]=2 != start[1]=3
        _relay("B", 0, 0, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "CHAINED" in text


# ------------------------------------------------------------------
# Pairings (SharedLeg)
# ------------------------------------------------------------------

def test_pairings_ok():
    c = _make_constraints(nb_arcs=6)
    shared = c.new_shared_relay(P6)
    c.new_runner("A", 3).add_relay(shared)
    c.new_runner("B", 3).add_relay(shared)
    relays = [
        _relay("A", 0, 0, 3, c, partner="B", solo=False),
        _relay("B", 0, 0, 3, c, partner="A", solo=False),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Pairings       : OK" in text


def test_pairings_violation():
    c = _make_constraints(nb_arcs=6)
    shared = c.new_shared_relay(P6)
    c.new_runner("A", 3).add_relay(shared)
    c.new_runner("B", 3).add_relay(shared)
    relays = [
        _relay("A", 0, 0, 3, c, partner="C", solo=False),  # devrait être B
        _relay("B", 0, 0, 3, c, partner="A", solo=False),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "PAIRING" in text


# ------------------------------------------------------------------
# Max same partenaire
# ------------------------------------------------------------------

def test_max_same_partenaire_ok():
    c = _make_constraints(nb_arcs=6, max_same_partenaire=2)
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, partner="B", solo=False),
        _relay("B", 0, 0, 3, c, partner="A", solo=False),
        _relay("A", 1, 3, 6, c, solo=True),
        _relay("B", 1, 3, 6, c, solo=True),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Max partenaire : OK" in text


def test_max_same_partenaire_violation():
    c = _make_constraints(nb_arcs=6, max_same_partenaire=1)
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, partner="B", solo=False),
        _relay("B", 0, 0, 3, c, partner="A", solo=False),
        _relay("A", 1, 3, 6, c, partner="B", solo=False),  # 2e binôme avec B > max 1
        _relay("B", 1, 3, 6, c, partner="A", solo=False),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "MAX SAME PARTENAIRE" in text


def test_max_same_partenaire_per_runner_override():
    """set_options(max_same_partenaire=) override la valeur par défaut."""
    c = _make_constraints(nb_arcs=6, max_same_partenaire=1)
    # A a un override à 2, B garde le défaut à 1
    c.new_runner("A", 3).set_options(max_same_partenaire=2).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, partner="B", solo=False),
        _relay("B", 0, 0, 3, c, partner="A", solo=False),
        _relay("A", 1, 3, 6, c, partner="B", solo=False),
        _relay("B", 1, 3, 6, c, partner="A", solo=False),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    # B voit 2 binômes avec A > max 1 (défaut) → violation
    assert ok is False
    assert "MAX SAME PARTENAIRE" in text


# ------------------------------------------------------------------
# Availability (window)
# ------------------------------------------------------------------

def test_availability_ok():
    c = _make_constraints(nb_arcs=6)
    window = c.interval_waypoints(0, 4)
    c.new_runner("A", 3).add_relay(P6, window=window)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),   # dans [0, 4]
        _relay("B", 0, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Disponibilité  : OK" in text


def test_availability_violation():
    c = _make_constraints(nb_arcs=6)
    window = c.interval_waypoints(0, 3)
    c.new_runner("A", 3).add_relay(P6, window=window)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 4, c),   # end=4 > hi=3 → hors fenêtre
        _relay("B", 0, 4, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "DISPONIBILITÉ" in text


def test_availability_multi_window():
    """Avec plusieurs fenêtres, le relais doit être dans au moins une."""
    c = _make_constraints(nb_arcs=6)
    w1 = c.interval_waypoints(0, 2)
    w2 = c.interval_waypoints(4, 6)
    c.new_runner("A", 3).add_relay(P6, window=[w1, w2])
    c.new_runner("B", 3).add_relay(P6)
    # Relais dans la 2e fenêtre → OK
    relays = [
        _relay("A", 0, 4, 6, c),
        _relay("B", 0, 0, 4, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Disponibilité  : OK" in text


def test_availability_multi_window_violation():
    """Relais hors de toutes les fenêtres → violation."""
    c = _make_constraints(nb_arcs=6)
    w1 = c.interval_waypoints(0, 2)
    w2 = c.interval_waypoints(5, 6)
    c.new_runner("A", 3).add_relay(P6, window=[w1, w2])
    c.new_runner("B", 3).add_relay(P6)
    # Relais [2,4] n'est dans aucune fenêtre
    relays = [
        _relay("A", 0, 2, 4, c),
        _relay("B", 0, 0, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "DISPONIBILITÉ" in text


# ------------------------------------------------------------------
# Pinned (fixed relays)
# ------------------------------------------------------------------

def test_pinned_ok():
    c = _make_constraints(nb_arcs=6)
    pin = c.new_pin(start_wp=0, end_wp=3)
    c.new_runner("A", 3).add_relay(P6, pinned=pin)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),   # start=0, end=3 → matches pin
        _relay("B", 0, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Épinglages     : OK" in text


def test_pinned_start_violation():
    c = _make_constraints(nb_arcs=6)
    pin = c.new_pin(start_wp=0)
    c.new_runner("A", 3).add_relay(P6, pinned=pin)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 1, 4, c),   # start=1 != pinned_start=0
        _relay("B", 0, 4, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "PINNED" in text


def test_pinned_end_violation():
    c = _make_constraints(nb_arcs=6)
    pin = c.new_pin(end_wp=3)
    c.new_runner("A", 3).add_relay(P6, pinned=pin)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 4, c),   # end=4 != pinned_end=3
        _relay("B", 0, 4, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "PINNED" in text


# ------------------------------------------------------------------
# D+ max
# ------------------------------------------------------------------

def test_dplus_max_ok():
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6, dplus_max=500)
    c.new_runner("B", 3).add_relay(P6)
    rel = _relay("A", 0, 0, 3, c)
    rel["d_plus"] = 200.0
    rel["d_moins"] = 100.0  # total 300 < 500
    relays = [rel, _relay("B", 0, 3, 6, c)]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "D+ max         : OK" in text


def test_dplus_max_violation():
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6, dplus_max=200)
    c.new_runner("B", 3).add_relay(P6)
    rel = _relay("A", 0, 0, 3, c)
    rel["d_plus"] = 150.0
    rel["d_moins"] = 100.0  # total 250 > 200
    relays = [rel, _relay("B", 0, 3, 6, c)]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "DPLUS_MAX" in text


def test_dplus_max_none_ignored():
    """Relais sans d_plus/d_moins données → dplus_max ignoré."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6, dplus_max=100)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),  # d_plus=None → skip
        _relay("B", 0, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "D+ max         : OK" in text


# ===================================================================
# Cas limites / sémantique fine
# ===================================================================
# Ces tests vérifient que la vérification a exactement la même
# sémantique que le modèle CP-SAT (model.py), notamment aux bornes.


# ------------------------------------------------------------------
# Solo intervals : sémantique d'overlap point-based
# ------------------------------------------------------------------

def test_solo_intervals_start_at_zone_end():
    """Relais solo démarrant au dernier point de la zone interdite.

    Zone [2,4] = waypoints {2,3,4}. Relais [4,6[ = waypoints {4,5,6}.
    Les waypoints 4 sont partagés → le modèle CP-SAT considère un overlap
    (start <= hi AND end > lo) : 4 <= 4 AND 6 > 2 → True.
    La vérification doit aussi le détecter.
    """
    c = _make_constraints(nb_arcs=6)
    c.add_no_solo(c.interval_waypoints(2, 4))
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, partner="B", solo=False),
        _relay("A", 1, 4, 6, c, solo=True),   # start=4 == hi=4, end=6 > lo=2
        _relay("B", 0, 0, 3, c, partner="A", solo=False),
        _relay("B", 1, 4, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "zone solo" in text.lower() or "Relais en zone solo" in text


def test_solo_intervals_start_after_zone_end():
    """Relais solo démarrant juste après le dernier point de la zone → OK.

    Zone [2,4]. Relais [5,6[. start=5 > hi=4 → pas d'overlap.
    """
    c = _make_constraints(nb_arcs=6)
    c.add_no_solo(c.interval_waypoints(2, 4))
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, partner="B", solo=False),
        _relay("A", 1, 5, 6, c, solo=True),   # start=5 > hi=4 → hors zone
        _relay("B", 0, 0, 3, c, partner="A", solo=False),
        _relay("B", 1, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "OK" in text


def test_solo_intervals_end_at_zone_start():
    """Relais solo finissant au premier point de la zone → pas d'overlap.

    Zone [3,5]. Relais [0,3[. end=3, lo=3 → end > lo est faux (3 > 3 = False).
    """
    c = _make_constraints(nb_arcs=6)
    c.add_no_solo(c.interval_waypoints(3, 5))
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, solo=True),   # end=3 == lo=3 → end > lo faux → pas d'overlap
        _relay("A", 1, 3, 6, c, partner="B", solo=False),
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 3, 6, c, partner="A", solo=False),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "OK" in text


def test_solo_intervals_end_just_inside_zone():
    """Relais solo finissant un point après le début de zone → overlap.

    Zone [3,5]. Relais [0,4[. end=4 > lo=3 AND start=0 <= hi=5 → overlap.
    """
    c = _make_constraints(nb_arcs=6)
    c.add_no_solo(c.interval_waypoints(3, 5))
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 4, c, solo=True),   # end=4 > lo=3 → overlap
        _relay("A", 1, 4, 6, c),
        _relay("B", 0, 0, 4, c),
        _relay("B", 1, 4, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "zone solo" in text.lower() or "Relais en zone solo" in text


# ------------------------------------------------------------------
# No-overlap : adjacence exacte (end_A == start_B → pas d'overlap)
# ------------------------------------------------------------------

def test_no_overlap_adjacent():
    """Deux relais adjacents (end_A == start_B) ne se chevauchent pas.

    Modèle : disjoint ssi end_A <= start_B. Avec end=3, start=3 → 3 <= 3 → OK.
    """
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("B", 0, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "No-overlap     : OK" in text


def test_no_overlap_one_arc_overlap():
    """Deux relais partageant un seul arc (end_A = start_B + 1) → overlap.

    A=[0,4[, B=[3,6[. Shared arc: 3. Modèle : 4 > 3 AND 6 > 0 → overlap.
    """
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 4, c),
        _relay("B", 0, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "OVERLAP" in text


# ------------------------------------------------------------------
# Tailles relais : bornes exactes
# ------------------------------------------------------------------

def test_relay_size_exact_min():
    """Distance exactement égale à min_m → OK."""
    c = _make_constraints(nb_arcs=6, total_km=12.0)
    p = Preset(km=6, min=6, max=12)
    c.new_runner("A", 3).add_relay(p)
    c.new_runner("B", 3).add_relay(p)
    relays = [
        _relay("A", 0, 0, 3, c),  # 6 km == min 6 km
        _relay("B", 0, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Tailles relais : OK" in text


def test_relay_size_exact_max():
    """Distance exactement égale à max_m → OK."""
    c = _make_constraints(nb_arcs=6, total_km=12.0)
    p = Preset(km=6, min=1, max=6)
    c.new_runner("A", 3).add_relay(p)
    c.new_runner("B", 3).add_relay(p)
    relays = [
        _relay("A", 0, 0, 3, c),  # 6 km == max 6 km
        _relay("B", 0, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Tailles relais : OK" in text


# ------------------------------------------------------------------
# Repos : borne exacte au seuil
# ------------------------------------------------------------------

def test_rest_exact_threshold():
    """Gap de repos exactement égal au minimum requis → OK.

    Parcours 10 arcs, 20 km, speed=10 km/h. Chaque arc = 2 km = 12 min.
    A fait [0,2] puis [4,6]. gap = cumul_temps[4] - cumul_temps[2] = 24 min.
    repos_jour = 24 min (0.4h). Exactement au seuil → OK.
    B fait [0,5] puis [7,10] avec le même gap de 24 min.
    """
    c = _make_constraints(nb_arcs=10, total_km=20.0, repos_jour=0.4)
    P_wide = Preset(km=4, min=1, max=20)
    c.new_runner("A", 3).add_relay(P_wide).add_relay(P_wide)
    c.new_runner("B", 3).add_relay(P_wide).add_relay(P_wide)
    relays = [
        _relay("A", 0, 0, 2, c),
        _relay("A", 1, 4, 6, c),   # gap = cumul_temps[4] - cumul_temps[2] = 24 min
        _relay("B", 0, 2, 4, c),
        _relay("B", 1, 6, 10, c),  # gap = cumul_temps[6] - cumul_temps[4] = 24 min
    ]
    gap_a = c.cumul_temps[4] - c.cumul_temps[2]
    gap_b = c.cumul_temps[6] - c.cumul_temps[4]
    repos_min = round(0.4 * 60)  # 24 min
    assert gap_a == repos_min, f"gap_a={gap_a} != repos_min={repos_min}"
    assert gap_b == repos_min, f"gap_b={gap_b} != repos_min={repos_min}"
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Repos          : OK" in text


# ------------------------------------------------------------------
# Coverage : arc couvert exactement 2 fois (max autorisé)
# ------------------------------------------------------------------

def test_coverage_exactly_two():
    """Deux coureurs couvrant le même arc (binôme) → OK (capacité max = 2)."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P12)
    c.new_runner("B", 3).add_relay(P12)
    relays = [
        _relay("A", 0, 0, 6, c, partner="B", solo=False),
        _relay("B", 0, 0, 6, c, partner="A", solo=False),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Couverture     : OK" in text


# ------------------------------------------------------------------
# Availability : bornes exactes (start == lo, end == hi → OK)
# ------------------------------------------------------------------

def test_availability_exact_bounds():
    """Relais calé exactement sur les bornes de la fenêtre → OK.

    Modèle : start >= lo AND end <= hi. Avec start=1, end=4, window=[1,4] → OK.
    """
    c = _make_constraints(nb_arcs=6)
    window = c.interval_waypoints(1, 4)
    c.new_runner("A", 3).add_relay(P6, window=window)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 1, 4, c),   # start=1==lo, end=4==hi → OK
        _relay("B", 0, 0, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Disponibilité  : OK" in text


def test_availability_start_before_window():
    """start < lo → violation (même si end est dans la fenêtre)."""
    c = _make_constraints(nb_arcs=6)
    window = c.interval_waypoints(2, 6)
    c.new_runner("A", 3).add_relay(P6, window=window)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 1, 4, c),   # start=1 < lo=2
        _relay("B", 0, 0, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "DISPONIBILITÉ" in text


# ------------------------------------------------------------------
# Pause : relais commençant juste après la pause
# ------------------------------------------------------------------

def test_pause_start_at_pause_plus_one():
    """Relais commençant au point pause+1 (juste après) → OK.

    Modèle : b_after → start >= ap+1. Avec start = ap+1 → OK.
    """
    c = _make_constraints(nb_arcs=6)
    c.add_pause(1.0, wp=2)  # pause arc at index 2
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 2, c),
        _relay("A", 1, 3, 7, c),   # start = 3 = pause_arc+1
        _relay("B", 0, 0, 2, c),
        _relay("B", 1, 3, 7, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Pauses         : OK" in text


# ------------------------------------------------------------------
# Pause : relais dont le end touche le point de pause
# ------------------------------------------------------------------

def test_pause_end_at_pause_point():
    """Relais finissant exactement au point de pause (end == ap) → OK.

    Modèle : !b_after → end <= ap. Avec end = ap → les arcs couverts
    sont [start, ..., ap-1] et n'incluent pas l'arc de pause ap.
    """
    c = _make_constraints(nb_arcs=6)
    c.add_pause(1.0, wp=3)  # pause arc at index 3
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),   # end = 3 = ap → arcs [0,1,2], arc 3 non couvert
        _relay("A", 1, 4, 7, c),
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 4, 7, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Pauses         : OK" in text


# ------------------------------------------------------------------
# D+ max : tolérance de 0.5 exactement au seuil
# ------------------------------------------------------------------

def test_dplus_max_at_tolerance():
    """D+ + D- dépasse dplus_max de 0.5 exactement → OK (tolérance)."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6, dplus_max=200)
    c.new_runner("B", 3).add_relay(P6)
    rel = _relay("A", 0, 0, 3, c)
    rel["d_plus"] = 120.0
    rel["d_moins"] = 80.5  # total 200.5, dplus_max=200 → 200.5 <= 200.5 → OK
    relays = [rel, _relay("B", 0, 3, 6, c)]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "D+ max         : OK" in text


def test_dplus_max_just_over_tolerance():
    """D+ + D- dépasse dplus_max de 0.6 → violation (> 0.5 de tolérance)."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6, dplus_max=200)
    c.new_runner("B", 3).add_relay(P6)
    rel = _relay("A", 0, 0, 3, c)
    rel["d_plus"] = 120.0
    rel["d_moins"] = 80.6  # total 200.6 > 200 + 0.5 → violation
    relays = [rel, _relay("B", 0, 3, 6, c)]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "DPLUS_MAX" in text


# ------------------------------------------------------------------
# Max duos : exactement au seuil
# ------------------------------------------------------------------

def test_max_duos_at_limit():
    """Nombre de binômes exactement au max → OK."""
    c = _make_constraints(nb_arcs=6)
    ra = c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    rb = c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    c.add_max_duos(ra, rb, 2)
    relays = [
        _relay("A", 0, 0, 3, c, partner="B", solo=False),
        _relay("B", 0, 0, 3, c, partner="A", solo=False),
        _relay("A", 1, 3, 6, c, partner="B", solo=False),
        _relay("B", 1, 3, 6, c, partner="A", solo=False),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Max duos       : OK" in text


# ------------------------------------------------------------------
# Night max : exactement au seuil
# ------------------------------------------------------------------

def test_night_max_at_limit():
    """Nombre de relais de nuit exactement au max → OK."""
    c = _make_constraints(nb_arcs=6, nuit_max_default=2)
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, night=True),
        _relay("A", 1, 3, 6, c, night=True),  # 2 nuits == max 2 → OK
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Nuit max       : OK" in text


# ------------------------------------------------------------------
# Solo max : exactement au seuil
# ------------------------------------------------------------------

def test_solo_max_at_limit():
    """Nombre de solos exactement au max → OK."""
    c = _make_constraints(nb_arcs=6, solo_max_default=2)
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, solo=True),
        _relay("A", 1, 3, 6, c, solo=True),  # 2 solos == max 2 → OK
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Solo max       : OK" in text


# ------------------------------------------------------------------
# Overlap incompatibles : vérification sans partner (compat score = 0)
# ------------------------------------------------------------------

def test_no_overlap_incompatible_pair():
    """Deux coureurs incompatibles (score=0) qui se chevauchent → overlap.

    Le modèle impose un no-overlap global pour les paires incompatibles.
    La vérification doit aussi le détecter (pas de partner croisé).
    """
    c = _make_constraints(
        nb_arcs=6,
        compat={("A", "B"): 0, ("A", "C"): 1, ("B", "C"): 1},
    )
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 4, c),
        _relay("B", 0, 2, 6, c),  # overlap [2,4[ avec A, incompatibles
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "OVERLAP" in text


# ------------------------------------------------------------------
# Champs dérivés (cohérence interne du dict relais)
# ------------------------------------------------------------------


def test_derived_fields_ok():
    """Dict relais propre : tous les champs calculés cohérents."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("B", 0, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Champs dérivés : OK" in text


def test_derived_km_start_wrong():
    """km_start corrompu → détecté."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("B", 0, 3, 6, c),
    ]
    relays[0]["km_start"] = 999.0  # Valeur invalide
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "CHAMP" in text and "km_start" in text


def test_derived_km_end_wrong():
    """km_end corrompu → détecté."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("B", 0, 3, 6, c),
    ]
    relays[0]["km_end"] = 999.0  # Valeur invalide
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "CHAMP" in text and "km_end" in text


def test_derived_km_wrong():
    """km corrompu → détecté."""
    c = _make_constraints(nb_arcs=6, total_km=12.0)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),  # 6 km
        _relay("B", 0, 3, 6, c),  # 6 km
    ]
    relays[0]["km"] = 999.0  # Valeur invalide
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "CHAMP" in text and "km=" in text


def test_derived_time_start_wrong():
    """time_start_min corrompu → détecté."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("B", 0, 3, 6, c),
    ]
    relays[0]["time_start_min"] = 9999  # Valeur invalide
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "CHAMP" in text and "time_start_min" in text


def test_derived_time_end_wrong():
    """time_end_min corrompu → détecté."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("B", 0, 3, 6, c),
    ]
    relays[0]["time_end_min"] = 9999  # Valeur invalide
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "CHAMP" in text and "time_end_min" in text


def test_derived_wp_start_wrong():
    """wp_start corrompu → détecté."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("B", 0, 3, 6, c),
    ]
    relays[0]["wp_start"] = 999  # Valeur invalide
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "CHAMP" in text and "wp_start" in text


def test_derived_wp_end_wrong():
    """wp_end corrompu → détecté."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("B", 0, 3, 6, c),
    ]
    relays[0]["wp_end"] = 999  # Valeur invalide
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "CHAMP" in text and "wp_end" in text


def test_derived_lat_start_wrong():
    """lat_start corrompu → détecté (si présent dans waypoint)."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("B", 0, 3, 6, c),
    ]
    relays[0]["lat_start"] = 999.0  # Valeur invalide
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "CHAMP" in text and "lat_start" in text


def test_derived_lon_end_wrong():
    """lon_end corrompu → détecté (si présent dans waypoint)."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("B", 0, 3, 6, c),
    ]
    relays[1]["lon_end"] = 999.0  # Valeur invalide
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "CHAMP" in text and "lon_end" in text


def test_derived_wp_absent_ignored():
    """wp_start/wp_end absents du dict → pas de check (champs optionnels)."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("B", 0, 3, 6, c),
    ]
    # Supprimer wp_start/wp_end (helper _relay ne les ajoute pas par défaut)
    for rel in relays:
        rel.pop("wp_start", None)
        rel.pop("wp_end", None)
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Champs dérivés : OK" in text


def test_derived_lat_absent_ignored():
    """lat_* absent du dict → pas de check (champs optionnels)."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("B", 0, 3, 6, c),
    ]
    # Supprimer les champs lat/lon/alt
    for rel in relays:
        rel.pop("lat_start", None)
        rel.pop("lon_start", None)
        rel.pop("alt_start", None)
        rel.pop("lat_end", None)
        rel.pop("lon_end", None)
        rel.pop("alt_end", None)
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Champs dérivés : OK" in text


def test_derived_wp_with_pause_ok():
    """wp_start/wp_end cohérents avec mapping internal_to_user (pause insérée)."""
    c = _make_constraints(nb_arcs=6)
    c.add_pause(1.0, wp=3)  # Pause insérée → décale les indices utilisateur
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("A", 1, 4, 7, c),
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 4, 7, c),
    ]
    # Ajouter wp_start/wp_end correctement (helper ne les ajoute pas)
    # La pause au point 3 signifie internal_to_user[3] = 2 (le point user juste avant)
    # et internal_to_user[4] = 3 (le point réel suivant)
    for rel in relays:
        s, e = rel["start"], rel["end"]
        # Reconstruire le mapping pour ce test
        pause_pts = {arc + 1 for arc in c.pause_arcs}
        uid = 0
        map_itu = {}
        for i in range(c.nb_points):
            if i in pause_pts:
                map_itu[i] = uid - 1
            else:
                map_itu[i] = uid
                uid += 1
        rel["wp_start"] = map_itu[s]
        rel["wp_end"] = map_itu[e]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Champs dérivés : OK" in text


def test_derived_wp_with_pause_wrong():
    """wp_end incorrect avec pause insérée → détecté."""
    c = _make_constraints(nb_arcs=6)
    c.add_pause(1.0, wp=3)
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("A", 1, 4, 7, c),
        _relay("B", 0, 0, 3, c),
        _relay("B", 1, 4, 7, c),
    ]
    # Construire le mapping correct
    pause_pts = {arc + 1 for arc in c.pause_arcs}
    uid = 0
    map_itu = {}
    for i in range(c.nb_points):
        if i in pause_pts:
            map_itu[i] = uid - 1
        else:
            map_itu[i] = uid
            uid += 1
    for rel in relays:
        s, e = rel["start"], rel["end"]
        rel["wp_start"] = map_itu[s]
        rel["wp_end"] = map_itu[e]
    # Corrompre un champ
    relays[1]["wp_end"] = 999  # Valeur invalide
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "CHAMP" in text and "wp_end" in text


# ==================================================================
# Cohérence croisée entre attributs
# ==================================================================


# ------------------------------------------------------------------
# Night vs time
# ------------------------------------------------------------------

def test_night_vs_time_ok():
    """night=true pour un relais chevauchant un intervalle nocturne → OK."""
    c = _make_constraints(nb_arcs=6)
    c.add_night(c.interval_waypoints(0, 2))  # [0,2] : chevauche [0,3[ mais pas [3,6[
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, night=True),   # start=0 <= 2 AND end=3 > 0 → nuit
        _relay("A", 1, 3, 6, c, night=False),   # start=3 > 2 → pas nuit
        _relay("B", 0, 0, 3, c, night=True),
        _relay("B", 1, 3, 6, c, night=False),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Nuit vs heure  : OK" in text


def test_night_vs_time_false_but_in_night():
    """night=false pour un relais chevauchant un intervalle nocturne → erreur."""
    c = _make_constraints(nb_arcs=6)
    c.add_night(c.interval_waypoints(0, 2))
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, night=False),  # chevauche [0,2] mais night=false
        _relay("A", 1, 3, 6, c, night=False),
        _relay("B", 0, 0, 3, c, night=True),
        _relay("B", 1, 3, 6, c, night=False),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "NUIT/HEURE" in text
    assert "night=false" in text


def test_night_vs_time_true_but_not_in_night():
    """night=true pour un relais hors de tout intervalle nocturne → erreur."""
    c = _make_constraints(nb_arcs=6)
    c.add_night(c.interval_waypoints(0, 2))
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, night=True),
        _relay("A", 1, 3, 6, c, night=True),  # [3,6[ ne chevauche pas [0,2]
        _relay("B", 0, 0, 3, c, night=True),
        _relay("B", 1, 3, 6, c, night=False),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "NUIT/HEURE" in text
    assert "night=true" in text


def test_night_vs_time_no_intervals():
    """Pas d'intervalle nocturne déclaré → OK sans contrôle."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, night=True),
        _relay("B", 0, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Nuit vs heure  : OK" in text


# ------------------------------------------------------------------
# Solo vs partner
# ------------------------------------------------------------------

def test_solo_vs_partner_ok():
    """solo=true avec partner=None, solo=false avec partner renseigné → OK."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, partner="B", solo=False),
        _relay("B", 0, 0, 3, c, partner="A", solo=False),
        _relay("A", 1, 3, 6, c, partner=None, solo=True),
        _relay("B", 1, 3, 6, c, partner=None, solo=True),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Solo/partner   : OK" in text


def test_solo_true_with_partner():
    """solo=true mais partner renseigné → erreur."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, partner="B", solo=True),  # incohérent
        _relay("B", 0, 0, 3, c, partner="A", solo=False),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "SOLO/PARTNER" in text
    assert "solo=true mais partner=" in text


def test_solo_false_without_partner():
    """solo=false mais partner=None → erreur."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, partner=None, solo=False),  # incohérent
        _relay("B", 0, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "SOLO/PARTNER" in text
    assert "solo=false mais partner=None" in text


# ------------------------------------------------------------------
# Partner reciprocity
# ------------------------------------------------------------------

def test_partner_reciprocity_ok():
    """Binôme réciproque avec mêmes start/end → OK."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, partner="B", solo=False),
        _relay("B", 0, 0, 3, c, partner="A", solo=False),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Réciprocité    : OK" in text


def test_partner_not_reciprocal():
    """A dit binôme avec B, mais B ne dit pas binôme avec A → erreur."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, partner="B", solo=False),
        _relay("B", 0, 0, 3, c, partner=None, solo=True),  # pas réciproque
        _relay("A", 1, 3, 6, c),
        _relay("B", 1, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "RÉCIPROCITÉ" in text


def test_partner_different_arcs():
    """A et B disent binôme mais sur des arcs différents → erreur."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c, partner="B", solo=False),
        _relay("B", 0, 1, 4, c, partner="A", solo=False),  # arcs différents
        _relay("A", 1, 3, 6, c),
        _relay("B", 1, 4, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "RÉCIPROCITÉ" in text


# ------------------------------------------------------------------
# Km consistency
# ------------------------------------------------------------------

def test_km_consistency_ok():
    """km ≈ km_end - km_start → OK."""
    c = _make_constraints(nb_arcs=6, total_km=12.0)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("B", 0, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Km cohérence   : OK" in text


def test_km_consistency_wrong():
    """km modifié à la main, incohérent avec km_start/km_end → erreur."""
    c = _make_constraints(nb_arcs=6, total_km=12.0)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("B", 0, 3, 6, c),
    ]
    relays[0]["km"] = 99.0  # valeur falsifiée
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "KM" in text


# ------------------------------------------------------------------
# Start/end order and bounds
# ------------------------------------------------------------------

def test_start_end_order_ok():
    """start < end, dans les bornes → OK."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    relays = [
        _relay("A", 0, 0, 3, c),
        _relay("B", 0, 3, 6, c),
    ]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert "Ordre/bornes   : OK" in text


def test_start_end_reversed():
    """start >= end → erreur."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    rel_a = _relay("A", 0, 0, 3, c)
    rel_a["start"] = 4
    rel_a["end"] = 2  # inversé
    relays = [rel_a, _relay("B", 0, 3, 6, c)]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "ORDRE" in text


def test_start_end_equal():
    """start == end (relais de longueur 0) → erreur."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    rel_a = _relay("A", 0, 0, 3, c)
    rel_a["start"] = 3
    rel_a["end"] = 3
    relays = [rel_a, _relay("B", 0, 0, 6, c)]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "ORDRE" in text


def test_start_negative():
    """start négatif → erreur de bornes."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    rel_a = _relay("A", 0, 0, 3, c)
    rel_a["start"] = -1
    relays = [rel_a, _relay("B", 0, 3, 6, c)]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "BORNES" in text


def test_end_out_of_bounds():
    """end > dernier point → erreur de bornes."""
    c = _make_constraints(nb_arcs=6)
    c.new_runner("A", 3).add_relay(P6)
    c.new_runner("B", 3).add_relay(P6)
    rel_a = _relay("A", 0, 0, 3, c)
    rel_a["end"] = 99
    relays = [rel_a, _relay("B", 0, 3, 6, c)]
    sol = Solution(relays, c)
    ok, text = _check(sol)
    assert ok is False
    assert "BORNES" in text
