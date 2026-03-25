"""
Tests unitaires — pauses planifiées.

Couvre :
1. Calcul de pause_segments dans RelayConstraints.__init__
2. segment_start_hour avec décalage de pause
3. hour_to_seg avec décalage (roundtrip)
4. verifications._check_pauses sur solutions fictives
5. Intégration solveur : aucun relais ne franchit une frontière de pause
"""
import io
import pytest
from constraints import RelayConstraints, R10
from verifications import _check_pauses


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Paramètres de base : 100 segments de 1 km, vitesse 10 km/h → segment_duration = 0.1h
_BASE = dict(
    total_km=100.0,
    nb_segments=100,
    speed_kmh=10.0,
    start_hour=10.0,
    compat_matrix={("A", "B"): 0},
    solo_max_km=50.0,
    solo_max_default=5,
    nuit_max_default=10,
    repos_jour_heures=0.0,
    repos_nuit_heures=0.0,
    nuit_debut=3.0,
    nuit_fin=4.0,
)


def _c(pauses: list[tuple[float, float]] | None = None, **kwargs) -> RelayConstraints:
    """Crée un RelayConstraints depuis _BASE en déclarant les pauses via add_pause().

    pauses : liste de (wall_clock_hour, duree) pour compatibilité avec l'ancienne API de test.
             Triées par wall_clock_hour avant application (comportement identique à l'ancien code).
    """
    base = {**_BASE, **kwargs}
    c = RelayConstraints(**base)
    speed, nb, km, start = base["speed_kmh"], base["nb_segments"], base["total_km"], base["start_hour"]
    D = 0.0
    for wall_clock_hour, duree in sorted(pauses or [], key=lambda p: p[0]):
        ps = int((wall_clock_hour - start - D) * speed * nb / km)
        c.add_pause(seg=ps, duree=duree)
        D += duree
    return c


def _rel(runner, k, start, end) -> dict:
    return {"runner": runner, "k": k, "start": start, "end": end}


def _out():
    return io.StringIO()


# ---------------------------------------------------------------------------
# 1. Calcul de pause_segments
# ---------------------------------------------------------------------------

class TestPauseSegmentCalculation:

    def test_single_pause(self):
        # wall=15h, D=0 → pure=5h → ps = int(5 * 10 * 100 / 100) = 50
        c = _c(pauses=[(15.0, 2.0)])
        assert c.pause_segments == [50]
        assert c.pause_duration_hours == [2.0]

    def test_no_pause(self):
        c = _c()
        assert c.pause_segments == []

    def test_two_pauses_sorted(self):
        # Déclarées dans le désordre → triées par wall_clock_hour
        # Pause 1 : wall=15, D=0  → pure=5  → ps=50 ; D devient 1.0
        # Pause 2 : wall=20, D=1  → pure=9  → ps=90
        c = _c(pauses=[(20.0, 0.5), (15.0, 1.0)])
        assert c.pause_segments == [50, 90]
        assert c.pause_duration_hours == [1.0, 0.5]

    def test_invalid_zero_duration(self):
        with pytest.raises(AssertionError):
            _c(pauses=[(15.0, 0.0)])

    def test_invalid_pause_at_start(self):
        # wall == start_hour → ps = 0 → assertion 0 < ps échoue
        with pytest.raises(AssertionError):
            _c(pauses=[(10.0, 1.0)])

    def test_invalid_pause_at_end(self):
        # wall = 20h → pure = 10h → ps = 100 = nb_segments → assertion ps < nb_segments échoue
        with pytest.raises(AssertionError):
            _c(pauses=[(20.0, 1.0)])


# ---------------------------------------------------------------------------
# 2. segment_start_hour avec pauses
# ---------------------------------------------------------------------------

class TestSegmentStartHour:
    # Pause de 2h à la frontière seg 50 (wall_clock=15h)

    def setup_method(self):
        self.c = _c(pauses=[(15.0, 2.0)])

    def test_before_pause_no_offset(self):
        assert self.c.segment_start_hour(49) == pytest.approx(10 + 49 * 0.1)

    def test_at_pause_boundary_offset_added(self):
        # seg 50 est le premier segment après la pause → décalage +2h
        assert self.c.segment_start_hour(50) == pytest.approx(10 + 50 * 0.1 + 2.0)

    def test_after_pause_offset_added(self):
        assert self.c.segment_start_hour(60) == pytest.approx(10 + 60 * 0.1 + 2.0)

    def test_no_pause_no_offset(self):
        c = _c()
        assert c.segment_start_hour(50) == pytest.approx(10 + 50 * 0.1)

    def test_two_pauses_cumulative_offset(self):
        # Pause 1 : seg 50, dur=1h ; Pause 2 : seg 90, dur=0.5h
        c = _c(pauses=[(15.0, 1.0), (20.0, 0.5)])
        assert c.segment_start_hour(49) == pytest.approx(10 + 49 * 0.1)           # aucun décalage
        assert c.segment_start_hour(50) == pytest.approx(10 + 50 * 0.1 + 1.0)     # +1h
        assert c.segment_start_hour(89) == pytest.approx(10 + 89 * 0.1 + 1.0)     # +1h seulement
        assert c.segment_start_hour(90) == pytest.approx(10 + 90 * 0.1 + 1.5)     # +1.5h
        assert c.segment_start_hour(99) == pytest.approx(10 + 99 * 0.1 + 1.5)     # +1.5h


# ---------------------------------------------------------------------------
# 3. hour_to_seg — roundtrip segment_start_hour ↔ hour_to_seg
# ---------------------------------------------------------------------------

class TestHourToSegRoundtrip:
    """
    Utilise nb_segments=10 / total_km=100 / speed=10 pour obtenir
    segment_duration=1h (représentable exactement en float).
    Évite les imprécisions de troncature qui affectent 99 * 0.1 * 10 = 98.999…
    """

    # 10 segments de 10 km, durée 1h chacun — arithmétique exacte
    _P = dict(
        total_km=100.0,
        nb_segments=10,
        speed_kmh=10.0,
        start_hour=10.0,
        compat_matrix={("A", "B"): 0},
        solo_max_km=50.0,
        solo_max_default=5,
        nuit_max_default=10,
        repos_jour_heures=0.0,
        repos_nuit_heures=0.0,
        nuit_debut=3.0,
        nuit_fin=4.0,
    )

    def _c(self, pauses: list[tuple[float, float]] | None = None, **kw):
        base = self._P | kw
        c = RelayConstraints(**base)
        speed, nb, km, start = base["speed_kmh"], base["nb_segments"], base["total_km"], base["start_hour"]
        D = 0.0
        for wall_clock_hour, duree in sorted(pauses or [], key=lambda p: p[0]):
            ps = int((wall_clock_hour - start - D) * speed * nb / km)
            c.add_pause(seg=ps, duree=duree)
            D += duree
        return c

    def test_roundtrip_no_pause(self):
        c = self._c()
        for s in range(10):
            assert c.hour_to_seg(c.segment_start_hour(s)) == s

    def test_roundtrip_single_pause(self):
        # wall=15h → pure=5h → ps=5 ; pause 2h
        c = self._c(pauses=[(15.0, 2.0)])
        for s in range(10):
            assert c.hour_to_seg(c.segment_start_hour(s)) == s, f"roundtrip échoue seg {s}"

    def test_roundtrip_two_pauses(self):
        # Pause 1 : ps=5, dur=1h ; Pause 2 : wall=20, D=1 → pure=9 → ps=9
        c = self._c(pauses=[(15.0, 1.0), (20.0, 0.5)])
        for s in range(10):
            assert c.hour_to_seg(c.segment_start_hour(s)) == s, f"roundtrip échoue seg {s}"


# ---------------------------------------------------------------------------
# 4. verifications._check_pauses
# ---------------------------------------------------------------------------

class TestCheckPauses:
    # pause_segments = [50] dans ce groupe

    def setup_method(self):
        self.c = _c(pauses=[(15.0, 1.0)])

    def test_relay_entirely_before_pause(self):
        assert _check_pauses([_rel("A", 0, 40, 50)], self.c, _out()) is True

    def test_relay_ending_exactly_at_pause(self):
        # end == ps : pas de franchissement (ps < end est False)
        assert _check_pauses([_rel("A", 0, 45, 50)], self.c, _out()) is True

    def test_relay_starting_exactly_at_pause(self):
        # start == ps : pas de franchissement (start < ps est False)
        assert _check_pauses([_rel("A", 0, 50, 60)], self.c, _out()) is True

    def test_relay_entirely_after_pause(self):
        assert _check_pauses([_rel("A", 0, 55, 65)], self.c, _out()) is True

    def test_relay_straddles_pause(self):
        # start=45, end=55 → 45 < 50 < 55
        assert _check_pauses([_rel("A", 0, 45, 55)], self.c, _out()) is False

    def test_no_pause_never_triggers(self):
        c = _c()
        # Un relais qui couvrirait toute la course ne déclenche rien sans pause
        assert _check_pauses([_rel("A", 0, 0, 100)], c, _out()) is True

    def test_multiple_relays_one_straddling(self):
        sol = [
            _rel("A", 0, 0, 50),
            _rel("A", 1, 50, 100),
            _rel("B", 0, 45, 55),  # franchit le pause
        ]
        assert _check_pauses(sol, self.c, _out()) is False

    def test_empty_solution(self):
        assert _check_pauses([], self.c, _out()) is True

    def test_two_pauses_both_respected(self):
        c = _c(pauses=[(15.0, 1.0), (20.0, 0.5)])  # ps=[50, 90]
        sol = [_rel("A", 0, 0, 50), _rel("A", 1, 50, 90), _rel("A", 2, 90, 100)]
        assert _check_pauses(sol, c, _out()) is True

    def test_two_pauses_second_straddled(self):
        c = _c(pauses=[(15.0, 1.0), (20.0, 0.5)])  # ps=[50, 90]
        sol = [_rel("A", 0, 0, 50), _rel("A", 1, 85, 95)]  # straddle ps=90
        assert _check_pauses(sol, c, _out()) is False


# ---------------------------------------------------------------------------
# 5. Intégration solveur
# ---------------------------------------------------------------------------

def _build_solver_constraints():
    """
    Problème minimal faisable avec pause :
    - 100 segments de 1 km (vitesse 10 km/h)
    - Coureurs A et B incompatibles, 5 × R10 chacun (= 50 segs chacun)
    - Pause à la frontière seg 50 → chaque coureur couvre une moitié
    """
    c = RelayConstraints(
        total_km=100.0,
        nb_segments=100,
        speed_kmh=10.0,
        start_hour=10.0,
        compat_matrix={("A", "B"): 0},
        solo_max_km=50.0,
        solo_max_default=5,
        nuit_max_default=10,
        repos_jour_heures=0.0,
        repos_nuit_heures=0.0,
        nuit_debut=3.0,
        nuit_fin=4.0,
    )
    c.add_pause(seg=50, duree=1.0)  # pause frontière seg 50
    c.new_runner("A").add_relay(R10, nb=5)
    c.new_runner("B").add_relay(R10, nb=5)
    return c


class TestSolverRespectsPause:

    @pytest.fixture(scope="class")
    def solutions(self):
        from model import build_model
        from solver import RelaySolver
        c = _build_solver_constraints()
        relay_model = build_model(c)
        relay_model.add_optimisation_func(c)
        solver = RelaySolver(relay_model, c)
        sols = list(solver.solve(timeout_sec=30, max_count=3, log_progress=False))
        assert sols, "Le solveur n'a trouvé aucune solution dans le délai imparti"
        return sols

    def test_solutions_found(self, solutions):
        assert len(solutions) >= 1

    def test_solutions_are_valid(self, solutions):
        for sol in solutions:
            assert sol.valid, "RelaySolution.valid est False (vérifications ont échoué)"

    def test_no_relay_straddles_pause(self, solutions):
        for sol in solutions:
            c = sol.constraints
            for rel in sol.relais_list:
                for ps in c.pause_segments:
                    assert not (rel["start"] < ps < rel["end"]), (
                        f"{rel['runner']}[{rel['k']}] [{rel['start']}, {rel['end']}["
                        f" franchit la frontière de pause seg {ps}"
                    )

    def test_all_segments_covered(self, solutions):
        sol = solutions[0]
        c = sol.constraints
        coverage = [0] * c.nb_segments
        for rel in sol.relais_list:
            for s in range(rel["start"], rel["end"]):
                coverage[s] += 1
        assert all(v >= 1 for v in coverage), "Des segments ne sont pas couverts"
