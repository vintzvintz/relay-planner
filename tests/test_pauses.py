"""
Tests unitaires — pauses planifiées (modèle espace-temps).

Dans le nouveau modèle, les pauses sont des segments INACTIFS dans l'espace-temps :
- inactive_ranges[i] = (time_start, time_end) : plage inactives [start, end)
- nb_segments = nb_active_segments + sum(b-a for a,b in inactive_ranges)
- segment_start_hour(seg) = start_hour + seg * segment_duration (linéaire, sans décalage)
- active_to_time_seg(a) convertit un index actif en index temps

Couvre :
1. Calcul de inactive_ranges dans Constraints.add_pause
2. segment_start_hour et active_to_time_seg
3. hour_to_seg roundtrip (trivial dans le nouveau modèle)
4. verifications._check_pauses sur solutions fictives
5. Intégration solveur : aucun relais ne couvre un segment inactif
6. _check_rest avec pauses (gap en temps inclut automatiquement les pauses)
7. Intégration solveur — repos avec pause
"""
import io
import pytest
from relay.constraints import Constraints, R10
from relay.verifications import _check_pauses, _check_rest


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


def _c(pauses: list[tuple[float, float]] | None = None, **kwargs) -> Constraints:
    """Crée un Constraints depuis _BASE en déclarant les pauses via add_pause().

    pauses : liste de (wall_clock_hour, duree) pour compatibilité.
             Triées par wall_clock_hour avant application.
    """
    base = {**_BASE, **kwargs}
    c = Constraints(**base)
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
# 1. Calcul de inactive_ranges
# ---------------------------------------------------------------------------

class TestPauseSegmentCalculation:

    def test_single_pause(self):
        # wall=15h, D=0 → ps = int((15-10)*10*100/100) = 50 ; 2h = 20 segs inactifs
        c = _c(pauses=[(15.0, 2.0)])
        assert c._pause_active_segs == [50]
        assert len(c.inactive_ranges) == 1
        a, b = c.inactive_ranges[0]
        assert a == 50
        assert b == 70   # 50 + ceil(2.0/0.1) = 50+20
        assert c.nb_segments == 120  # 100 actifs + 20 inactifs

    def test_no_pause(self):
        c = _c()
        assert c._pause_active_segs == []
        assert c.inactive_ranges == []
        assert c.nb_segments == c.nb_active_segments

    def test_two_pauses_sorted(self):
        # Pause 1 : wall=15, D=0 → ps=50, 1h=10 segs → [50, 60)
        # Pause 2 : wall=20, D=1 → ps=90, 0.5h=5 segs → time_start=90+10=100 → [100, 105)
        c = _c(pauses=[(20.0, 0.5), (15.0, 1.0)])
        assert c._pause_active_segs == [50, 90]
        assert c.inactive_ranges == [(50, 60), (100, 105)]
        assert c.nb_segments == 115  # 100 + 10 + 5

    def test_inactive_segments_content(self):
        # 1h=10 segs à active 50 → inactifs {50..59}
        c = _c(pauses=[(15.0, 1.0)])
        assert c.inactive_segments == set(range(50, 60))

    def test_active_segments_list(self):
        # 1h=10 segs à active 50 → actifs = [0..49] ∪ [60..109]
        c = _c(pauses=[(15.0, 1.0)])
        expected = list(range(50)) + list(range(60, 110))
        assert c.active_segments == expected

    def test_invalid_zero_duration(self):
        with pytest.raises(AssertionError):
            _c(pauses=[(15.0, 0.0)])

    def test_invalid_pause_at_start(self):
        # wall == start_hour → ps = 0 → assertion 0 < ps échoue
        with pytest.raises(AssertionError):
            _c(pauses=[(10.0, 1.0)])

    def test_invalid_pause_at_end(self):
        # wall = 20h → pure = 10h → ps = 100 = nb_active_segments → échoue
        with pytest.raises(AssertionError):
            _c(pauses=[(20.0, 1.0)])


# ---------------------------------------------------------------------------
# 2. segment_start_hour et active_to_time_seg
# ---------------------------------------------------------------------------

class TestSegmentStartHour:
    """Dans le nouveau modèle, segment_start_hour est linéaire sans correction de pause.
    La correspondance temps↔actif se fait via active_to_time_seg().
    """

    def setup_method(self):
        # 2h = 20 segs inactifs à time 50 → inactive [50, 70), nb_segments=120
        self.c = _c(pauses=[(15.0, 2.0)])

    def test_linearity(self):
        """segment_start_hour est linéaire sur tous les segments temps."""
        c = self.c
        for s in range(0, 120, 10):
            assert c.segment_start_hour(s) == pytest.approx(10.0 + s * 0.1)

    def test_active_to_time_seg_before_pause(self):
        """Segments actifs avant la pause : index temps = index actif."""
        c = self.c
        for a in range(50):
            assert c.active_to_time_seg(a) == a

    def test_active_to_time_seg_after_pause(self):
        """Segments actifs après la pause : décalage de 20 (durée de la pause)."""
        c = self.c
        for a in range(50, 100):
            assert c.active_to_time_seg(a) == a + 20

    def test_wall_clock_active_seg_before_pause(self):
        """Heure horloge du segment actif 49 (avant la pause)."""
        c = self.c
        t = c.active_to_time_seg(49)  # = 49
        assert c.segment_start_hour(t) == pytest.approx(10 + 49 * 0.1)

    def test_wall_clock_first_active_seg_after_pause(self):
        """Heure horloge du premier segment actif après la pause (actif 50 → temps 70)."""
        c = self.c
        t = c.active_to_time_seg(50)  # = 70
        assert t == 70
        assert c.segment_start_hour(t) == pytest.approx(10 + 70 * 0.1)  # = 17h

    def test_two_pauses_active_to_time(self):
        # Pause 1 : active 50, 1h=10 segs → [50, 60) ; Pause 2 : active 90, 0.5h=5 segs → [100, 105)
        c = _c(pauses=[(15.0, 1.0), (20.0, 0.5)])
        assert c.active_to_time_seg(49) == 49      # avant pause 1
        assert c.active_to_time_seg(50) == 60      # après pause 1 (+10)
        assert c.active_to_time_seg(89) == 99      # avant pause 2 (+10)
        assert c.active_to_time_seg(90) == 105     # après pause 2 (+15)
        assert c.active_to_time_seg(99) == 114     # fin de course (+15)

    def test_no_pause_no_offset(self):
        c = _c()
        assert c.segment_start_hour(50) == pytest.approx(10 + 50 * 0.1)


# ---------------------------------------------------------------------------
# 3. hour_to_seg — roundtrip (trivial dans le nouveau modèle)
# ---------------------------------------------------------------------------

class TestHourToSegRoundtrip:
    """hour_to_seg() retourne un index ACTIF ; segment_start_hour() prend un index TEMPS.
    Le roundtrip s'effectue sur les segments actifs uniquement :
      hour_to_seg(segment_start_hour(time_seg)) == active_idx
    où active_idx = time_seg_to_active(time_seg).
    Les segments inactifs (pauses) n'ont pas de correspondance active.
    """

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

    def _c(self, pauses=None, **kw):
        base = self._P | kw
        c = Constraints(**base)
        speed, nb, km, start = base["speed_kmh"], base["nb_segments"], base["total_km"], base["start_hour"]
        D = 0.0
        for wall_clock_hour, duree in sorted(pauses or [], key=lambda p: p[0]):
            ps = int((wall_clock_hour - start - D) * speed * nb / km)
            c.add_pause(seg=ps, duree=duree)
            D += duree
        return c

    def test_roundtrip_no_pause(self):
        c = self._c()
        for s in c.active_segments:
            active_idx = c.time_seg_to_active(s)
            assert c.hour_to_seg(c.segment_start_hour(s)) == active_idx

    def test_roundtrip_single_pause(self):
        # wall=15h → ps=5 ; 2h=2 segs → nb_segments=12
        # Les segments inactifs [5,7) n'ont pas de correspondance active.
        c = self._c(pauses=[(15.0, 2.0)])
        for s in c.active_segments:
            active_idx = c.time_seg_to_active(s)
            assert c.hour_to_seg(c.segment_start_hour(s)) == active_idx, f"roundtrip échoue seg temps {s}"

    def test_roundtrip_two_pauses(self):
        # Pause 1 : ps=5, dur=1h=1seg ; Pause 2 : wall=20 → ps=9 (après shift), dur=0.5h≈1seg
        c = self._c(pauses=[(15.0, 1.0), (20.0, 0.5)])
        for s in c.active_segments:
            active_idx = c.time_seg_to_active(s)
            assert c.hour_to_seg(c.segment_start_hour(s)) == active_idx, f"roundtrip échoue seg temps {s}"


# ---------------------------------------------------------------------------
# 4. verifications._check_pauses
# ---------------------------------------------------------------------------
# Géométrie : 100 segs actifs, pause 1h=10 segs à active 50 → inactive [50, 60), nb=110
# Les relais après la pause utilisent les indices temps (≥ 60).

class TestCheckPauses:

    def setup_method(self):
        self.c = _c(pauses=[(15.0, 1.0)])  # inactive [50, 60)

    def test_relay_entirely_before_pause(self):
        assert _check_pauses([_rel("A", 0, 40, 50)], self.c, _out()) is True

    def test_relay_ending_exactly_at_pause(self):
        # end == 50 : range(45,50) ∩ {50..59} = ∅ → OK
        assert _check_pauses([_rel("A", 0, 45, 50)], self.c, _out()) is True

    def test_relay_starting_exactly_after_pause(self):
        # start = 60 (premier temps actif après la pause) → OK
        assert _check_pauses([_rel("A", 0, 60, 70)], self.c, _out()) is True

    def test_relay_entirely_after_pause(self):
        assert _check_pauses([_rel("A", 0, 65, 75)], self.c, _out()) is True

    def test_relay_straddles_pause_start(self):
        # [45, 55) ∩ {50..59} = {50..54} → FAIL
        assert _check_pauses([_rel("A", 0, 45, 55)], self.c, _out()) is False

    def test_relay_entirely_inside_pause(self):
        # [51, 58) ⊂ {50..59} → FAIL
        assert _check_pauses([_rel("A", 0, 51, 58)], self.c, _out()) is False

    def test_relay_straddles_pause_end(self):
        # [55, 65) ∩ {50..59} = {55..59} → FAIL
        assert _check_pauses([_rel("A", 0, 55, 65)], self.c, _out()) is False

    def test_no_pause_never_triggers(self):
        c = _c()
        assert _check_pauses([_rel("A", 0, 0, 100)], c, _out()) is True

    def test_multiple_relays_one_straddling(self):
        sol = [
            _rel("A", 0, 0, 50),
            _rel("A", 1, 60, 110),
            _rel("B", 0, 45, 55),  # straddle la pause
        ]
        assert _check_pauses(sol, self.c, _out()) is False

    def test_empty_solution(self):
        assert _check_pauses([], self.c, _out()) is True

    def test_two_pauses_both_respected(self):
        # Pause 1 : [50, 60) ; Pause 2 : [100, 105)
        c = _c(pauses=[(15.0, 1.0), (20.0, 0.5)])
        sol = [
            _rel("A", 0, 0, 50),
            _rel("A", 1, 60, 100),
            _rel("A", 2, 105, 115),
        ]
        assert _check_pauses(sol, c, _out()) is True

    def test_two_pauses_second_straddled(self):
        # Pause 2 à [100, 105), relay [95, 106) straddle → FAIL
        c = _c(pauses=[(15.0, 1.0), (20.0, 0.5)])
        sol = [_rel("A", 0, 0, 50), _rel("A", 1, 95, 106)]
        assert _check_pauses(sol, c, _out()) is False


# ---------------------------------------------------------------------------
# 5. Intégration solveur
# ---------------------------------------------------------------------------

def _build_solver_constraints():
    """
    Problème minimal faisable avec pause :
    - 100 segments actifs, 1 km/seg, vitesse 10 km/h
    - Coureurs A et B incompatibles, 5×R10 chacun (= 50 segs actifs chacun)
    - Pause 1h à la frontière du segment actif 50 → inactive [50, 60), nb_total=110
    """
    c = Constraints(
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
    c.add_pause(seg=50, duree=1.0)
    c.new_runner("A").add_relay(R10, nb=5)
    c.new_runner("B").add_relay(R10, nb=5)
    return c


class TestSolverRespectsPause:

    @pytest.fixture(scope="class")
    def solutions(self):
        from relay.model import build_model
        from relay.solver import Solver
        c = _build_solver_constraints()
        relay_model = build_model(c)
        relay_model.add_optimisation_func(c)
        solver = Solver(relay_model, c)
        sols = list(solver.solve(timeout_sec=30, max_count=3, log_progress=False))
        assert sols, "Le solveur n'a trouvé aucune solution dans le délai imparti"
        return sols

    def test_solutions_found(self, solutions):
        assert len(solutions) >= 1

    def test_solutions_are_valid(self, solutions):
        for sol in solutions:
            assert sol.valid, "Solution.valid est False (vérifications ont échoué)"

    def test_no_relay_covers_inactive_segment(self, solutions):
        for sol in solutions:
            c = sol.constraints
            for rel in sol.relays:
                for s in range(rel["start"], rel["end"]):
                    assert s not in c.inactive_segments, (
                        f"{rel['runner']}[{rel['k']}] [{rel['start']}, {rel['end']}["
                        f" couvre le segment inactif {s}"
                    )

    def test_all_active_segments_covered(self, solutions):
        sol = solutions[0]
        c = sol.constraints
        coverage = [0] * c.nb_segments
        for rel in sol.relays:
            for s in range(rel["start"], rel["end"]):
                coverage[s] += 1
        for s in c.active_segments:
            assert coverage[s] >= 1, f"Segment actif {s} non couvert"


# ---------------------------------------------------------------------------
# 6. _check_rest avec pauses — tests unitaires
#
# Géométrie : 40 segs actifs, 1 km/seg, vitesse 10 km/h → segment_duration=0.1h
# repos_jour=3h → 30 time segs ; pause 2h=20 segs à active 20 → inactive [20, 40), nb=60
# Active segs 0..19 → time segs 0..19
# Active segs 20..39 → time segs 40..59
# ---------------------------------------------------------------------------

def _make_rest_constraints(repos_jour_h=3.0, repos_nuit_h=3.0, pause_seg=None, pause_dur_h=None):
    """Crée un Constraints 40 segs actifs, 1 km/seg, vitesse 10 km/h, coureur A déclaré."""
    c = Constraints(
        total_km=40.0,
        nb_segments=40,
        speed_kmh=10.0,
        start_hour=0.0,
        compat_matrix={("A", "B"): 0},
        solo_max_km=40.0,
        solo_max_default=10,
        nuit_max_default=10,
        repos_jour_heures=repos_jour_h,
        repos_nuit_heures=repos_nuit_h,
        nuit_debut=23.0,
        nuit_fin=5.0,
    )
    if pause_seg is not None:
        c.add_pause(seg=pause_seg, duree=pause_dur_h)
    c.new_runner("A").add_relay(R10, nb=4)
    return c


def _rest_rel(runner, k, start, end, night=False):
    return {"runner": runner, "k": k, "start": start, "end": end, "night": night}


class TestCheckRestWithPause:
    """
    Géométrie temps : nb_active=40, pause 2h=20 segs à active 20 → inactive [20,40), nb_total=60
    Active segs 0..19 → time segs 0..19
    Active segs 20..39 → time segs 40..59
    repos_jour = ceil(3.0/0.1) = 30 time segs

    Vérifications :
    - gap = nxt_start - prev_end (en time segs) ; gap_h = gap * 0.1
    - gap_h >= repos_h ssi gap >= repos_segs = 30
    """

    def setup_method(self):
        # pause 2h=20 segs inactifs à active 20 → inactive [20, 40), nb_total=60
        self.c = _make_rest_constraints(repos_jour_h=3.0, repos_nuit_h=3.0,
                                        pause_seg=20, pause_dur_h=2.0)

    def test_gap_exact_repos_ok(self):
        # prev=[0,5[, nxt=[35,45[ — nxt dans zone active après pause (active 15..24 → time 15..19,40..44)
        # Attention : on utilise des indices TEMPS. Relay [35,45) ∩ inactive [20,40) = {35..39} → straddle!
        # Utiliser nxt entièrement après la pause : time [40, 50) = active [20, 30)
        # gap = 40 - 5 = 35 ≥ 30 → OK
        sol = [_rest_rel("A", 0, 0, 5), _rest_rel("A", 1, 40, 50)]
        assert _check_rest(sol, self.c, _out()) is True

    def test_gap_too_small_no_pause_between_fail(self):
        # Deux relais entièrement avant la pause (time segs 0..19)
        # prev=[0,5[, nxt=[14,19[ — gap=9 time segs = 0.9h < 3h → FAIL
        sol = [_rest_rel("A", 0, 0, 5), _rest_rel("A", 1, 14, 19)]
        assert _check_rest(sol, self.c, _out()) is False

    def test_pause_intercalated_exact_repos_ok(self):
        # prev=[0,10[, nxt=[40,50[ — gap=30 time segs = 3h = repos → OK
        # (inactive [20,40) est entre eux)
        sol = [_rest_rel("A", 0, 0, 10), _rest_rel("A", 1, 40, 50)]
        assert _check_rest(sol, self.c, _out()) is True

    def test_pause_intercalated_gap_too_small_fail(self):
        # prev=[0,10[, nxt=[39,49[?  → [39,49) ∩ [20,40) = {39} → straddle, utiliser [40,50)
        # Pour un gap < 30 avec pause entre : prev=[0,10[, nxt=[39, ...] → impossible sans straddle
        # On teste plutôt : relais entièrement avant pause, gap insuffisant
        # prev=[0,10[, nxt=[19, 29[ — gap=9 < 30 ; [19,29) ∩ [20,40) = {20..28} → straddle!
        # Deux relais avant pause : prev=[0,10[, nxt=[14, 20[ — gap=4 < 30 → FAIL
        sol = [_rest_rel("A", 0, 0, 10), _rest_rel("A", 1, 14, 20)]
        assert _check_rest(sol, self.c, _out()) is False

    def test_both_relays_after_pause_small_gap_fail(self):
        # prev=[45,50[, nxt=[55,60[ — tous deux après la pause, gap=5 < 30 → FAIL
        sol = [_rest_rel("A", 0, 45, 50), _rest_rel("A", 1, 55, 60)]
        assert _check_rest(sol, self.c, _out()) is False

    def test_no_pause_normal_gap_ok(self):
        c = _make_rest_constraints(repos_jour_h=3.0, repos_nuit_h=3.0)
        sol = [_rest_rel("A", 0, 0, 5), _rest_rel("A", 1, 35, 40)]
        assert _check_rest(sol, c, _out()) is True

    def test_no_pause_gap_too_small_fail(self):
        c = _make_rest_constraints(repos_jour_h=3.0, repos_nuit_h=3.0)
        sol = [_rest_rel("A", 0, 0, 5), _rest_rel("A", 1, 34, 39)]
        assert _check_rest(sol, c, _out()) is False


# ---------------------------------------------------------------------------
# 7. Intégration solveur — repos avec pause
#
# repos=2h=20 time segs, pause=1h=10 segs à active 10 → inactive [10,20), nb_total=40
# Seuls starts valides (taille 10) : {0} ∪ {20..30}
# A[0]=[0,10[, repos=20 → A[1] doit démarrer ≥ 30. A[1]=[30,40[.
# B : couvre active 10..19 = time 20..29 → B=[20,30[.
# ---------------------------------------------------------------------------

def _build_rest_solver_constraints(repos_jour_h, with_pause):
    c = Constraints(
        total_km=30.0,
        nb_segments=30,
        speed_kmh=10.0,
        start_hour=0.0,
        compat_matrix={("A", "B"): 0},
        solo_max_km=30.0,
        solo_max_default=10,
        nuit_max_default=10,
        repos_jour_heures=repos_jour_h,
        repos_nuit_heures=repos_jour_h,
        nuit_debut=23.0,
        nuit_fin=5.0,
    )
    if with_pause:
        c.add_pause(seg=10, duree=1.0)  # inactive [10, 20), 1h=10 segs
    c.new_runner("A").add_relay(R10, nb=2)
    c.new_runner("B").add_relay(R10, nb=1)
    return c


def _solve(c, timeout=30):
    from relay.model import build_model
    from relay.solver import Solver
    relay_model = build_model(c)
    relay_model.add_optimisation_func(c)
    sols = list(Solver(relay_model, c).solve(timeout_sec=timeout, max_count=1, log_progress=False))
    return sols


class TestSolverRespectsRestWithPause:
    """
    Avec pause (repos=2h=20 segs, pause=1h=10 segs à active 10) :
      A[0]=[0,10[, A[1]=[30,40[ (obligé car repos=20 et la prochaine start valide est 30).
      gap en time = 30-10 = 20 time segs = 2h = repos_h → OK.

    Sans pause (repos=1h=10 segs) :
      A[0]=[0,10[, A[1]=[20,30[ — gap=10=repos_segs → OK.
    """

    @pytest.fixture(scope="class")
    def solutions_with_pause(self):
        c = _build_rest_solver_constraints(repos_jour_h=2.0, with_pause=True)
        sols = _solve(c)
        assert sols, "Aucune solution trouvée avec pause"
        return sols, c

    @pytest.fixture(scope="class")
    def solutions_without_pause(self):
        c = _build_rest_solver_constraints(repos_jour_h=1.0, with_pause=False)
        sols = _solve(c)
        assert sols, "Aucune solution trouvée sans pause"
        return sols, c

    def test_with_pause_valid(self, solutions_with_pause):
        sols, _ = solutions_with_pause
        assert sols[0].valid

    def test_without_pause_valid(self, solutions_without_pause):
        sols, _ = solutions_without_pause
        assert sols[0].valid

    def test_rest_respected_with_pause(self, solutions_with_pause):
        """gap en heures réelles >= repos_h (la pause est incluse dans le gap)."""
        sols, c = solutions_with_pause
        sd = c.segment_duration
        repos_h = c.runners_data["A"].options.repos_jour * sd
        rels_a = sorted(
            [r for r in sols[0].relays if r["runner"] == "A"],
            key=lambda x: x["start"]
        )
        for prev, nxt in zip(rels_a, rels_a[1:]):
            gap_h = (nxt["start"] - prev["end"]) * sd
            assert gap_h >= repos_h - 1e-9, (
                f"Repos insuffisant : gap={gap_h:.3f}h < {repos_h:.3f}h"
            )

    def test_gap_in_time_segs_at_least_repos_segs(self, solutions_with_pause):
        """Dans le modèle temps, gap_segs >= repos_segs (la pause est dans le gap)."""
        sols, c = solutions_with_pause
        repos_segs = c.runners_data["A"].options.repos_jour
        rels_a = sorted(
            [r for r in sols[0].relays if r["runner"] == "A"],
            key=lambda x: x["start"]
        )
        for prev, nxt in zip(rels_a, rels_a[1:]):
            gap_segs = nxt["start"] - prev["end"]
            assert gap_segs >= repos_segs, (
                f"gap_segs={gap_segs} < repos_segs={repos_segs}"
            )

    def test_no_pause_gap_equals_repos_segs(self, solutions_without_pause):
        """Sans pause, le gap en time segs est au moins repos_segs."""
        sols, c = solutions_without_pause
        repos_segs = c.runners_data["A"].options.repos_jour
        rels_a = sorted(
            [r for r in sols[0].relays if r["runner"] == "A"],
            key=lambda x: x["start"]
        )
        for prev, nxt in zip(rels_a, rels_a[1:]):
            gap = nxt["start"] - prev["end"]
            assert gap >= repos_segs, (
                f"Gap={gap} segs < repos={repos_segs} segs sans pause"
            )
