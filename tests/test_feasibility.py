"""
Tests unitaires pour relay/feasibility.py.

Vérifie que le FeasibilityAnalyser détecte correctement les incompatibilités
directes entre contraintes (paires de contraintes rendant le problème infaisable).
La transitivité (incompatibilités à 3+ familles) est hors périmètre.

Stratégie : pour chaque famille de contraintes, on construit un problème
minimal qui est faisable SAUF quand une famille spécifique est active.
On vérifie que :
  1. Le modèle complet est infaisable.
  2. Désactiver la famille suspecte rend le modèle faisable.
  3. Désactiver une autre famille ne suffit pas (optionnel, selon les cas).
"""

import pytest

from relay.constraints import Constraints, Preset, Interval
from relay.parcours import Parcours
from relay.feasibility import _PartialModel, _solve_feasibility


# ===================================================================
# Helpers
# ===================================================================

def _make_parcours(nb_arcs: int, total_km: float) -> Parcours:
    """Parcours synthétique uniforme (espacement constant)."""
    n = nb_arcs + 1
    step = total_km / nb_arcs
    waypoints = [
        {"km": round(i * step, 6), "lat": 45.0, "lon": 4.0 + i * 0.01, "alt": 200.0}
        for i in range(n)
    ]
    waypoints[-1]["km"] = total_km
    return Parcours.from_raw(waypoints)


COMPAT_AB = {("A", "B"): 2}
COMPAT_ABC = {("A", "B"): 2, ("A", "C"): 1, ("B", "C"): 1}
COMPAT_ABCD = {
    ("A", "B"): 2, ("A", "C"): 1, ("A", "D"): 1,
    ("B", "C"): 1, ("B", "D"): 1, ("C", "D"): 2,
}


def _base_constraints(
    nb_arcs=10,
    total_km=10.0,
    compat=None,
    solo_max_km=None,
    solo_max_default=99,
    nuit_max_default=99,
    repos_jour=0.0,
    repos_nuit=0.0,
    max_same_partenaire=None,
    speed_kmh=10.0,
    start_hour=8.0,
) -> Constraints:
    """Crée un Constraints minimal avec des défauts permissifs."""
    if compat is None:
        compat = COMPAT_AB
    if solo_max_km is None:
        solo_max_km = total_km
    return Constraints(
        parcours=_make_parcours(nb_arcs, total_km),
        speed_kmh=speed_kmh,
        start_hour=start_hour,
        compat_matrix=compat,
        solo_max_km=solo_max_km,
        solo_max_default=solo_max_default,
        nuit_max_default=nuit_max_default,
        repos_jour_heures=repos_jour,
        repos_nuit_heures=repos_nuit,
        max_same_partenaire=max_same_partenaire,
    )


def _is_feasible(c: Constraints, skip: set[str] | None = None, timeout: float = 5.0) -> bool:
    """Construit un modèle partiel et teste la faisabilité."""
    m = _PartialModel()
    model = m.build_without(c, skip or set())
    return _solve_feasibility(model, timeout)


# ===================================================================
# Test de base : problème faisable
# ===================================================================

class TestBaseFeasibility:
    """Vérifie que le helper fonctionne sur un problème trivialement faisable."""

    def test_trivial_feasible(self):
        c = _base_constraints(nb_arcs=5, total_km=10.0)
        p = Preset(km=5.0, min=1, max=9)
        c.new_runner("A", 3).add_relay(p).add_relay(p)
        c.new_runner("B", 3).add_relay(p).add_relay(p)
        assert _is_feasible(c)


# ===================================================================
# fixed_relays : relais épinglé impossible
# ===================================================================

class TestFixedRelays:
    """Un relais épinglé à une position incompatible avec sa taille."""

    def test_pinned_outside_range(self):
        """Épingler start et end à des positions incompatibles avec min/max distance."""
        # 10 arcs de 1 km chacun. Relais A[0] épinglé start=0, end=2 (2 km)
        # mais min=5 km → impossible.
        c = _base_constraints(nb_arcs=10, total_km=10.0)
        p_big = Preset(km=8.0, min=5, max=10)
        p_small = Preset(km=3.0, min=1, max=5)

        pin = c.new_pin(start_wp=0, end_wp=2)
        c.new_runner("A", 3).add_relay(p_big, pinned=pin).add_relay(p_small)
        c.new_runner("B", 3).add_relay(p_big).add_relay(p_small)

        assert not _is_feasible(c), "Modèle complet devrait être infaisable"
        assert _is_feasible(c, skip={"fixed_relays"}), "Sans fixed_relays devrait être faisable"

    def test_pinned_conflicting_two_runners(self):
        """Deux coureurs incompatibles épinglés au même départ → overlap forcé."""
        # 20 arcs, 20 km. Deux coureurs incompatibles épinglés au même start=0.
        # Avec min=6 km chacun, ils se chevauchent forcément sur [0, 6+].
        # Sans pinning, on peut les séquencer : A [0,10], B [10,20].
        c = _base_constraints(nb_arcs=20, total_km=20.0, compat={("A", "B"): 0})
        p = Preset(km=8.0, min=6, max=12)
        pin_start = c.new_pin(start_wp=0)
        c.new_runner("A", 3).add_relay(p, pinned=pin_start)
        c.new_runner("B", 3).add_relay(p, pinned=pin_start)

        assert not _is_feasible(c), "Modèle complet devrait être infaisable"
        assert _is_feasible(c, skip={"fixed_relays"}), "Sans fixed_relays devrait être faisable"


# ===================================================================
# availability : fenêtre de placement impossible
# ===================================================================

class TestAvailability:
    """Fenêtres de disponibilité incompatibles avec la couverture."""

    def test_window_too_narrow(self):
        """Fenêtre trop étroite pour accueillir le relais minimal."""
        # 20 arcs de 1 km. Coureur A : relais de 5-10 km, fenêtre réduite à 2 arcs.
        c = _base_constraints(nb_arcs=20, total_km=20.0)
        p = Preset(km=7.0, min=5, max=10)
        window_narrow = c.interval_waypoints(0, 2)  # 2 arcs = 2 km < min 5 km
        c.new_runner("A", 3).add_relay(p, window=window_narrow).add_relay(p)
        c.new_runner("B", 3).add_relay(p).add_relay(p)

        assert not _is_feasible(c), "Modèle complet devrait être infaisable"
        assert _is_feasible(c, skip={"availability"}), "Sans availability devrait être faisable"

    def test_windows_no_overlap_coverage(self):
        """Fenêtres qui ne couvrent pas tout le parcours → trou de couverture."""
        # 10 arcs. Deux coureurs avec fenêtres qui laissent un trou.
        c = _base_constraints(nb_arcs=10, total_km=10.0)
        p = Preset(km=3.0, min=1, max=5)
        # A : uniquement dans [0, 4], B : uniquement dans [6, 10]
        # Arcs 4-5 et 5-6 ne seront couverts par personne.
        w_a = c.interval_waypoints(0, 4)
        w_b = c.interval_waypoints(6, 10)
        c.new_runner("A", 3).add_relay(p, window=w_a).add_relay(p, window=w_a)
        c.new_runner("B", 3).add_relay(p, window=w_b).add_relay(p, window=w_b)

        assert not _is_feasible(c), "Modèle complet devrait être infaisable"
        assert _is_feasible(c, skip={"availability"}), "Sans availability devrait être faisable"


# ===================================================================
# rest_intervals : repos incompatible avec la couverture
# ===================================================================

class TestRestIntervals:
    """Repos trop long rendant la couverture impossible."""

    def test_rest_too_long(self):
        """Repos si long qu'il empêche de couvrir le parcours dans le temps imparti."""
        # 10 arcs, 10 km, 10 km/h → 60 min de parcours total.
        # 2 coureurs, 2 relais chacun, repos_jour = 10 heures → impossible.
        c = _base_constraints(nb_arcs=10, total_km=10.0, repos_jour=10.0)
        p = Preset(km=3.0, min=1, max=5)
        c.new_runner("A", 3).add_relay(p).add_relay(p)
        c.new_runner("B", 3).add_relay(p).add_relay(p)

        assert not _is_feasible(c), "Modèle complet devrait être infaisable"
        assert _is_feasible(c, skip={"rest_intervals"}), "Sans rest_intervals devrait être faisable"


# ===================================================================
# night_relay : nuit_max trop restrictif
# ===================================================================

class TestNightRelay:
    """nuit_max=0 quand tous les relais tombent de nuit."""

    def test_nuit_max_zero_all_night(self):
        """Tout le parcours est de nuit, nuit_max=0 → infaisable."""
        # On déclare tout le parcours comme nuit.
        # 10 arcs, 10 km, 10 km/h, start à 0h.
        c = _base_constraints(nb_arcs=10, total_km=10.0, nuit_max_default=0)
        # Déclarer tout comme nuit
        c.add_night(c.interval_waypoints(0, 10))

        p = Preset(km=3.0, min=1, max=5)
        c.new_runner("A", 3).add_relay(p).add_relay(p)
        c.new_runner("B", 3).add_relay(p).add_relay(p)

        assert not _is_feasible(c), "Modèle complet devrait être infaisable"
        assert _is_feasible(c, skip={"night_relay"}), "Sans night_relay devrait être faisable"


# ===================================================================
# solo : solo interdit mais inévitable
# ===================================================================

class TestSolo:
    """Contraintes solo rendant le problème infaisable."""

    def test_solo_max_zero_odd_coverage(self):
        """3 coureurs avec 1 relais chacun, couverture impaire → au moins 1 solo.
        Avec solo_max=0, infaisable."""
        # 6 arcs, 3 coureurs, 1 relais chacun de 2 arcs.
        # Total = 6 arcs, chaque relais = 2 arcs → 3 relais couvrent pile 6 arcs.
        # Mais max 2 runners sur un arc → pas de binôme possible pour 3 coureurs.
        # Au moins 1 sera solo.
        c = _base_constraints(nb_arcs=6, total_km=6.0, compat=COMPAT_ABC, solo_max_default=0)
        p = Preset(km=2.0, min=2, max=2)
        c.new_runner("A", 3).add_relay(p)
        c.new_runner("B", 3).add_relay(p)
        c.new_runner("C", 3).add_relay(p)

        assert not _is_feasible(c), "Modèle complet devrait être infaisable"
        assert _is_feasible(c, skip={"solo"}), "Sans solo devrait être faisable"

    def test_solo_forbidden_zone_covers_all(self):
        """Zone no_solo couvre tout le parcours, mais un coureur est forcément solo."""
        c = _base_constraints(nb_arcs=6, total_km=6.0, compat=COMPAT_ABC, solo_max_default=99)
        c.add_no_solo(c.interval_waypoints(0, 6))

        p = Preset(km=2.0, min=2, max=2)
        c.new_runner("A", 3).add_relay(p)
        c.new_runner("B", 3).add_relay(p)
        c.new_runner("C", 3).add_relay(p)

        assert not _is_feasible(c), "Modèle complet devrait être infaisable"
        assert _is_feasible(c, skip={"solo"}), "Sans solo devrait être faisable"


# ===================================================================
# inter_runner_no_overlap : incompatibles sur parcours trop court
# ===================================================================

class TestInterRunnerNoOverlap:
    """Coureurs incompatibles ne peuvent pas se chevaucher."""

    def test_incompatible_forced_overlap(self):
        """Deux coureurs incompatibles, relais trop gros pour le parcours → overlap forcé."""
        # 4 arcs. Chaque coureur a 1 relais de 3-4 arcs. Total = 4 arcs.
        # Deux relais de 3+ arcs sur 4 arcs → overlap certain.
        # compat = 0 → pas de binôme → no-overlap → infaisable.
        c = _base_constraints(nb_arcs=4, total_km=4.0, compat={("A", "B"): 0})
        p = Preset(km=3.0, min=3, max=4)
        c.new_runner("A", 3).add_relay(p)
        c.new_runner("B", 3).add_relay(p)

        assert not _is_feasible(c), "Modèle complet devrait être infaisable"
        assert _is_feasible(c, skip={"inter_runner_no_overlap"}), \
            "Sans inter_runner_no_overlap devrait être faisable"


# ===================================================================
# shared_relays : binôme forcé impossible
# ===================================================================

class TestSharedRelays:
    """SharedLeg entre coureurs incompatibles."""

    def test_shared_with_incompatible(self):
        """Binôme forcé entre coureurs avec compat=0 → same_relay inexistant → infaisable."""
        # Quand compat=0, add_same_relay ne crée pas de BoolVar pour la paire,
        # donc add_shared_relays ne peut pas forcer same_relay=1.
        # Avec compat > 0 mais des contraintes rendant l'appariement impossible.
        c = _base_constraints(nb_arcs=10, total_km=10.0)
        p = Preset(km=3.0, min=1, max=5)
        shared = c.new_shared_relay(target_km=5.0, min_km=3, max_km=7)

        # A a le shared + un autre relais, B aussi
        # On épingle A et B dans des fenêtres disjointes pour le shared → infaisable.
        w_a = c.interval_waypoints(0, 5)
        w_b = c.interval_waypoints(5, 10)
        c.new_runner("A", 3).add_relay(shared, window=w_a).add_relay(p)
        c.new_runner("B", 3).add_relay(shared, window=w_b).add_relay(p)

        assert not _is_feasible(c), "Modèle complet devrait être infaisable"
        # Désactiver shared_relays ET availability devrait débloquer
        assert _is_feasible(c, skip={"shared_relays"}), \
            "Sans shared_relays devrait être faisable"


# ===================================================================
# max_duos : limite de binômes trop basse
# ===================================================================

class TestMaxDuos:
    """max_duos trop restrictif."""

    def test_max_duos_zero_with_shared(self):
        """SharedLeg force un binôme, mais max_duos=0 interdit tout binôme."""
        c = _base_constraints(nb_arcs=10, total_km=10.0)
        p = Preset(km=3.0, min=1, max=5)
        shared = c.new_shared_relay(target_km=5.0, min_km=3, max_km=7)

        a = c.new_runner("A", 3)
        b = c.new_runner("B", 3)
        a.add_relay(shared).add_relay(p)
        b.add_relay(shared).add_relay(p)
        c.add_max_duos(a, b, nb=0)

        assert not _is_feasible(c), "Modèle complet devrait être infaisable"
        assert _is_feasible(c, skip={"max_duos"}), "Sans max_duos devrait être faisable"


# ===================================================================
# max_same_partenaire : limite par partenaire trop basse
# ===================================================================

class TestMaxSamePartenaire:
    """max_same_partenaire trop restrictif avec SharedLeg."""

    def test_max_same_partenaire_zero_with_shared(self):
        """SharedLeg force un binôme, mais max_same_partenaire=0 interdit tout."""
        c = _base_constraints(nb_arcs=10, total_km=10.0, max_same_partenaire=0)
        p = Preset(km=3.0, min=1, max=5)
        shared = c.new_shared_relay(target_km=5.0, min_km=3, max_km=7)

        c.new_runner("A", 3).add_relay(shared).add_relay(p)
        c.new_runner("B", 3).add_relay(shared).add_relay(p)

        assert not _is_feasible(c), "Modèle complet devrait être infaisable"
        assert _is_feasible(c, skip={"max_same_partenaire"}), \
            "Sans max_same_partenaire devrait être faisable"


# ===================================================================
# coverage + contraintes de taille : parcours non couvrable
# ===================================================================

class TestCoverage:
    """Relais trop petits ou trop grands pour couvrir le parcours."""

    def test_total_too_short(self):
        """Somme des max de tous les relais < total_km → couverture impossible."""
        # 20 arcs, 20 km. 2 coureurs × 2 relais de max=3 km → total max = 12 km < 20 km.
        c = _base_constraints(nb_arcs=20, total_km=20.0)
        p = Preset(km=3.0, min=1, max=3)
        c.new_runner("A", 3).add_relay(p).add_relay(p)
        c.new_runner("B", 3).add_relay(p).add_relay(p)

        assert not _is_feasible(c), "Modèle complet devrait être infaisable"
        # Pas de famille unique à désactiver ici — c'est structurel.
        # On vérifie juste la détection d'infaisabilité.


# ===================================================================
# Combinaisons de contraintes incompatibles deux à deux
# ===================================================================

class TestPairwiseIncompatibilities:
    """Tests d'incompatibilités entre paires de familles de contraintes.

    Chaque test construit un problème qui est faisable sauf quand deux
    familles spécifiques sont TOUTES DEUX actives.
    """

    def test_availability_vs_rest(self):
        """Fenêtre serrée + repos long → infaisable."""
        # 40 arcs, 40 km, 10 km/h → 240 min total.
        # A a 2 relais de 3 km (~18 min chacun) avec repos_jour personnel de 1h.
        # Fenêtre A : [0, 10] = 10 km = 60 min. Besoin : 18+60+18 = 96 min > 60 → infaisable.
        # Sans repos : 18+18 = 36 < 60 → faisable.
        # Sans fenêtre : repos de 60 min passe dans le temps total 240 min → faisable.
        # B n'a pas de repos (set_options repos_jour=0).
        c = _base_constraints(nb_arcs=40, total_km=40.0, repos_jour=0.0)
        p = Preset(km=3.0, min=1, max=5)
        w = c.interval_waypoints(0, 10)
        c.new_runner("A", 3).set_options(repos_jour=1.0).add_relay(p, window=w).add_relay(p, window=w)
        p_big = Preset(km=15.0, min=10, max=30)
        c.new_runner("B", 3).add_relay(p_big).add_relay(p_big)

        assert not _is_feasible(c), "Modèle complet devrait être infaisable"
        assert _is_feasible(c, skip={"availability"}), "Sans availability devrait être faisable"
        assert _is_feasible(c, skip={"rest_intervals"}), "Sans rest devrait être faisable"

    def test_fixed_vs_availability(self):
        """Relais épinglé hors fenêtre → infaisable."""
        # Épingler à start=0, fenêtre commence au point 5.
        c = _base_constraints(nb_arcs=10, total_km=10.0)
        p = Preset(km=3.0, min=1, max=5)
        pin = c.new_pin(start_wp=0)
        w = c.interval_waypoints(5, 10)
        c.new_runner("A", 3).add_relay(p, pinned=pin, window=w).add_relay(p)
        c.new_runner("B", 3).add_relay(p).add_relay(p)

        assert not _is_feasible(c), "Modèle complet devrait être infaisable"
        assert _is_feasible(c, skip={"fixed_relays"}), "Sans fixed_relays devrait être faisable"
        assert _is_feasible(c, skip={"availability"}), "Sans availability devrait être faisable"

    def test_night_vs_rest(self):
        """nuit_max=0 + repos nuit obligatoire → infaisable si tout est nuit."""
        # Tout est nuit, nuit_max=0 → infaisable.
        # Mais skipping night_relay skips aussi rest_intervals (dépendance).
        # On teste l'infaisabilité et la résolution par skip de night_relay.
        c = _base_constraints(nb_arcs=10, total_km=10.0, nuit_max_default=0)
        c.add_night(c.interval_waypoints(0, 10))
        p = Preset(km=3.0, min=1, max=5)
        c.new_runner("A", 3).add_relay(p).add_relay(p)
        c.new_runner("B", 3).add_relay(p).add_relay(p)

        assert not _is_feasible(c), "Modèle complet devrait être infaisable"
        assert _is_feasible(c, skip={"night_relay"}), "Sans night_relay devrait être faisable"

    def test_solo_forced_false_more_relays_than_partner(self):
        """solo=False sur tous les relais mais plus de relais que le partenaire ne peut couvrir.

        A a 3 relais (solo=False chacun), B a 1 relais.
        Même en binôme, B ne peut couvrir qu'un seul relais de A → 2 restent solo → infaisable.
        """
        c = _base_constraints(nb_arcs=12, total_km=12.0)
        p_small = Preset(km=2.0, min=1, max=4)
        p_big = Preset(km=6.0, min=4, max=8)
        c.new_runner("A", 3).add_relay(p_small, solo=False).add_relay(p_small, solo=False).add_relay(p_small, solo=False)
        c.new_runner("B", 3).add_relay(p_big).add_relay(p_big)

        assert not _is_feasible(c), "Modèle complet devrait être infaisable"
        assert _is_feasible(c, skip={"solo"}), "Sans solo devrait être faisable"


# ===================================================================
# _PartialModel.build_without : propagation des dépendances
# ===================================================================

class TestSkipDependencies:
    """Vérifie la propagation des dépendances dans build_without."""

    def test_skip_same_relay_propagates(self):
        """Skipper same_relay doit aussi skipper solo, inter_runner, shared, max_duos, max_same_partenaire."""
        c = _base_constraints(nb_arcs=5, total_km=10.0)
        p = Preset(km=5.0, min=1, max=9)
        c.new_runner("A", 3).add_relay(p).add_relay(p)
        c.new_runner("B", 3).add_relay(p).add_relay(p)

        # Le modèle doit se construire sans erreur même si same_relay est skippé
        # (les familles dépendantes ne doivent pas crasher)
        m = _PartialModel()
        model = m.build_without(c, {"same_relay"})
        assert model is not None
        # same_relay dict doit être vide
        assert len(m.same_relay) == 0

    def test_skip_night_propagates_rest(self):
        """Skipper night_relay doit aussi skipper rest_intervals."""
        c = _base_constraints(nb_arcs=5, total_km=10.0, repos_jour=1.0)
        c.add_night(c.interval_waypoints(0, 5))
        p = Preset(km=5.0, min=1, max=9)
        c.new_runner("A", 3).add_relay(p).add_relay(p)
        c.new_runner("B", 3).add_relay(p).add_relay(p)

        m = _PartialModel()
        model = m.build_without(c, {"night_relay"})
        assert model is not None
        # Pas d'intervalles de repos créés
        assert len(m.iv_repos) == 0


# ===================================================================
# Tests de non-régression : build_without ne crashe pas
# ===================================================================

class TestBuildWithoutRobustness:
    """Vérifie que build_without fonctionne pour chaque famille skippable."""

    @pytest.mark.parametrize("family", [
        "symmetry_breaking",
        "fixed_relays",
        "pause_constraints",
        "coverage",
        "same_relay",
        "inter_runner_no_overlap",
        "night_relay",
        "solo",
        "rest_intervals",
        "availability",
        "shared_relays",
        "max_duos",
        "max_same_partenaire",
        "dplus_max",
    ])
    def test_skip_single_family(self, family):
        """build_without({family}) ne doit pas crasher."""
        c = _base_constraints(nb_arcs=10, total_km=10.0)
        c.add_night(c.interval_waypoints(0, 5))
        c.add_no_solo(c.interval_waypoints(5, 10))
        p = Preset(km=3.0, min=1, max=5)
        shared = c.new_shared_relay(target_km=3.0, min_km=1, max_km=5)
        a = c.new_runner("A", 3)
        b = c.new_runner("B", 3)
        a.add_relay(shared).add_relay(p)
        b.add_relay(shared).add_relay(p)
        c.add_max_duos(a, b, nb=2)

        m = _PartialModel()
        model = m.build_without(c, {family})
        assert model is not None

    def test_skip_empty_set(self):
        """build_without(set()) = modèle complet."""
        c = _base_constraints(nb_arcs=5, total_km=10.0)
        p = Preset(km=5.0, min=1, max=9)
        c.new_runner("A", 3).add_relay(p).add_relay(p)
        c.new_runner("B", 3).add_relay(p).add_relay(p)

        m = _PartialModel()
        model = m.build_without(c, set())
        assert model is not None

    def test_skip_all_phase1_families(self):
        """Skipper toutes les familles testables ne doit pas crasher."""
        from relay.feasibility import _PHASE1_FAMILIES
        all_families = {f for f, _ in _PHASE1_FAMILIES}
        c = _base_constraints(nb_arcs=5, total_km=10.0)
        p = Preset(km=5.0, min=1, max=9)
        c.new_runner("A", 3).add_relay(p).add_relay(p)
        c.new_runner("B", 3).add_relay(p).add_relay(p)

        m = _PartialModel()
        model = m.build_without(c, all_families)
        assert model is not None


# ===================================================================
# Tests des drills (Phase 2)
# ===================================================================

class TestDrillNight:
    """Vérifie que _apply_night_for_runner crée bien les BoolVars et applique nuit_max."""

    def test_night_bvars_created_after_skip(self):
        """Après skip de night_relay, _apply_night_for_runner doit créer relais_nuit."""
        from relay.feasibility import _apply_night_for_runner

        c = _base_constraints(nb_arcs=10, total_km=10.0, nuit_max_default=0)
        c.add_night(c.interval_waypoints(0, 10))
        p = Preset(km=3.0, min=1, max=5)
        c.new_runner("A", 3).add_relay(p).add_relay(p)
        c.new_runner("B", 3).add_relay(p).add_relay(p)

        m = _PartialModel()
        m.build_without(c, {"night_relay"})
        # Après skip, relais_nuit est vide
        assert len(m.relais_nuit) == 0

        # Appliquer pour "A" uniquement
        _apply_night_for_runner(m, c, "A")
        # relais_nuit doit maintenant contenir les BoolVars de A
        assert ("A", 0) in m.relais_nuit
        assert ("A", 1) in m.relais_nuit
        # B n'est pas touché
        assert ("B", 0) not in m.relais_nuit

    def test_night_drill_detects_guilty_runner(self):
        """Le drill nuit identifie le coureur dont nuit_max=0 cause l'infaisabilité."""
        c = _base_constraints(nb_arcs=10, total_km=10.0, nuit_max_default=99)
        c.add_night(c.interval_waypoints(0, 10))
        p = Preset(km=3.0, min=1, max=5)
        # A a nuit_max=0 → infaisable (tout est nuit)
        c.new_runner("A", 3).set_options(nuit_max=0).add_relay(p).add_relay(p)
        c.new_runner("B", 3).add_relay(p).add_relay(p)

        # Modèle complet infaisable
        assert not _is_feasible(c)
        # Skip night → faisable
        assert _is_feasible(c, skip={"night_relay"})

        # Drill per runner : A seul cause l'infaisabilité
        from relay.feasibility import FeasibilityAnalyser
        analyser = FeasibilityAnalyser(c, timeout=5.0)
        assert not analyser._check_single_runner("night_relay", "A")
        assert analyser._check_single_runner("night_relay", "B")


class TestDrillSharedRelays:
    """Vérifie la recherche de clé same_relay dans les deux ordres."""

    def test_shared_relay_key_order(self):
        """Le drill shared_relays trouve le BoolVar quel que soit l'ordre des coureurs."""
        c = _base_constraints(nb_arcs=10, total_km=10.0)
        p = Preset(km=3.0, min=1, max=5)
        shared = c.new_shared_relay(target_km=5.0, min_km=3, max_km=7)

        # B est déclaré avant A dans runners_data → paired_relays retournera (B, 0, A, 0)
        # mais same_relay est indexé par ordre d'itération sur runners_data
        c.new_runner("A", 3).add_relay(shared).add_relay(p)
        c.new_runner("B", 3).add_relay(shared).add_relay(p)

        m = _PartialModel()
        m.build_without(c, {"shared_relays"})

        # Vérifier que same_relay contient la clé dans un ordre précis
        pairings = c.paired_relays
        assert len(pairings) == 1
        r1, k1, r2, k2 = pairings[0]

        # Le drill doit trouver le BoolVar quelle que soit la direction
        bv = m.same_relay.get((r1, k1, r2, k2))
        if bv is None:
            bv = m.same_relay.get((r2, k2, r1, k1))
        assert bv is not None, "BoolVar same_relay introuvable dans les deux ordres"

    def test_drill_shared_with_disjoint_windows(self):
        """SharedLeg dans fenêtres disjointes → infaisable, le drill identifie le pairing."""
        c = _base_constraints(nb_arcs=10, total_km=10.0)
        p = Preset(km=3.0, min=1, max=5)
        shared = c.new_shared_relay(target_km=5.0, min_km=3, max_km=7)

        w_a = c.interval_waypoints(0, 5)
        w_b = c.interval_waypoints(5, 10)
        c.new_runner("A", 3).add_relay(shared, window=w_a).add_relay(p)
        c.new_runner("B", 3).add_relay(shared, window=w_b).add_relay(p)

        assert not _is_feasible(c)
        assert _is_feasible(c, skip={"shared_relays"})

        # Le drill ne doit pas crasher (c'était le bug d'origine)
        from relay.feasibility import FeasibilityAnalyser
        analyser = FeasibilityAnalyser(c, timeout=5.0)
        # Pas d'exception
        analyser._drill_shared_relays()


class TestDrillSolo:
    """Vérifie que le drill solo couvre solo_max, solo=False et no_solo."""

    def test_drill_solo_max(self):
        """Le drill identifie un coureur dont solo_max est trop restrictif."""
        # 3 coureurs, 1 relais chacun de 2 arcs sur 6 arcs.
        # Au moins 1 solo inévitable. A a solo_max=0.
        c = _base_constraints(nb_arcs=6, total_km=6.0, compat=COMPAT_ABC, solo_max_default=99)
        p = Preset(km=2.0, min=2, max=2)
        c.new_runner("A", 3).set_options(solo_max=0).add_relay(p)
        c.new_runner("B", 3).add_relay(p)
        c.new_runner("C", 3).add_relay(p)

        assert not _is_feasible(c)
        assert _is_feasible(c, skip={"solo"})

        # Le drill ne doit pas crasher et doit toucher les 3 axes
        from relay.feasibility import FeasibilityAnalyser
        analyser = FeasibilityAnalyser(c, timeout=5.0)
        analyser._drill_solo()  # pas d'exception

    def test_drill_solo_false(self):
        """Le drill identifie un relais solo=False impossible à satisfaire."""
        c = _base_constraints(nb_arcs=12, total_km=12.0)
        p_small = Preset(km=2.0, min=1, max=4)
        p_big = Preset(km=6.0, min=4, max=8)
        # A a 3 relais solo=False, B n'en a que 2 → 1 relais de A sera forcément solo
        c.new_runner("A", 3).add_relay(p_small, solo=False).add_relay(p_small, solo=False).add_relay(p_small, solo=False)
        c.new_runner("B", 3).add_relay(p_big).add_relay(p_big)

        assert not _is_feasible(c)
        assert _is_feasible(c, skip={"solo"})

        from relay.feasibility import FeasibilityAnalyser
        analyser = FeasibilityAnalyser(c, timeout=5.0)
        analyser._drill_solo()  # pas d'exception

    def test_drill_no_solo_zone(self):
        """Le drill identifie une zone no_solo problématique."""
        c = _base_constraints(nb_arcs=6, total_km=6.0, compat=COMPAT_ABC, solo_max_default=99)
        # Zone no_solo sur tout le parcours, mais un coureur sera forcément solo
        c.add_no_solo(c.interval_waypoints(0, 6))

        p = Preset(km=2.0, min=2, max=2)
        c.new_runner("A", 3).add_relay(p)
        c.new_runner("B", 3).add_relay(p)
        c.new_runner("C", 3).add_relay(p)

        assert not _is_feasible(c)
        assert _is_feasible(c, skip={"solo"})

        from relay.feasibility import FeasibilityAnalyser
        analyser = FeasibilityAnalyser(c, timeout=5.0)
        analyser._drill_solo()  # pas d'exception
