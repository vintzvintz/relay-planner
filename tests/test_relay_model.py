"""Tests unitaires de RelayModel : variables CP-SAT, contraintes, structure du modèle."""

import pytest
from ortools.sat.python import cp_model

from constraints import RelayConstraints, RelayIntervals
from model import RelayModel, build_model


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# nb=90, total_km=90 → seg_km=1 km → relay_types cohérents avec les vraies tailles km :
#   R10={10}, R15={15}, R20={20}, R30={30}, R13_F={10..13}, R15_F={10..15}
# Couvertures exactes faciles : 3×R30=90, 6×R15=90, 9×R10=90
NB = 90
KM = 90.0


def _make_rc(compat_matrix=None, solo_max_km=90.0, repos_jour=0.0, repos_nuit=0.0):
    """RelayConstraints diurne (départ 8h), 90 km / 90 segs (1 km/seg), sans segments nocturnes."""
    return RelayConstraints(
        total_km=KM,
        nb_segments=NB,
        speed_kmh=KM / NB,
        start_hour=8.0,
        compat_matrix=compat_matrix or {},
        solo_max_km=solo_max_km,
        solo_max_default=99,
        nuit_max_default=99,
        repos_jour_heures=repos_jour,
        repos_nuit_heures=repos_nuit,
        nuit_debut=0.0,
        nuit_fin=0.0,
    )


# ---------------------------------------------------------------------------
# Fixtures
#
# R10={10}, R15={15}, R20={20}, R30={30}, R15_F={10..15}
# Couverture totale 90 segs : ex. Alice 3×R15(15) + Bob 3×R15(15) = 90
# ---------------------------------------------------------------------------

@pytest.fixture
def c2():
    """2 coureurs compatibles, couverture 90 segs (3×R15 chacun)."""
    rc = _make_rc(compat_matrix={("Alice", "Bob"): 2})
    rc.new_runner("Alice").add_relay("R15", nb=3)
    rc.new_runner("Bob").add_relay("R15", nb=3)
    return rc


@pytest.fixture
def c_incompatible():
    """2 coureurs incompatibles, couverture 90 segs."""
    rc = _make_rc(compat_matrix={("Alice", "Bob"): 0})
    rc.new_runner("Alice").add_relay("R15", nb=3)
    rc.new_runner("Bob").add_relay("R15", nb=3)
    return rc


@pytest.fixture
def c_multi_relay():
    """Alice : 2×R10(10), Bob : 1×R10(10), Carol : 7×R10 — couverture totale 90 segs."""
    rc = _make_rc(compat_matrix={("Alice", "Bob"): 1, ("Alice", "Carol"): 0, ("Bob", "Carol"): 0})
    rc.new_runner("Alice").add_relay("R10").add_relay("R10")
    rc.new_runner("Bob").add_relay("R10")
    rc.new_runner("Carol").add_relay("R10", nb=7)
    return rc


@pytest.fixture
def c_flex():
    """Alice R15_F {10..15}, Bob R15 {15}, Carol 5×R15 — couverture totale 90 segs."""
    rc = _make_rc(compat_matrix={("Alice", "Bob"): 2, ("Alice", "Carol"): 0, ("Bob", "Carol"): 0})
    rc.new_runner("Alice").add_relay("R15_F")
    rc.new_runner("Bob").add_relay("R15")
    rc.new_runner("Carol").add_relay("R15", nb=5)
    return rc


@pytest.fixture
def c_pinned():
    """Alice pinnée au seg 0 (R30=30), Bob+Carol couvrent le reste (30+30=60)."""
    rc = _make_rc(compat_matrix={("Alice", "Bob"): 0, ("Alice", "Carol"): 0, ("Bob", "Carol"): 0})
    rc.new_runner("Alice").add_relay("R30", pinned=0)
    rc.new_runner("Bob").add_relay("R30")
    rc.new_runner("Carol").add_relay("R30")
    return rc


@pytest.fixture
def c_window():
    """Alice fenêtre [0, 35] (R30=30 → end ≤ 36). Bob+Carol couvrent le reste."""
    rc = _make_rc(compat_matrix={("Alice", "Bob"): 0, ("Alice", "Carol"): 0, ("Bob", "Carol"): 0})
    rc.new_runner("Alice").add_relay("R30", window=RelayIntervals([(0, 35)]))
    rc.new_runner("Bob").add_relay("R30")
    rc.new_runner("Carol").add_relay("R30")
    return rc


@pytest.fixture
def c_shared():
    """SharedRelay R30 entre Alice et Bob (binôme forcé), Carol couvre le reste."""
    rc = _make_rc(compat_matrix={("Alice", "Bob"): 2, ("Alice", "Carol"): 0, ("Bob", "Carol"): 0})
    shared = rc.new_relay("R30")
    rc.new_runner("Alice").add_relay(shared)
    rc.new_runner("Bob").add_relay(shared)
    rc.new_runner("Carol").add_relay("R30", nb=2)
    return rc


# ---------------------------------------------------------------------------
# Construction du modèle
# ---------------------------------------------------------------------------

class TestBuildModel:
    def test_model_created(self, c2):
        m = build_model(c2)
        assert m.model is not None

    def test_model_is_cpsat(self, c2):
        m = build_model(c2)
        assert isinstance(m.model, cp_model.CpModel)

    def test_double_build_raises(self, c2):
        m = RelayModel()
        m.build(c2)
        with pytest.raises(AssertionError):
            m.build(c2)


# ---------------------------------------------------------------------------
# Variables start / end / size
# ---------------------------------------------------------------------------

class TestVariables:
    def test_start_keys(self, c2):
        m = build_model(c2)
        assert set(m.start.keys()) == {"Alice", "Bob"}

    def test_end_keys(self, c2):
        m = build_model(c2)
        assert set(m.end.keys()) == {"Alice", "Bob"}

    def test_size_keys(self, c2):
        m = build_model(c2)
        assert set(m.size.keys()) == {"Alice", "Bob"}

    def test_relay_count_per_runner(self, c_multi_relay):
        m = build_model(c_multi_relay)
        assert len(m.start["Alice"]) == 2
        assert len(m.start["Bob"]) == 1

    def test_intervals_all_length(self, c_multi_relay):
        m = build_model(c_multi_relay)
        # Alice=2, Bob=1, Carol=7 → 10 intervalles au total
        assert len(m._intervals_all) == 10

    def test_intervals_all_structure(self, c2):
        m = build_model(c2)
        for entry in m._intervals_all:
            assert len(entry) == 4  # (r, k, sz_max, interval_var)

    def test_flex_size_domain(self, c_flex):
        m = build_model(c_flex)
        assert len(m.size["Alice"]) == 1
        assert len(m.size["Bob"]) == 1


# ---------------------------------------------------------------------------
# Variables solo / nuit
# ---------------------------------------------------------------------------

class TestSoloNuitVars:
    def test_relais_solo_keys(self, c2):
        m = build_model(c2)
        assert "Alice" in m.relais_solo
        assert "Bob" in m.relais_solo

    def test_relais_nuit_keys(self, c2):
        m = build_model(c2)
        assert "Alice" in m.relais_nuit
        assert "Bob" in m.relais_nuit

    def test_relais_solo_count(self, c_multi_relay):
        m = build_model(c_multi_relay)
        assert len(m.relais_solo["Alice"]) == 2
        assert len(m.relais_solo["Bob"]) == 1

    def test_relais_nuit_count(self, c_multi_relay):
        m = build_model(c_multi_relay)
        assert len(m.relais_nuit["Alice"]) == 2
        assert len(m.relais_nuit["Bob"]) == 1


# ---------------------------------------------------------------------------
# Variables same_relay (binômes)
# ---------------------------------------------------------------------------

class TestSameRelayVars:
    def test_same_relay_created_for_compatible(self, c2):
        m = build_model(c2)
        # 3 relais chacun → 3*3 = 9 paires potentielles
        assert len(m.same_relay) == 9
        assert ("Alice", 0, "Bob", 0) in m.same_relay

    def test_same_relay_empty_for_incompatible(self, c_incompatible):
        m = build_model(c_incompatible)
        assert len(m.same_relay) == 0

    def test_same_relay_key_order(self, c2):
        m = build_model(c2)
        for (r, k, rp, kp) in m.same_relay:
            assert c2.runners.index(r) < c2.runners.index(rp)

    def test_same_relay_multi_relay_count(self, c_multi_relay):
        """Alice 2 relais, Bob 1 → 2 paires potentielles."""
        m = build_model(c_multi_relay)
        assert len(m.same_relay) == 2

    def test_no_same_relay_for_incompatible_sizes(self):
        """Pas de same_relay si les domaines de taille ne se chevauchent pas."""
        rc = _make_rc(compat_matrix={("Alice", "Bob"): 2})
        rc.new_runner("Alice").add_relay("R10")  # {10}
        rc.new_runner("Bob").add_relay("R30")    # {30}
        m = build_model(rc)
        assert len(m.same_relay) == 0


# ---------------------------------------------------------------------------
# Résolution : vérification de faisabilité
# ---------------------------------------------------------------------------

class TestSolvability:
    def _solve(self, constraints, timeout=10):
        m = build_model(constraints)
        m.add_optimisation_func(constraints)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = timeout
        status = solver.solve(m.model)
        return status, solver, m

    def test_simple_feasible(self, c2):
        status, _, _ = self._solve(c2)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def test_incompatible_feasible(self, c_incompatible):
        status, _, _ = self._solve(c_incompatible)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def test_pinned_respected(self, c_pinned):
        status, solver, m = self._solve(c_pinned)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.value(m.start["Alice"][0]) == 0

    def test_window_respected(self, c_window):
        status, solver, m = self._solve(c_window)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.value(m.start["Alice"][0]) >= 0
        assert solver.value(m.end["Alice"][0]) <= 36  # [0,35] + taille 30 → end ≤ 36

    def test_shared_relay_same_start(self, c_shared):
        status, solver, m = self._solve(c_shared)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.value(m.start["Alice"][0]) == solver.value(m.start["Bob"][0])

    def test_score_binome_positive(self):
        """Binôme activé quand les deux coureurs compatibles se chevauchent.

        Alice 4×R15=60, Bob 1×R15=15, Carol 2×R15=30 → 105 segs pour 90 → 1 binôme possible.
        """
        rc = _make_rc(compat_matrix={("Alice", "Bob"): 2, ("Alice", "Carol"): 0, ("Bob", "Carol"): 0})
        rc.new_runner("Alice").add_relay("R15", nb=4)
        rc.new_runner("Bob").add_relay("R15", nb=1)
        rc.new_runner("Carol").add_relay("R15", nb=2)
        status, solver, m = self._solve(rc)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        n_binomes = sum(solver.value(bv) for bv in m.same_relay.values())
        assert n_binomes >= 1

    def test_multi_relay_no_overlap(self, c_multi_relay):
        """Les 2 relais d'Alice ne doivent pas se chevaucher."""
        status, solver, m = self._solve(c_multi_relay)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        s0 = solver.value(m.start["Alice"][0])
        e0 = solver.value(m.end["Alice"][0])
        s1 = solver.value(m.start["Alice"][1])
        e1 = solver.value(m.end["Alice"][1])
        assert e0 <= s1 or e1 <= s0

    def test_flex_size_matches_partner(self, c_flex):
        """En binôme, la taille flex d'Alice doit correspondre à celle de Bob."""
        status, solver, m = self._solve(c_flex)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        key = ("Alice", 0, "Bob", 0)
        if key in m.same_relay and solver.value(m.same_relay[key]) == 1:
            assert solver.value(m.size["Alice"][0]) == solver.value(m.size["Bob"][0])


# ---------------------------------------------------------------------------
# add_max_binomes (_add_once_max)
# ---------------------------------------------------------------------------

class TestOnceMax:
    def _solve(self, rc, timeout=10):
        m = build_model(rc)
        m.add_optimisation_func(rc)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = timeout
        status = solver.solve(m.model)
        return status, solver, m

    def _rc_two_relays_each(self, nb_max):
        """Alice 2×R15(15), Bob 2×R15(15), Carol 2×R15(15) → 90 segs."""
        rc = _make_rc(compat_matrix={("Alice", "Bob"): 2, ("Alice", "Carol"): 0, ("Bob", "Carol"): 0})
        alice = rc.new_runner("Alice").add_relay("R15").add_relay("R15")
        bob = rc.new_runner("Bob").add_relay("R15").add_relay("R15")
        rc.new_runner("Carol").add_relay("R15", nb=2)
        rc.add_max_binomes(alice, bob, nb=nb_max)
        return rc

    def test_once_max_1_feasible(self):
        status, _, _ = self._solve(self._rc_two_relays_each(nb_max=1))
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def test_once_max_1_at_most_one_binome(self):
        status, solver, m = self._solve(self._rc_two_relays_each(nb_max=1))
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        n = sum(solver.value(bv) for (r1,_,r2,_), bv in m.same_relay.items()
                if {r1, r2} == {"Alice", "Bob"})
        assert n <= 1

    def test_once_max_0_no_binome(self):
        status, solver, m = self._solve(self._rc_two_relays_each(nb_max=0))
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        n = sum(solver.value(bv) for (r1,_,r2,_), bv in m.same_relay.items()
                if {r1, r2} == {"Alice", "Bob"})
        assert n == 0

    def test_once_max_2_allows_both_binomes(self):
        status, solver, m = self._solve(self._rc_two_relays_each(nb_max=2))
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        n = sum(solver.value(bv) for (r1,_,r2,_), bv in m.same_relay.items()
                if {r1, r2} == {"Alice", "Bob"})
        assert n <= 2


# ---------------------------------------------------------------------------
# max_same_partenaire (_add_max_same_partenaire)
# ---------------------------------------------------------------------------

class TestMaxSamePartenaire:
    def _solve(self, rc, timeout=10):
        m = build_model(rc)
        m.add_optimisation_func(rc)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = timeout
        status = solver.solve(m.model)
        return status, solver, m

    def _rc_global(self, max_same):
        rc = _make_rc(compat_matrix={("Alice", "Bob"): 2, ("Alice", "Carol"): 0, ("Bob", "Carol"): 0})
        rc.max_same_partenaire = max_same
        rc.new_runner("Alice").add_relay("R15").add_relay("R15")
        rc.new_runner("Bob").add_relay("R15").add_relay("R15")
        rc.new_runner("Carol").add_relay("R15", nb=2)
        return rc

    def _rc_individual(self, max_same_alice):
        rc = _make_rc(compat_matrix={("Alice", "Bob"): 2, ("Alice", "Carol"): 0, ("Bob", "Carol"): 0})
        rc.new_runner("Alice").set_options(max_same_partenaire=max_same_alice).add_relay("R15").add_relay("R15")
        rc.new_runner("Bob").add_relay("R15").add_relay("R15")
        rc.new_runner("Carol").add_relay("R15", nb=2)
        return rc

    def test_global_limit_1_feasible(self):
        status, _, _ = self._solve(self._rc_global(max_same=1))
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def test_global_limit_1_at_most_one_binome(self):
        status, solver, m = self._solve(self._rc_global(max_same=1))
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        n = sum(solver.value(bv) for (r1,_,r2,_), bv in m.same_relay.items()
                if {r1, r2} == {"Alice", "Bob"})
        assert n <= 1

    def test_individual_limit_applies(self):
        status, solver, m = self._solve(self._rc_individual(max_same_alice=1))
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        n = sum(solver.value(bv) for (r1,_,r2,_), bv in m.same_relay.items()
                if {r1, r2} == {"Alice", "Bob"})
        assert n <= 1

    def test_no_limit_more_binomes_than_with_limit(self):
        def solve_and_count(limit):
            rc = _make_rc(compat_matrix={("Alice", "Bob"): 2, ("Alice", "Carol"): 0, ("Bob", "Carol"): 0})
            rc.new_runner("Alice").add_relay("R15").add_relay("R15")
            rc.new_runner("Bob").add_relay("R15").add_relay("R15")
            rc.new_runner("Carol").add_relay("R15", nb=2)
            if limit is not None:
                rc.max_same_partenaire = limit
            m = build_model(rc)
            m.add_optimisation_func(rc)
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = 10
            status = solver.solve(m.model)
            assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
            return sum(solver.value(bv) for (r1,_,r2,_), bv in m.same_relay.items()
                       if {r1, r2} == {"Alice", "Bob"})

        assert solve_and_count(None) >= solve_and_count(1)

    def test_individual_overrides_global(self):
        rc = _make_rc(compat_matrix={("Alice", "Bob"): 2, ("Alice", "Carol"): 0, ("Bob", "Carol"): 0})
        rc.max_same_partenaire = 2
        rc.new_runner("Alice").set_options(max_same_partenaire=1).add_relay("R15").add_relay("R15")
        rc.new_runner("Bob").add_relay("R15").add_relay("R15")
        rc.new_runner("Carol").add_relay("R15", nb=2)
        status, solver, m = self._solve(rc)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        n = sum(solver.value(bv) for (r1,_,r2,_), bv in m.same_relay.items()
                if {r1, r2} == {"Alice", "Bob"})
        assert n <= 1


# ---------------------------------------------------------------------------
# add_min_score / add_optimisation_func
# ---------------------------------------------------------------------------

class TestObjective:
    def test_add_optimisation_func_does_not_raise(self, c2):
        m = build_model(c2)
        m.add_optimisation_func(c2)

    def test_add_min_score_feasible(self, c2):
        m = build_model(c2)
        m.add_optimisation_func(c2)
        m.add_min_score(c2, "compat_et_flex", 0)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 10
        status = solver.solve(m.model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def test_add_min_score_infeasible_if_too_high(self, c_incompatible):
        """Score min > 0 impossible avec 2 coureurs incompatibles."""
        m = build_model(c_incompatible)
        m.add_min_score(c_incompatible, "compat_et_flex", 1)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5
        status = solver.solve(m.model)
        assert status in (cp_model.INFEASIBLE, cp_model.MODEL_INVALID)


# ---------------------------------------------------------------------------
# Régression : no-overlap avec relais flex entre coureurs compatibles
# ---------------------------------------------------------------------------

class TestNoOverlapFlex:
    """Régression : deux coureurs compatibles avec relais flex ne doivent pas se
    chevaucher quand ils ne forment pas de binôme.

    Bug : le no-overlap conditionnel (~b) utilisait min(size_domain) comme
    séparation minimale. Pour un relais R15_F (domaine {10..15}), lo=10 segs.
    Si la taille résolue était 15, la condition diff <= -10 permettait un
    chevauchement de 5 segments (diff=-10 satisfait alors que la taille réelle
    exige diff <= -15).
    """

    def _solve(self, rc, timeout=10):
        m = build_model(rc)
        m.add_optimisation_func(rc)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = timeout
        status = solver.solve(m.model)
        return status, solver, m

    def _check_no_overlap(self, solver, m, r1, r2):
        """Vérifie qu'aucun relais de r1 ne chevauche un relais de r2."""
        for k1 in range(len(m.start[r1])):
            s1 = solver.value(m.start[r1][k1])
            e1 = solver.value(m.end[r1][k1])
            for k2 in range(len(m.start[r2])):
                key = (r1, k1, r2, k2)
                key_rev = (r2, k2, r1, k1)
                bv = m.same_relay.get(key) if key in m.same_relay else m.same_relay.get(key_rev)
                if bv is not None and solver.value(bv) == 1:
                    continue  # binôme : chevauchement autorisé
                s2 = solver.value(m.start[r2][k2])
                e2 = solver.value(m.end[r2][k2])
                assert e1 <= s2 or e2 <= s1, (
                    f"Chevauchement : {r1}[{k1}]=[{s1},{e1}[ et {r2}[{k2}]=[{s2},{e2}["
                )

    def test_flex_no_overlap_when_binome_forced_zero(self):
        """Régression directe : add_max_binomes(alice, bob, nb=0) interdit le binôme.
        Les relais flex résolus à taille maximale ne doivent pas se chevaucher.

        Couverture : Alice 1×R15_F(15) + Bob 1×R15_F(15) + Carol 4×R15(15) = 90 segs.
        NB=90, seg_km=1 → R15_F résolu à max(domaine)=15 segs en solo.
        """
        rc = _make_rc(
            compat_matrix={("Alice", "Bob"): 2, ("Alice", "Carol"): 0, ("Bob", "Carol"): 0},
        )
        alice = rc.new_runner("Alice").add_relay("R15_F")
        bob = rc.new_runner("Bob").add_relay("R15_F")
        rc.new_runner("Carol").add_relay("R15", nb=4)
        rc.add_max_binomes(alice, bob, nb=0)

        status, solver, m = self._solve(rc)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        self._check_no_overlap(solver, m, "Alice", "Bob")
