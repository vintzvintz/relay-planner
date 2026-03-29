"""Tests de Constraints : new_runner, add_relay, new_relay."""

import math
import pytest
from relay.constraints import Constraints, Intervals, SharedLeg


# ---------------------------------------------------------------------------
# Paramètres de base
# ---------------------------------------------------------------------------

class TestInit:
    def test_segment_km(self, c):
        assert c.segment_km == pytest.approx(10.0)

    def test_segment_duration(self, c):
        # 10 km / 10 km/h = 1h par segment
        assert c.segment_duration == pytest.approx(1.0)

    def test_solo_max_size(self, c):
        # solo_max_km=15 → 15/100 * 10 = 1.5 → int(1.5) = 1
        assert c.solo_max_size == 1

    def test_repos_jour_segs(self, c):
        assert c.repos_jour_default == 7

    def test_repos_nuit_segs(self, c):
        assert c.repos_nuit_default == 9


# ---------------------------------------------------------------------------
# new_runner : structure du Coureur créé
# ---------------------------------------------------------------------------

class TestNewRunner:
    def test_runner_registered(self, c):
        c.new_runner("Alice").add_relay("R10")
        assert "Alice" in c.runners_data

    def test_runner_appears_in_runners(self, c):
        c.new_runner("Alice").add_relay("R10")
        assert "Alice" in c.runners

    def test_default_overrides_are_none(self, c):
        c.new_runner("Alice").add_relay("R10")
        coureur = c.runners_data["Alice"]
        assert coureur.solo_max is None
        assert coureur.nuit_max is None
        assert coureur.repos_jour is None
        assert coureur.repos_nuit is None

    def test_solo_max_override(self, c):
        c.new_runner("Alice").set_options(solo_max=0).add_relay("R10")
        assert c.runners_data["Alice"].solo_max == 0
        assert c.runner_solo_max["Alice"] == 0

    def test_nuit_max_override(self, c):
        c.new_runner("Alice").set_options(nuit_max=3).add_relay("R10")
        assert c.runner_nuit_max["Alice"] == 3

    def test_repos_jour_override_converted_to_segs(self, c):
        # 3.5h * 10/100 * 10 = 3.5 → ceil = 4 segments
        c.new_runner("Alice").set_options(repos_jour=3.5).add_relay("R10")
        assert c.runner_repos_jour["Alice"] == 4

    def test_repos_nuit_override_converted_to_segs(self, c):
        c.new_runner("Alice").set_options(repos_nuit=5.0).add_relay("R10")
        assert c.runner_repos_nuit["Alice"] == 5

    def test_default_repos_jour_when_no_override(self, c):
        c.new_runner("Alice").add_relay("R10")
        assert c.runner_repos_jour["Alice"] == c.repos_jour_default

    def test_default_repos_nuit_when_no_override(self, c):
        c.new_runner("Alice").add_relay("R10")
        assert c.runner_repos_nuit["Alice"] == c.repos_nuit_default

    def test_multiple_runners_independent(self, c):
        c.new_runner("Alice").add_relay("R10")
        c.new_runner("Bob").add_relay("R15")
        assert set(c.runners) == {"Alice", "Bob"}


# ---------------------------------------------------------------------------
# add_relay : RelaySpec enregistrées dans le Coureur
# ---------------------------------------------------------------------------

class TestAddRelay:
    def test_single_relay(self, c):
        c.new_runner("Alice").add_relay("R30")
        assert len(c.runners_data["Alice"].relais) == 1
        assert c.runners_data["Alice"].relais[0].size == c.relay_types["R30"]

    def test_nb_relay(self, c):
        c.new_runner("Alice").add_relay("R10", nb=4)
        assert len(c.runners_data["Alice"].relais) == 4

    def test_multiple_add_relay_calls(self, c):
        c.new_runner("Alice").add_relay("R30").add_relay("R15", nb=2)
        assert len(c.runners_data["Alice"].relais) == 3
        assert c.runners_data["Alice"].relais[0].size == c.relay_types["R30"]
        assert c.runners_data["Alice"].relais[1].size == c.relay_types["R15"]

    def test_relay_sizes_property(self, c):
        c.new_runner("Alice").add_relay("R10").add_relay("R15")
        r10_max = max(c.relay_types["R10"])
        r15_max = max(c.relay_types["R15"])
        assert c.relay_sizes["Alice"] == [r10_max, r15_max]

    def test_flex_relay_nominal_size_is_max(self, c):
        c.new_runner("Alice").add_relay("R15_F")
        assert c.relay_sizes["Alice"] == [max(c.relay_types["R15_F"])]

    def test_pinned_relay(self, c):
        c.new_runner("Alice").add_relay("R10", pinned=2)
        spec = c.runners_data["Alice"].relais[0]
        assert spec.pinned == 2

    def test_no_pinned_by_default(self, c):
        c.new_runner("Alice").add_relay("R10")
        assert c.runners_data["Alice"].relais[0].pinned is None

    def test_window_tuple(self, c):
        c.new_runner("Alice").add_relay("R10", window=(0, 5))
        spec = c.runners_data["Alice"].relais[0]
        assert spec.window == [(0, 5)]

    def test_window_relay_intervals(self, c):
        w = Intervals([(0, 3), (7, 9)])
        c.new_runner("Alice").add_relay("R10", window=w)
        spec = c.runners_data["Alice"].relais[0]
        assert spec.window == [(0, 3), (7, 9)]

    def test_no_window_by_default(self, c):
        c.new_runner("Alice").add_relay("R10")
        assert c.runners_data["Alice"].relais[0].window is None

    def test_nb_gt1_with_shared_relay_raises(self, c):
        shared = c.new_relay("R10")
        with pytest.raises(ValueError):
            c.new_runner("Alice").add_relay(shared, nb=2)

    def test_invalid_type_raises(self, c):
        with pytest.raises(TypeError):
            c.new_runner("Alice").add_relay({3})


# ---------------------------------------------------------------------------
# new_relay / SharedLeg : pairing entre coureurs
# ---------------------------------------------------------------------------

class TestSharedRelay:
    def test_shared_relay_creates_pairing(self, c):
        shared = c.new_relay("R10")
        c.new_runner("Alice").add_relay(shared)
        c.new_runner("Bob").add_relay(shared)

        alice_spec = c.runners_data["Alice"].relais[0]
        bob_spec = c.runners_data["Bob"].relais[0]

        assert alice_spec.paired_with == ("Bob", 0)
        assert bob_spec.paired_with == ("Alice", 0)

    def test_shared_relay_size_propagated(self, c):
        shared = c.new_relay("R30")
        c.new_runner("Alice").add_relay(shared)
        c.new_runner("Bob").add_relay(shared)
        assert c.runners_data["Alice"].relais[0].size == c.relay_types["R30"]
        assert c.runners_data["Bob"].relais[0].size == c.relay_types["R30"]

    def test_paired_relays_property(self, c):
        shared = c.new_relay("R10")
        c.new_runner("Alice").add_relay(shared)
        c.new_runner("Bob").add_relay(shared)
        pairs = c.paired_relays
        assert len(pairs) == 1
        assert set(pairs[0]) == {"Alice", 0, "Bob", 0}

    def test_two_shared_relays_two_pairs(self, c):
        s1 = c.new_relay("R10")
        s2 = c.new_relay("R15")
        c.new_runner("Alice").add_relay(s1).add_relay(s2)
        c.new_runner("Bob").add_relay(s1).add_relay(s2)
        assert len(c.paired_relays) == 2

    def test_shared_relay_third_runner_raises(self, c):
        shared = c.new_relay("R10")
        c.new_runner("Alice").add_relay(shared)
        c.new_runner("Bob").add_relay(shared)
        with pytest.raises(ValueError):
            c.new_runner("Carol").add_relay(shared)

    def test_unpaired_relay_has_no_paired_with(self, c):
        c.new_runner("Alice").add_relay("R10")
        assert c.runners_data["Alice"].relais[0].paired_with is None


# ---------------------------------------------------------------------------
# add_max_binomes / once_max
# ---------------------------------------------------------------------------

class TestAddMaxBinomes:
    def test_once_max_initially_empty(self, c):
        assert c.once_max == []

    def test_add_max_binomes_enregistre(self, c):
        alice = c.new_runner("Alice").add_relay("R10")
        bob = c.new_runner("Bob").add_relay("R10")
        c.add_max_binomes(alice, bob, nb=1)
        assert len(c.once_max) == 1

    def test_add_max_binomes_valeurs(self, c):
        alice = c.new_runner("Alice").add_relay("R10")
        bob = c.new_runner("Bob").add_relay("R10")
        c.add_max_binomes(alice, bob, nb=2)
        r1, r2, nb = c.once_max[0]
        assert r1 == "Alice"
        assert r2 == "Bob"
        assert nb == 2

    def test_add_max_binomes_multiple(self, c):
        alice = c.new_runner("Alice").add_relay("R10")
        bob = c.new_runner("Bob").add_relay("R10")
        carol = c.new_runner("Carol").add_relay("R10")
        c.add_max_binomes(alice, bob, nb=1)
        c.add_max_binomes(alice, carol, nb=2)
        assert len(c.once_max) == 2
        assert c.once_max[1] == ("Alice", "Carol", 2)


# ---------------------------------------------------------------------------
# set_options(max_same_partenaire=) / max_same_partenaire
# ---------------------------------------------------------------------------

class TestMaxSamePartenaire:
    def test_global_max_same_partenaire_none_by_default(self, c):
        assert c.max_same_partenaire is None

    def test_global_max_same_partenaire_set(self):
        rc = Constraints(
            total_km=100.0, nb_segments=10, speed_kmh=10.0, start_hour=15.0,
            compat_matrix={}, solo_max_km=15.0, solo_max_default=2,
            nuit_max_default=1, repos_jour_heures=7.0, repos_nuit_heures=9.0,
            nuit_debut=0.0, nuit_fin=6.0, max_same_partenaire=3,
        )
        assert rc.max_same_partenaire == 3

    def test_coureur_max_same_partenaire_none_by_default(self, c):
        c.new_runner("Alice").add_relay("R10")
        assert c.runners_data["Alice"].max_same_partenaire is None

    def test_set_max_same_partenaire_stores_value(self, c):
        c.new_runner("Alice").set_options(max_same_partenaire=2).add_relay("R10")
        assert c.runners_data["Alice"].max_same_partenaire == 2

    def test_set_options_is_chainable(self, c):
        builder = c.new_runner("Alice")
        result = builder.set_options(max_same_partenaire=1)
        assert result is builder

    def test_set_max_same_partenaire_independent_per_runner(self, c):
        c.new_runner("Alice").set_options(max_same_partenaire=1).add_relay("R10")
        c.new_runner("Bob").add_relay("R10")
        assert c.runners_data["Alice"].max_same_partenaire == 1
        assert c.runners_data["Bob"].max_same_partenaire is None


# ---------------------------------------------------------------------------
# Compatibilité
# ---------------------------------------------------------------------------

class TestCompat:
    def test_compatible_pair(self, c):
        assert c.is_compatible("Alice", "Bob") is True

    def test_compatible_score(self, c):
        assert c.compat_score("Alice", "Bob") == 2

    def test_incompatible_pair(self, c):
        assert c.is_compatible("Alice", "Dave") is False

    def test_compat_score_missing_pair(self, c):
        assert c.compat_score("Alice", "Dave") == 0


# ---------------------------------------------------------------------------
# Segments utilitaires
# ---------------------------------------------------------------------------

class TestSegmentUtils:
    def test_segment_start_hour(self, c):
        # départ 15h, 1h/seg → seg 2 démarre à 17h
        assert c.segment_start_hour(2) == pytest.approx(17.0)

    def test_is_night_false_at_15h(self, c):
        assert c.is_night(0) is False  # seg 0 → 15h

    def test_is_night_true_at_2h(self, c):
        # seg 11 → 15+11=26 → 2h du matin → nuit
        assert c.is_night(11) is True

    def test_duration_to_segs_rounds_up(self, c):
        # 1.1h * 10/100 * 10 = 1.1 → ceil = 2
        assert c.duration_to_segs(1.1) == 2

    def test_duration_to_segs_exact(self, c):
        assert c.duration_to_segs(1.0) == 1

    def test_hour_to_seg(self, c):
        # heure 17h jour 0 → 2h depuis départ → seg 2
        assert c.hour_to_seg(17.0) == 2

    def test_hour_to_seg_with_jour(self, c):
        # heure 3h jour 1 → (24 + 3 - 15) = 12h depuis départ → seg 12
        assert c.hour_to_seg(3.0, jour=1) == 12
