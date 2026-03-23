"""
Tests unitaires : prise en compte de solo_autorise_debut / solo_autorise_fin

Couvre :
  - is_solo_forbidden()  : logique jour normal et wrap-around minuit
  - solo_forbidden_segments : cohérence avec is_solo_forbidden sur l'ensemble des segments
  - plage couvrant 0h-24h : aucun segment interdit
  - verifications._check_solo_intervals : détection d'une violation dans une solution fictive
"""

import pytest
from constraints import RelayConstraints
from verifications import _check_solo_intervals, _NULL


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

COMPAT_MIN = {("A", "B"): 1}


def make_c(solo_debut: float, solo_fin: float, nb_segments: int = 96, start_hour: float = 15.0) -> RelayConstraints:
    """Construit un RelayConstraints minimal avec la plage solo demandée."""
    return RelayConstraints(
        total_km=144,
        nb_segments=nb_segments,
        speed_kmh=9.0,
        start_hour=start_hour,
        compat_matrix=COMPAT_MIN,
        solo_max_km=20,
        solo_max_default=1,
        nuit_max_default=1,
        repos_jour_heures=7,
        repos_nuit_heures=9,
        nuit_debut=0.0,
        nuit_fin=6.0,
        solo_autorise_debut=solo_debut,
        solo_autorise_fin=solo_fin,
    )


def _make_solution_entry(runner: str, k: int, start: int, size: int, solo: bool, partner=None) -> dict:
    return {
        "runner": runner,
        "k": k,
        "start": start,
        "end": start + size,
        "size": size,
        "solo": solo,
        "night": False,
        "fixe": False,
        "partner": partner,
    }


# ---------------------------------------------------------------------------
# Tests de is_solo_forbidden (logique pure)
# ---------------------------------------------------------------------------

class TestIsSoloForbidden:
    """Tests de la méthode is_solo_forbidden pour des plages normales et cross-minuit."""

    # Plage normale : 7h–22h30  (solo_debut < solo_fin)
    def test_segment_inside_window_is_allowed(self):
        """Un segment qui démarre à 10h (dans la plage 7h–22h30) doit être autorisé."""
        c = make_c(7.0, 22.5)
        # dur = 1.5/9 = 1/6 h → seg 114 : 15 + 114/6 = 15 + 19 = 34h → 10h mod 24
        seg = 114
        h = c.segment_start_hour(seg) % 24
        assert h >= 7.0
        assert h < 22.5
        assert not c.is_solo_forbidden(seg)

    def test_segment_before_window_is_forbidden(self):
        """Un segment qui démarre avant 7h doit être interdit."""
        c = make_c(7.0, 22.5)
        # seg 84 : 15 + 84/6 = 15 + 14 = 29h → 5h mod 24
        seg = 84
        h = c.segment_start_hour(seg) % 24
        assert h < 7.0 or h >= 22.5, f"Précondition: heure hors plage, obtenu {h}"
        assert c.is_solo_forbidden(seg)

    def test_segment_after_window_is_forbidden(self):
        """Un segment qui démarre après 22h30 doit être interdit."""
        c = make_c(7.0, 22.5)
        # seg 48 : 15 + 48/6 = 15 + 8 = 23h mod 24
        seg = 48
        h = c.segment_start_hour(seg) % 24
        assert h >= 22.5 or h < 7.0, f"Précondition: heure hors plage, obtenu {h}"
        assert c.is_solo_forbidden(seg)

    def test_exact_lower_bound_is_allowed(self):
        """Un segment démarrant exactement à solo_autorise_debut doit être autorisé."""
        c = make_c(7.0, 22.5, start_hour=7.0)
        h = c.segment_start_hour(0) % 24
        assert h == pytest.approx(7.0)
        assert not c.is_solo_forbidden(0)

    def test_exact_upper_bound_is_forbidden(self):
        """Un segment démarrant exactement à solo_autorise_fin doit être interdit."""
        c = make_c(7.0, 22.5, start_hour=22.5)
        h = c.segment_start_hour(0) % 24
        assert h == pytest.approx(22.5)
        assert c.is_solo_forbidden(0)

    # Plage cross-minuit : 22h–6h  (solo_debut > solo_fin)
    def test_crossmidnight_inside_window_is_allowed(self):
        """Plage 22h–6h : un segment à 23h (dans la plage) doit être autorisé."""
        c = make_c(22.0, 6.0, start_hour=23.0)
        h = c.segment_start_hour(0) % 24
        assert h == pytest.approx(23.0)
        assert not c.is_solo_forbidden(0)

    def test_crossmidnight_at_midnight_is_allowed(self):
        """Plage 22h–6h : un segment à 0h (dans la plage) doit être autorisé."""
        c = make_c(22.0, 6.0, start_hour=0.0)
        h = c.segment_start_hour(0) % 24
        assert h == pytest.approx(0.0)
        assert not c.is_solo_forbidden(0)

    def test_crossmidnight_outside_window_is_forbidden(self):
        """Plage 22h–6h : un segment à 10h (hors plage) doit être interdit."""
        c = make_c(22.0, 6.0, start_hour=10.0)
        h = c.segment_start_hour(0) % 24
        assert h == pytest.approx(10.0)
        assert c.is_solo_forbidden(0)

    def test_window_covers_full_day_no_segment_forbidden(self):
        """Plage 0h–24h : aucun segment ne doit être interdit."""
        c = make_c(0.0, 24.0)
        for seg in range(c.nb_segments):
            assert not c.is_solo_forbidden(seg), f"Segment {seg} ne devrait pas être interdit"

    def test_window_zero_length_all_segments_forbidden(self):
        """Plage de durée nulle (debut==fin) : tous les segments sont interdits."""
        c = make_c(15.0, 15.0, start_hour=15.0)
        for seg in range(c.nb_segments):
            assert c.is_solo_forbidden(seg), f"Segment {seg} devrait être interdit avec plage vide"


# ---------------------------------------------------------------------------
# Tests de solo_forbidden_segments
# ---------------------------------------------------------------------------

class TestSoloForbiddenSegments:

    def test_forbidden_segments_consistent_with_is_solo_forbidden(self):
        """solo_forbidden_segments doit être exactement l'ensemble des segments pour lesquels is_solo_forbidden est vrai."""
        c = make_c(7.0, 22.5)
        expected = {s for s in range(c.nb_segments) if c.is_solo_forbidden(s)}
        assert c.solo_forbidden_segments == expected

    def test_all_day_window_gives_empty_forbidden_set(self):
        """Plage 0h–24h : aucun segment interdit."""
        c = make_c(0.0, 24.0)
        assert c.solo_forbidden_segments == set()

    def test_forbidden_segments_nonempty_with_restricted_window(self):
        """Une plage restreinte (7h–22h30, départ 15h) doit produire des segments interdits."""
        c = make_c(7.0, 22.5)
        assert len(c.solo_forbidden_segments) > 0

    def test_forbidden_plus_allowed_equals_total(self):
        """forbidden + allowed == nb_segments."""
        c = make_c(7.0, 22.5)
        forbidden = c.solo_forbidden_segments
        allowed = {s for s in range(c.nb_segments) if not c.is_solo_forbidden(s)}
        assert len(forbidden) + len(allowed) == c.nb_segments
        assert forbidden & allowed == set()

    def test_crossmidnight_forbidden_segments_coherent(self):
        """Plage cross-minuit 22h–6h : aucun segment dans la plage autorisée ne doit apparaître comme interdit."""
        c = make_c(22.0, 6.0)
        for seg in c.solo_forbidden_segments:
            h = c.segment_start_hour(seg) % 24
            assert not (h >= 22.0 or h < 6.0), \
                f"Segment {seg} (h={h:.2f}h) est dans la plage autorisée mais déclaré interdit"

    def test_solo_autorise_debut_stored_correctly(self):
        """Les valeurs passées à l'init sont bien stockées dans les attributs."""
        c = make_c(8.5, 21.0)
        assert c.solo_autorise_debut == pytest.approx(8.5)
        assert c.solo_autorise_fin == pytest.approx(21.0)


# ---------------------------------------------------------------------------
# Tests d'intégration : verifications._check_solo_intervals
# ---------------------------------------------------------------------------

class TestCheckSoloIntervals:

    def test_solo_in_allowed_window_passes(self):
        """Un relais solo dans la plage autorisée ne doit pas déclencher d'erreur."""
        c = make_c(7.0, 22.5, start_hour=10.0)
        assert not c.is_solo_forbidden(0), "Précondition : seg 0 autorisé"
        solution = [_make_solution_entry("A", 0, start=0, size=10, solo=True)]
        assert _check_solo_intervals(solution, c, _NULL)

    def test_solo_in_forbidden_window_fails(self):
        """Un relais solo hors de la plage autorisée doit déclencher une erreur de vérification."""
        c = make_c(7.0, 22.5, start_hour=3.0)
        assert c.is_solo_forbidden(0), "Précondition : seg 0 interdit"
        solution = [_make_solution_entry("A", 0, start=0, size=10, solo=True)]
        assert not _check_solo_intervals(solution, c, _NULL)

    def test_binome_in_forbidden_window_passes(self):
        """Un relais en binôme (solo=False) dans une plage interdite doit être accepté."""
        c = make_c(7.0, 22.5, start_hour=3.0)
        assert c.is_solo_forbidden(0), "Précondition : seg 0 interdit"
        solution = [_make_solution_entry("A", 0, start=0, size=10, solo=False, partner="B")]
        assert _check_solo_intervals(solution, c, _NULL)

    def test_multiple_runners_mixed_validity(self):
        """Un coureur OK et un autre en violation : check doit échouer."""
        c = make_c(7.0, 22.5, start_hour=15.0)
        # seg 72 : 15 + 72/6 = 15 + 12 = 27h → 3h mod 24 → interdit
        forbidden_seg = 72
        h = c.segment_start_hour(forbidden_seg) % 24
        assert c.is_solo_forbidden(forbidden_seg), f"Précondition : seg {forbidden_seg} (h={h:.2f}) interdit"
        solution = [
            _make_solution_entry("A", 0, start=0, size=10, solo=True),
            _make_solution_entry("B", 0, start=forbidden_seg, size=10, solo=True),
        ]
        assert not _check_solo_intervals(solution, c, _NULL)

    def test_no_solos_always_passes(self):
        """Si aucun relais n'est solo, la vérification passe quel que soit le paramétrage."""
        c = make_c(7.0, 22.5, start_hour=3.0)
        solution = [
            _make_solution_entry("A", 0, start=0, size=10, solo=False, partner="B"),
            _make_solution_entry("B", 0, start=0, size=10, solo=False, partner="A"),
        ]
        assert _check_solo_intervals(solution, c, _NULL)

    def test_allday_window_solo_always_passes(self):
        """Plage 0h–24h : un solo à n'importe quelle heure doit toujours passer."""
        c = make_c(0.0, 24.0, start_hour=3.0)
        solution = [_make_solution_entry("A", 0, start=0, size=10, solo=True)]
        assert _check_solo_intervals(solution, c, _NULL)
