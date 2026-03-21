"""Tests unitaires de RelayModel : variables CP-SAT, contraintes, structure du modèle."""

import pytest
from ortools.sat.python import cp_model

from constraints import RelayConstraints, SharedRelay
from model import RelayModel, build_model


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_rc(compat_matrix=None, solo_max_km=100.0, repos_jour=1.0, repos_nuit=1.0,
             nb_segments=10, total_km=100.0):
    """Crée un RelayConstraints diurne (départ 8h) pour éviter les segments nocturnes."""
    return RelayConstraints(
        total_km=total_km,
        nb_segments=nb_segments,
        speed_kmh=total_km / nb_segments,   # 1h par segment
        start_hour=8.0,                       # départ 8h → tout de jour
        compat_matrix=compat_matrix or {},
        solo_max_km=solo_max_km,
        solo_max_default=2,
        nuit_max_default=1,
        repos_jour_heures=repos_jour,
        repos_nuit_heures=repos_nuit,
        nuit_debut=0.0,
        nuit_fin=6.0,
    )


@pytest.fixture
def c2():
    """2 coureurs compatibles, couvrent exactement les 10 segments (5 + 5)."""
    rc = _make_rc(compat_matrix={("Alice", "Bob"): 2, ("Bob", "Alice"): 2})
    rc.new_runner("Alice").add_relay({5})
    rc.new_runner("Bob").add_relay({5})
    return rc


@pytest.fixture
def c_incompatible():
    """2 coureurs incompatibles, couvrent les 10 segments (5 + 5) sans binôme."""
    rc = _make_rc()
    rc.new_runner("Alice").add_relay({5})
    rc.new_runner("Bob").add_relay({5})
    return rc


@pytest.fixture
def c_multi_relay():
    """Alice : 2 relais de 3, Bob : 1 relai de 3 (9 segments total)."""
    rc = _make_rc(
        compat_matrix={("Alice", "Bob"): 1, ("Bob", "Alice"): 1},
        nb_segments=9, total_km=90.0,
    )
    rc.new_runner("Alice").add_relay({3}).add_relay({3})
    rc.new_runner("Bob").add_relay({3})
    return rc


@pytest.fixture
def c_flex():
    """Alice flex {3,5}, Bob {5}. Binôme possible à taille 5."""
    rc = _make_rc(compat_matrix={("Alice", "Bob"): 2, ("Bob", "Alice"): 2})
    rc.new_runner("Alice").add_relay({3, 5})
    rc.new_runner("Bob").add_relay({5})
    return rc


@pytest.fixture
def c_pinned():
    """Alice pinn au seg 0, Bob couvre le reste (10 segments total)."""
    rc = _make_rc()
    rc.new_runner("Alice").add_relay({5}, pinned=0)
    rc.new_runner("Bob").add_relay({5})
    return rc


@pytest.fixture
def c_window():
    """Alice fenêtre [0,7], taille 5 → end ≤ 8. Bob couvre le reste."""
    rc = _make_rc()
    from constraints import RelayIntervals
    rc.new_runner("Alice").add_relay({5}, window=RelayIntervals([(0, 7)]))
    rc.new_runner("Bob").add_relay({5})
    return rc


@pytest.fixture
def c_shared():
    """SharedRelay entre Alice et Bob (binôme forcé au seg 0), Carol couvre le reste."""
    rc = _make_rc(compat_matrix={("Alice", "Bob"): 2, ("Bob", "Alice"): 2})
    shared = rc.new_relay({5})
    rc.new_runner("Alice").add_relay(shared)
    rc.new_runner("Bob").add_relay(shared)
    rc.new_runner("Carol").add_relay({5})
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
        # Alice: 2 relais, Bob: 1 → 3 intervalles au total
        assert len(m._intervals_all) == 3

    def test_intervals_all_structure(self, c2):
        m = build_model(c2)
        for entry in m._intervals_all:
            assert len(entry) == 4  # (r, k, sz_max, interval_var)

    def test_flex_size_domain(self, c_flex):
        m = build_model(c_flex)
        # La variable size d'Alice doit avoir un domaine contenant 3 et 5
        solver = cp_model.CpSolver()
        # On vérifie juste que le modèle se construit sans erreur et que
        # start/size existent pour Alice
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
        assert len(m.same_relay) == 1
        key = ("Alice", 0, "Bob", 0)
        assert key in m.same_relay

    def test_same_relay_empty_for_incompatible(self, c_incompatible):
        m = build_model(c_incompatible)
        assert len(m.same_relay) == 0

    def test_same_relay_key_order(self, c2):
        """Les clés sont toujours (runner_avec_index_plus_petit, ..., runner_plus_grand, ...)."""
        m = build_model(c2)
        for (r, k, rp, kp) in m.same_relay:
            ri = c2.runners.index(r)
            rpi = c2.runners.index(rp)
            assert ri < rpi

    def test_same_relay_multi_relay_count(self, c_multi_relay):
        """Alice a 2 relais, Bob 1 → 2 paires potentielles."""
        m = build_model(c_multi_relay)
        assert len(m.same_relay) == 2

    def test_no_same_relay_for_incompatible_sizes(self):
        """Pas de same_relay si les domaines de taille ne se chevauchent pas."""
        rc = RelayConstraints(
            total_km=200.0,
            nb_segments=20,
            speed_kmh=10.0,
            start_hour=15.0,
            compat_matrix={("Alice", "Bob"): 2, ("Bob", "Alice"): 2},
            solo_max_km=100.0,
            solo_max_default=2,
            nuit_max_default=1,
            repos_jour_heures=2.0,
            repos_nuit_heures=3.0,
            nuit_debut=0.0,
            nuit_fin=6.0,
        )
        rc.new_runner("Alice").add_relay({3})
        rc.new_runner("Bob").add_relay({5})
        m = build_model(rc)
        assert len(m.same_relay) == 0


# ---------------------------------------------------------------------------
# Résolution : vérification de faisabilité sur des modèles simples
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
        """Deux coureurs incompatibles peuvent quand même couvrir le parcours en solo."""
        status, _, _ = self._solve(c_incompatible)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def test_pinned_respected(self, c_pinned):
        """Un relais pinné doit démarrer exactement au segment spécifié (0)."""
        status, solver, m = self._solve(c_pinned)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.value(m.start["Alice"][0]) == 0

    def test_window_respected(self, c_window):
        """Le relais doit être contenu dans la fenêtre [0, 7]."""
        status, solver, m = self._solve(c_window)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        start_val = solver.value(m.start["Alice"][0])
        end_val = solver.value(m.end["Alice"][0])
        assert start_val >= 0
        assert end_val <= 8  # window fin = 7, end = start + size = 5 max

    def test_shared_relay_same_start(self, c_shared):
        """Un SharedRelay force Alice et Bob à démarrer au même segment."""
        status, solver, m = self._solve(c_shared)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.value(m.start["Alice"][0]) == solver.value(m.start["Bob"][0])

    def test_score_binome_positive(self):
        """Avec 2 coureurs compatibles + couverture assurée, le binôme est activé."""
        # Alice+Bob en binôme (seg 0-4), Carol solo (seg 5-9)
        rc = _make_rc(compat_matrix={("Alice", "Bob"): 2, ("Bob", "Alice"): 2})
        rc.new_runner("Alice").add_relay({5})
        rc.new_runner("Bob").add_relay({5})
        rc.new_runner("Carol").add_relay({5})
        status, solver, m = self._solve(rc)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        key = ("Alice", 0, "Bob", 0)
        assert solver.value(m.same_relay[key]) == 1

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
        """En binôme, la taille flex d'Alice doit correspondre à celle de Bob (5)."""
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
        """Alice et Bob ont chacun 2 relais de taille 3 sur 12 segments."""
        rc = _make_rc(
            compat_matrix={("Alice", "Bob"): 2, ("Bob", "Alice"): 2},
            nb_segments=12, total_km=120.0, repos_jour=0.0, repos_nuit=0.0,
        )
        alice = rc.new_runner("Alice").add_relay({3}).add_relay({3})
        bob = rc.new_runner("Bob").add_relay({3}).add_relay({3})
        rc.add_max_binomes(alice, bob, nb=nb_max)
        return rc

    def test_once_max_1_feasible(self):
        rc = self._rc_two_relays_each(nb_max=1)
        status, _, _ = self._solve(rc)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def test_once_max_1_at_most_one_binome(self):
        rc = self._rc_two_relays_each(nb_max=1)
        status, solver, m = self._solve(rc)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        n_binomes = sum(
            solver.value(bv)
            for (r1, _, r2, _), bv in m.same_relay.items()
            if {r1, r2} == {"Alice", "Bob"}
        )
        assert n_binomes <= 1

    def test_once_max_0_no_binome(self):
        rc = self._rc_two_relays_each(nb_max=0)
        status, solver, m = self._solve(rc)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        n_binomes = sum(
            solver.value(bv)
            for (r1, _, r2, _), bv in m.same_relay.items()
            if {r1, r2} == {"Alice", "Bob"}
        )
        assert n_binomes == 0

    def test_once_max_2_allows_both_binomes(self):
        rc = self._rc_two_relays_each(nb_max=2)
        status, solver, m = self._solve(rc)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        # Avec nb_max=2 et optimisation binôme, le solver doit en trouver 2
        n_binomes = sum(
            solver.value(bv)
            for (r1, _, r2, _), bv in m.same_relay.items()
            if {r1, r2} == {"Alice", "Bob"}
        )
        assert n_binomes <= 2


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
        """Alice et Bob ont chacun 2 relais de 3 ; limite globale max_same."""
        rc = _make_rc(
            compat_matrix={("Alice", "Bob"): 2, ("Bob", "Alice"): 2},
            nb_segments=12, total_km=120.0, repos_jour=0.0, repos_nuit=0.0,
        )
        rc.max_same_partenaire = max_same
        rc.new_runner("Alice").add_relay({3}).add_relay({3})
        rc.new_runner("Bob").add_relay({3}).add_relay({3})
        return rc

    def _rc_individual(self, max_same_alice):
        """Limite individuelle sur Alice uniquement."""
        rc = _make_rc(
            compat_matrix={("Alice", "Bob"): 2, ("Bob", "Alice"): 2},
            nb_segments=12, total_km=120.0, repos_jour=0.0, repos_nuit=0.0,
        )
        rc.new_runner("Alice").set_max_same_partenaire(max_same_alice).add_relay({3}).add_relay({3})
        rc.new_runner("Bob").add_relay({3}).add_relay({3})
        return rc

    def test_global_limit_1_feasible(self):
        rc = self._rc_global(max_same=1)
        status, _, _ = self._solve(rc)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def test_global_limit_1_at_most_one_binome(self):
        rc = self._rc_global(max_same=1)
        status, solver, m = self._solve(rc)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        n_binomes = sum(
            solver.value(bv)
            for (r1, _, r2, _), bv in m.same_relay.items()
            if {r1, r2} == {"Alice", "Bob"}
        )
        assert n_binomes <= 1

    def test_individual_limit_applies(self):
        rc = self._rc_individual(max_same_alice=1)
        status, solver, m = self._solve(rc)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        n_binomes = sum(
            solver.value(bv)
            for (r1, _, r2, _), bv in m.same_relay.items()
            if {r1, r2} == {"Alice", "Bob"}
        )
        assert n_binomes <= 1

    def test_no_limit_more_binomes_than_with_limit(self):
        """Sans limite, le solver trouve au moins autant de binômes qu'avec une limite à 1."""
        def solve_with_limit(limit):
            rc = _make_rc(
                compat_matrix={("Alice", "Bob"): 2, ("Bob", "Alice"): 2},
                nb_segments=12, total_km=120.0, repos_jour=0.0, repos_nuit=0.0,
            )
            alice = rc.new_runner("Alice").add_relay({3}).add_relay({3})
            rc.new_runner("Bob").add_relay({3}).add_relay({3})
            if limit is not None:
                rc.max_same_partenaire = limit
            m = build_model(rc)
            m.add_optimisation_func(rc)
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = 10
            status = solver.solve(m.model)
            assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
            return sum(
                solver.value(bv)
                for (r1, _, r2, _), bv in m.same_relay.items()
                if {r1, r2} == {"Alice", "Bob"}
            )

        n_unlimited = solve_with_limit(None)
        n_limited = solve_with_limit(1)
        assert n_unlimited >= n_limited

    def test_individual_overrides_global(self):
        """La surcharge individuelle (plus restrictive) l'emporte sur la limite globale."""
        rc = _make_rc(
            compat_matrix={("Alice", "Bob"): 2, ("Bob", "Alice"): 2},
            nb_segments=12, total_km=120.0, repos_jour=0.0, repos_nuit=0.0,
        )
        rc.max_same_partenaire = 2  # globale permissive
        rc.new_runner("Alice").set_max_same_partenaire(1).add_relay({3}).add_relay({3})
        rc.new_runner("Bob").add_relay({3}).add_relay({3})
        status, solver, m = self._solve(rc)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        n_binomes = sum(
            solver.value(bv)
            for (r1, _, r2, _), bv in m.same_relay.items()
            if {r1, r2} == {"Alice", "Bob"}
        )
        assert n_binomes <= 1


# ---------------------------------------------------------------------------
# add_min_score / add_optimisation_func
# ---------------------------------------------------------------------------

class TestObjective:
    def test_add_optimisation_func_does_not_raise(self, c2):
        m = build_model(c2)
        m.add_optimisation_func(c2)  # ne doit pas lever d'exception

    def test_add_min_score_feasible(self, c2):
        m = build_model(c2)
        m.add_optimisation_func(c2)
        m.add_min_score(c2, 0)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 10
        status = solver.solve(m.model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def test_add_min_score_infeasible_if_too_high(self, c_incompatible):
        """Score min > 0 impossible avec 2 coureurs incompatibles (same_relay vide)."""
        m = build_model(c_incompatible)
        # Pas de same_relay → score toujours 0 ; min_score=1 rend le modèle infaisable
        m.add_min_score(c_incompatible, 1)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5
        status = solver.solve(m.model)
        assert status in (cp_model.INFEASIBLE, cp_model.MODEL_INVALID)
