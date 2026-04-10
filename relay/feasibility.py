"""
relay/feasibility.py

FeasibilityAnalyser — recherche automatique des contraintes causant l'infaisabilité
dans le modèle à points de passage (waypoints).

Stratégie : construction de modèles partiels successifs.
1. Modèle complet — si faisable, pas de problème.
2. Désactivation successive de chaque famille de contraintes.
3. Pour les familles suspectes : diagnostic fin par coureur / relais (stubs).

Usage :
    from relay.feasibility import FeasibilityAnalyser
    FeasibilityAnalyser(constraints).run()
"""

from ortools.sat.python import cp_model

from .constraints import Constraints
from .model import Model


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _solve_feasibility(model: cp_model.CpModel, timeout: float = 10.0) -> bool:
    """Retourne True si le modèle CP-SAT trouve une solution (ou expire sans preuve d'infaisabilité).

    Un UNKNOWN après timeout est traité comme faisable : on ne peut pas conclure à
    l'infaisabilité sans preuve complète.
    """
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout
    solver.parameters.num_workers = 8
    solver.parameters.log_search_progress = False
    status = solver.solve(model)
    return status in (cp_model.OPTIMAL, cp_model.FEASIBLE, cp_model.UNKNOWN)


def _label(ok: bool) -> str:
    return "OK/timeout" if ok else "INFAISABLE"


def _apply_rest_for_runner(m: "_PartialModel", c: Constraints, runner: str) -> None:
    """Réapplique les contraintes de repos uniquement pour `runner` sur un modèle déjà construit."""
    # Délègue à add_rest_intervals mais uniquement pour le coureur voulu.
    # add_rest_intervals itère sur tous les coureurs — on patch temporairement runners_data.
    saved = c.runners_data
    c.runners_data = {runner: saved[runner]}
    try:
        m.add_rest_intervals(c)
    finally:
        c.runners_data = saved


def _apply_availability_for_runner(m: "_PartialModel", c: Constraints, runner: str) -> None:
    """Réapplique les contraintes de disponibilité uniquement pour `runner`."""
    saved = c.runners_data
    c.runners_data = {runner: saved[runner]}
    try:
        m.add_availability(c)
    finally:
        c.runners_data = saved


def _apply_night_for_runner(m: "_PartialModel", c: Constraints, runner: str) -> None:
    """Réapplique les contraintes de nuit uniquement pour `runner`.

    Quand night_relay est skippée, relais_nuit est vide. On appelle
    add_night_relay() en patchant runners_data pour ne traiter que `runner`,
    ce qui recrée les BoolVars nuit ET applique nuit_max pour ce coureur.
    """
    saved = c.runners_data
    c.runners_data = {runner: saved[runner]}
    try:
        m.add_night_relay(c)
    finally:
        c.runners_data = saved


# ---------------------------------------------------------------------------
# Modèle partiel — variante de Model avec contraintes désactivables
# ---------------------------------------------------------------------------

# Mapping : nom de famille → dépendances qui doivent être présentes
# (familles qui doivent aussi être skippées si on skippe celle-ci)
_SKIP_DEPS: dict[str, set[str]] = {
    "same_relay": {"solo", "inter_runner_no_overlap", "shared_relays", "max_duos", "max_same_partenaire"},
    "night_relay": {"rest_intervals"},
}

# Familles testables en phase 1 (avec label lisible)
_PHASE1_FAMILIES: list[tuple[str, str]] = [
    ("fixed_relays",            "Relais épinglés (pinned)"),
    ("night_relay",             "Plages de nuit (nuit_max)"),
    ("rest_intervals",          "Repos entre relais"),
    ("availability",            "Disponibilités / fenêtres"),
    ("coverage",                "Couverture des arcs"),
    ("inter_runner_no_overlap", "Non-chevauchement inter-coureurs"),
    ("solo",                    "Contraintes solo"),
    ("shared_relays",           "Pairings forcés (SharedLeg)"),
    ("max_duos",                "Max binômes par paire (add_max_duos)"),
    ("max_same_partenaire",     "Max même partenaire"),
    ("dplus_max",               "Max D+ / D-")
]


class _PartialModel(Model):
    """Model waypoint avec des groupes de contraintes désactivables."""

    def _dispatch(self, family: str, c: Constraints) -> None:
        dispatch = {
            "symmetry_breaking":       self.add_symmetry_breaking,
            "fixed_relays":            self.add_fixed_relays,
            "chained_relays":          self.add_chained_relays,
            "pause_constraints":       self.add_pause_constraints,
            "coverage":                self.add_coverage,
            "same_relay":              self.add_same_relay,
            "inter_runner_no_overlap": self.add_inter_runner_no_overlap,
            "night_relay":             self.add_night_relay,
            "solo":                    self.add_solo_constraints,
            "rest_intervals":          self.add_rest_intervals,
            "availability":            self.add_availability,
            "shared_relays":           self.add_shared_relays,
            "max_duos":                self.add_max_duos,
            "max_same_partenaire":     self.add_max_same_partenaire,
            "dplus_max":               self.add_dplus_max_constraints,
        }
        dispatch[family](c)

    def build_without(self, c: Constraints, skip: set[str]) -> cp_model.CpModel:
        """Construit le modèle complet sauf les familles dans skip.

        Gère automatiquement les dépendances : si une famille est skippée,
        toutes les familles qui en dépendent sont également skippées.
        """
        # Propagation des dépendances
        effective_skip = set(skip)
        changed = True
        while changed:
            changed = False
            for family, dependents in _SKIP_DEPS.items():
                if family in effective_skip:
                    added = dependents - effective_skip
                    if added:
                        effective_skip |= added
                        changed = True

        assert not self.model, "déjà initialisé"
        self.model = cp_model.CpModel()

        self.add_variables(c)
        for family in self.CONSTRAINT_FAMILIES:
            if family not in effective_skip:
                self._dispatch(family, c)

        return self.model


# ---------------------------------------------------------------------------
# Analyser principal
# ---------------------------------------------------------------------------

class FeasibilityAnalyser:
    """Diagnostique les contraintes causant l'infaisabilité d'un Constraints waypoint."""

    def __init__(self, constraints: Constraints, timeout: float = 10.0):
        self.c = constraints
        self.timeout = timeout

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Lance l'analyse complète et affiche le rapport."""
        print("=" * 65)
        print("ANALYSE DE FAISABILITÉ (waypoints)")
        print("=" * 65)

        ok_full = self._check_skip("Modèle complet", set())
        if ok_full:
            print("\nLe modèle complet est FAISABLE. Aucun problème détecté.")
            return

        print()
        print("Phase 1 — désactivation de chaque famille de contraintes")
        print("-" * 65)

        suspects: list[tuple[str, str]] = []
        for family, label in _PHASE1_FAMILIES:
            ok = self._check_skip(label, {family})
            if ok:
                suspects.append((family, label))

        if not suspects:
            print()
            print("Aucune famille seule ne débloque le problème.")
            print("L'infaisabilité est probablement due à une combinaison de contraintes.")
            self._analyse_combinations()
            return

        print()
        print(f"Phase 2 — diagnostic fin ({len(suspects)} famille(s) suspecte(s))")
        print("-" * 65)
        for family, label in suspects:
            print(f"\n  >> {label}")
            self._drill_down(family)

        print()
        print("=" * 65)
        print("FIN DE L'ANALYSE")

    # ------------------------------------------------------------------
    # Méthodes internes
    # ------------------------------------------------------------------

    def _check_skip(self, label: str, skip: set[str]) -> bool:
        m = _PartialModel()
        model = m.build_without(self.c, skip)
        ok = _solve_feasibility(model, self.timeout)
        print(f"  [{_label(ok)}]  {label}")
        return ok

    def _drill_down(self, family: str) -> None:
        """Identifie quels coureurs / relais causent le problème dans une famille."""
        if family == "rest_intervals":
            self._drill_rest()
        elif family == "availability":
            self._drill_availability()
        elif family == "night_relay":
            self._drill_night()
        elif family == "fixed_relays":
            self._drill_pinned()
        elif family == "shared_relays":
            self._drill_shared_relays()
        elif family == "max_duos":
            self._drill_max_duos()
        elif family == "max_same_partenaire":
            self._drill_max_same_partenaire()
        elif family == "solo":
            self._drill_solo()
        else:
            print("    (pas de diagnostic fin disponible pour cette famille)")

    def _drill_per_runner(self, family: str) -> None:
        """Pour repos / dispo / nuit : teste chaque coureur séparément.

        On construit le modèle SANS la famille concernée, puis on la réactive
        coureur par coureur. Si réactiver UN coureur seul rend infaisable → suspect.
        """
        c = self.c
        family_label = {
            "rest_intervals": "Repos",
            "availability":   "Disponibilité",
            "night_relay":    "Nuit max",
        }[family]

        guilty = []
        for r in c.runners:
            ok = self._check_single_runner(family, r)
            if not ok:
                guilty.append(r)
                print(f"    SUSPECT [{family_label}] : {r}")

        if not guilty:
            print(f"    Aucun coureur isolément ne cause l'infaisabilité ({family_label}).")
            print("    → Probablement une interaction entre plusieurs coureurs.")

    def _check_single_runner(self, family: str, runner: str) -> bool:
        """Construit un modèle partiel où `family` n'est active que pour `runner`.

        Pour les familles per-runner (rest, availability, night) :
        on désactive la famille globalement, puis on l'applique manuellement
        pour le seul coureur `runner`.
        """
        m = _PartialModel()
        model = m.build_without(self.c, {family})

        c = self.c
        if family == "rest_intervals":
            _apply_rest_for_runner(m, c, runner)
        elif family == "availability":
            _apply_availability_for_runner(m, c, runner)
        elif family == "night_relay":
            _apply_night_for_runner(m, c, runner)

        ok = _solve_feasibility(model, self.timeout)
        return ok

    def _drill_rest(self) -> None:
        self._drill_per_runner("rest_intervals")

    def _drill_availability(self) -> None:
        self._drill_per_runner("availability")

    def _drill_night(self) -> None:
        self._drill_per_runner("night_relay")

    def _drill_pinned(self) -> None:
        """Teste chaque relais épinglé individuellement."""
        c = self.c
        pinned_list = [
            (r, k, spec)
            for r, coureur in c.runners_data.items()
            for k, spec in enumerate(coureur.relais)
            if spec.pinned_start is not None or spec.pinned_end is not None
        ]
        if not pinned_list:
            print("    Aucun relais épinglé.")
            return

        for r, k, spec in pinned_list:
            start_pt = spec.pinned_start
            end_pt = spec.pinned_end
            h_start = c._point_hour(start_pt) if start_pt is not None else None
            h_end = c._point_hour(end_pt) if end_pt is not None else None
            # Modèle sans fixed, puis on force uniquement ce relais
            m = _PartialModel()
            model = m.build_without(c, {"fixed_relays"})
            if start_pt is not None:
                model.add(m.start[(r, k)] == start_pt)
            if end_pt is not None:
                model.add(m.end[(r, k)] == end_pt)
            ok = _solve_feasibility(model, self.timeout)
            s_info = f"pt {start_pt} ({h_start:.1f}h)" if start_pt is not None else "libre"
            e_info = f"pt {end_pt} ({h_end:.1f}h)" if end_pt is not None else "libre"
            print(f"    [{_label(ok)}]  {r}[{k}] épinglé {s_info}→{e_info}")

    def _drill_shared_relays(self) -> None:
        """Teste chaque SharedLeg individuellement."""
        c = self.c
        pairings = c.paired_relays
        if not pairings:
            print("    Aucun pairing forcé.")
            return

        for r1, k1, r2, k2 in pairings:
            m = _PartialModel()
            model = m.build_without(c, {"shared_relays"})
            # same_relay est indexé par (r_lower_idx, k, r_higher_idx, kp)
            # mais paired_relays peut retourner l'ordre inverse — essayer les deux
            bv = m.same_relay.get((r1, k1, r2, k2))
            if bv is None:
                bv = m.same_relay.get((r2, k2, r1, k1))
            if bv is not None:
                model.add(bv == 1)
            else:
                # Pas de BoolVar same_relay (compat=0) → forcer manuellement start/end identiques
                model.add(m.start[(r1, k1)] == m.start[(r2, k2)])
                model.add(m.end[(r1, k1)] == m.end[(r2, k2)])
            ok = _solve_feasibility(model, self.timeout)
            print(f"    [{_label(ok)}]  pairing {r1}[{k1}]+{r2}[{k2}]")

    def _drill_max_duos(self) -> None:
        """Teste chaque contrainte add_max_duos individuellement."""
        c = self.c
        if not c.max_duos:
            print("    Aucune contrainte add_max_duos déclarée.")
            return

        for r1, r2, nb in c.max_duos:
            m = _PartialModel()
            model = m.build_without(c, {"max_duos"})
            pair_vars = [
                bv
                for (a, _k1, b, _k2), bv in m.same_relay.items()
                if {a, b} == {r1, r2}
            ]
            if pair_vars:
                model.add(sum(pair_vars) <= nb)
            ok = _solve_feasibility(model, self.timeout)
            print(f"    [{_label(ok)}]  max_duos({r1}, {r2}) <= {nb}")

    def _drill_max_same_partenaire(self) -> None:
        """Teste chaque paire (r1, r2) soumise à max_same_partenaire individuellement."""
        c = self.c

        # Construire un modèle de référence pour connaître les clés same_relay
        m_ref = _PartialModel()
        m_ref.build_without(c, {"max_same_partenaire"})

        seen: set[frozenset] = set()
        pairs: list[tuple[str, str, int]] = []
        for (r1, _k1, r2, _k2) in m_ref.same_relay:
            key = frozenset({r1, r2})
            if key in seen:
                continue
            seen.add(key)
            lim1 = c.runners_data[r1].options.max_same_partenaire
            lim2 = c.runners_data[r2].options.max_same_partenaire
            individual = [v for v in (lim1, lim2) if v is not None]
            msp_default = c.defaults.max_same_partenaire
            max_same = min(individual) if individual else msp_default
            if max_same is not None:
                pairs.append((r1, r2, max_same))

        if not pairs:
            print("    Aucune contrainte max_same_partenaire effective.")
            return

        for r1, r2, max_same in pairs:
            m = _PartialModel()
            model = m.build_without(c, {"max_same_partenaire"})
            pair_vars = [
                bv for (a, _k1, b, _k2), bv in m.same_relay.items()
                if {a, b} == {r1, r2}
            ]
            if len(pair_vars) > max_same:
                model.add(sum(pair_vars) <= max_same)
            ok = _solve_feasibility(model, self.timeout)
            print(f"    [{_label(ok)}]  max_same_partenaire({r1}, {r2}) <= {max_same}")

    def _drill_solo(self) -> None:
        """Diagnostique les causes d'infaisabilité liées aux contraintes solo.

        Explore trois axes :
        1. solo_max par coureur : relâche solo_max pour chaque coureur individuellement
        2. solo=False par relais : teste chaque relais avec binôme obligatoire
        3. zones no_solo : teste chaque zone solo-interdite individuellement
        """
        c = self.c
        found_any = False

        # --- 1. solo_max : relâchement par coureur ---
        solo_max_candidates = [
            r for r in c.runners
            if c.runners_data[r].options.solo_max is not None
        ]
        if solo_max_candidates:
            print("    solo_max par coureur :")
            for r in solo_max_candidates:
                orig = c.runners_data[r].options.solo_max
                c.runners_data[r].options.solo_max = 99
                try:
                    m = _PartialModel()
                    model = m.build_without(c, set())
                finally:
                    c.runners_data[r].options.solo_max = orig
                ok = _solve_feasibility(model, self.timeout)
                if ok:
                    found_any = True
                    print(f"      [{_label(ok)}]  {r} avec solo_max=99 (déclaré={orig})")

        # --- 2. solo=False : relais forcés en binôme ---
        forced_binome = [
            (r, k, spec)
            for r, coureur in c.runners_data.items()
            for k, spec in enumerate(coureur.relais)
            if spec.solo is False
        ]
        if forced_binome:
            print("    relais solo=False (binôme obligatoire) :")
            for r, k, spec in forced_binome:
                orig = spec.solo
                spec.solo = None
                try:
                    m = _PartialModel()
                    model = m.build_without(c, set())
                finally:
                    spec.solo = orig
                ok = _solve_feasibility(model, self.timeout)
                if ok:
                    found_any = True
                print(f"      [{_label(ok)}]  {r}[{k}] solo=False → solo=None")

        # --- 3. zones no_solo ---
        if c._intervals_no_solo:
            print("    zones solo-interdites :")
            for i, (lo, hi) in enumerate(c._intervals_no_solo):
                saved = list(c._intervals_no_solo)
                c._intervals_no_solo = saved[:i] + saved[i + 1:]
                try:
                    m = _PartialModel()
                    model = m.build_without(c, set())
                finally:
                    c._intervals_no_solo = saved
                ok = _solve_feasibility(model, self.timeout)
                if ok:
                    found_any = True
                lo_km = c.waypoints_km[lo] if lo < len(c.waypoints_km) else "?"
                hi_km = c.waypoints_km[hi] if hi < len(c.waypoints_km) else "?"
                print(f"      [{_label(ok)}]  no_solo[{i}] pts {lo}→{hi} ({lo_km}→{hi_km} km)")

        if not found_any and not (solo_max_candidates or forced_binome or c._intervals_no_solo):
            print("    Aucune contrainte solo spécifique détectée.")

    def _analyse_combinations(self) -> None:
        """Teste des paires de familles désactivées simultanément."""
        print()
        print("Phase 3 — combinaisons de deux familles désactivées")
        print("-" * 65)

        found = False
        for i, (f1, l1) in enumerate(_PHASE1_FAMILIES):
            for f2, l2 in _PHASE1_FAMILIES[i + 1:]:
                m = _PartialModel()
                model = m.build_without(self.c, {f1, f2})
                ok = _solve_feasibility(model, self.timeout)
                if ok:
                    found = True
                    print(f"  [OK  ]  désactiver {l1!r} + {l2!r} → faisable")

        if not found:
            print("  Aucune paire de familles ne débloque le problème.")
            print("  → Interaction plus complexe ou contrainte structurelle (couverture / no-overlap).")


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def diag_faisabilite(constraints: Constraints, timeout: float = 10.0) -> None:
    """Fonction utilitaire : crée un FeasibilityAnalyser et lance l'analyse."""
    FeasibilityAnalyser(constraints, timeout).run()
