"""
FeasibilityAnalyser — recherche automatique des contraintes causant l'infaisabilité.

Stratégie : construction de modèles partiels successifs.
1. Modèle complet — si faisable, pas de problème.
2. Désactivation successive de chaque famille de contraintes.
3. Pour les familles suspectes : diagnostic fin par coureur / relais.

Usage :
    python feasibility_analyser.py
"""

import sys
from pathlib import Path

# Les modules du projet (constraints, model, …) sont à la racine ; on l'ajoute
# au chemin pour pouvoir importer ce script depuis n'importe quel répertoire.
sys.path.insert(0, str(Path(__file__).parent.parent))

from ortools.sat.python import cp_model

from constraints import RelayConstraints
from model import RelayModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _solve_feasibility(model: cp_model.CpModel, timeout: float = 10.0) -> bool:
    """Retourne True si le modèle CP-SAT trouve une solution (ou expire sans preuve d'infaisabilité).

    Un UNKNOWN après timeout est traité comme faisable : on ne peut pas conclure à l'infaisabilité
    sans preuve complète, et l'outil vise à isoler les contraintes clairement bloquantes.
    """
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout
    solver.parameters.num_workers = 8
    solver.parameters.log_search_progress = False
    status = solver.solve(model)
    # UNKNOWN = timeout sans solution ni preuve d'infaisabilité → on considère faisable
    return status in (cp_model.OPTIMAL, cp_model.FEASIBLE, cp_model.UNKNOWN)


def _label(ok: bool) -> str:
    return "OK/timeout" if ok else "INFAISABLE"


# ---------------------------------------------------------------------------
# Modèle partiel — variante de RelayModel avec contraintes optionnelles
# ---------------------------------------------------------------------------

class _PartialModel(RelayModel):
    """RelayModel avec des groupes de contraintes désactivables."""

    def build_partial(
        self,
        constraints: RelayConstraints,
        *,
        skip_fixed: bool = False,
        skip_night: bool = False,
        skip_rest: bool = False,
        skip_availability: bool = False,
        skip_coverage: bool = False,
        skip_no_overlap: bool = False,
        skip_solo: bool = False,
        skip_forced_pairings: bool = False,
        skip_once_max: bool = False,
        skip_max_same_partenaire: bool = False,
        # Sous-ensembles par coureur (None = appliquer à tous)
        only_rest_for: set[str] | None = None,
        only_avail_for: set[str] | None = None,
        only_night_for: set[str] | None = None,
    ) -> "cp_model.CpModel":
        assert not self.model, "déjà initialisé"
        self.model = cp_model.CpModel()

        self._add_variables(constraints)

        if not skip_fixed:
            self._add_fixed_relays(constraints)

        self._add_night_relay_partial(
            constraints,
            skip=skip_night,
            only_for=only_night_for,
        )

        self._add_solo_intervals(constraints)

        self._add_rest_partial(
            constraints,
            skip=skip_rest,
            only_for=only_rest_for,
        )

        self._add_availability_partial(
            constraints,
            skip=skip_availability,
            only_for=only_avail_for,
        )

        self._add_same_relay(constraints)

        self._add_pause_constraints(constraints)

        if not skip_coverage:
            self._add_coverage(constraints)

        if not skip_no_overlap:
            self._add_inter_runner_no_overlap(constraints)

        if not skip_solo:
            self._add_solo_constraints(constraints)

        if not skip_forced_pairings:
            self._add_forced_pairings(constraints)

        if not skip_once_max:
            self._add_once_max(constraints)

        if not skip_max_same_partenaire:
            self._add_max_same_partenaire(constraints)

        return self.model

    # ------------------------------------------------------------------
    # Variantes partielles des méthodes de RelayModel
    # ------------------------------------------------------------------

    def _add_night_relay_partial(self, constraints, skip: bool, only_for: set[str] | None):
        """Ajoute les contraintes de nuit, potentiellement filtrées par coureur."""
        c = constraints
        model = self.model
        seg_night_list = sorted(c.night_segments)

        for r in c.runners:
            self.relais_nuit[r] = []
            for k, spec in enumerate(c.runners_data[r].relais):
                sizes = spec.size
                sz_lo, sz_hi = min(sizes), max(sizes)
                night_starts = sorted(
                    set(
                        n - off
                        for n in seg_night_list
                        for off in range(sz_hi)
                        if 0 <= n - off <= c.nb_segments - sz_lo
                    )
                )
                rhn = model.new_bool_var(f"rn_{r}_{k}")
                if not night_starts:
                    model.add(rhn == 0)
                else:
                    nd = cp_model.Domain.from_values(night_starts)
                    dd = nd.complement().intersection_with(
                        cp_model.Domain(0, c.nb_segments - sz_lo)
                    )
                    model.add_linear_expression_in_domain(self.start[r][k], nd).only_enforce_if(rhn)
                    if not dd.is_empty():
                        model.add_linear_expression_in_domain(
                            self.start[r][k], dd
                        ).only_enforce_if(~rhn)
                    else:
                        model.add(rhn == 1)
                self.relais_nuit[r].append(rhn)

        if skip:
            return

        for r in c.runners:
            if only_for is not None and r not in only_for:
                continue
            rd = c.runners_data[r]
            nuit_max = c._resolved_nuit_max(rd)
            if nuit_max < len(rd.relais):
                model.add(sum(self.relais_nuit[r]) <= nuit_max)

    def _add_rest_partial(self, constraints, skip: bool, only_for: set[str] | None):
        """Contraintes de repos, filtrées par coureur si only_for est fourni."""
        if skip:
            return
        c = constraints
        model = self.model
        for r in c.runners:
            if only_for is not None and r not in only_for:
                continue
            n_relays = len(c.runners_data[r].relais)
            if n_relays < 2:
                continue
            rd = c.runners_data[r]
            repos_jour = c._resolved_repos_jour(rd)
            repos_nuit = c._resolved_repos_nuit(rd)
            for k in range(n_relays):
                for kp in range(k + 1, n_relays):
                    k_before_kp = model.new_bool_var(f"bef_{r}_{k}_{kp}")
                    k_day_then_kp = model.new_bool_var(f"bkd_{r}_{k}_{kp}")
                    k_night_then_kp = model.new_bool_var(f"bkn_{r}_{k}_{kp}")
                    model.add_bool_and([k_before_kp, ~self.relais_nuit[r][k]]).only_enforce_if(k_day_then_kp)
                    model.add_bool_or([~k_before_kp, self.relais_nuit[r][k]]).only_enforce_if(~k_day_then_kp)
                    model.add_bool_and([k_before_kp, self.relais_nuit[r][k]]).only_enforce_if(k_night_then_kp)
                    model.add_bool_or([~k_before_kp, ~self.relais_nuit[r][k]]).only_enforce_if(~k_night_then_kp)
                    model.add(self.end[r][k] + repos_jour <= self.start[r][kp]).only_enforce_if(k_day_then_kp)
                    model.add(self.end[r][k] + repos_nuit <= self.start[r][kp]).only_enforce_if(k_night_then_kp)
                    kp_day_then_k = model.new_bool_var(f"bkpd_{r}_{k}_{kp}")
                    kp_night_then_k = model.new_bool_var(f"bkpn_{r}_{k}_{kp}")
                    model.add_bool_and([~k_before_kp, ~self.relais_nuit[r][kp]]).only_enforce_if(kp_day_then_k)
                    model.add_bool_or([k_before_kp, self.relais_nuit[r][kp]]).only_enforce_if(~kp_day_then_k)
                    model.add_bool_and([~k_before_kp, self.relais_nuit[r][kp]]).only_enforce_if(kp_night_then_k)
                    model.add_bool_or([k_before_kp, ~self.relais_nuit[r][kp]]).only_enforce_if(~kp_night_then_k)
                    model.add(self.end[r][kp] + repos_jour <= self.start[r][k]).only_enforce_if(kp_day_then_k)
                    model.add(self.end[r][kp] + repos_nuit <= self.start[r][k]).only_enforce_if(kp_night_then_k)

    def _add_availability_partial(self, constraints, skip: bool, only_for: set[str] | None):
        """Contraintes de disponibilité, filtrées par coureur si only_for est fourni."""
        if skip:
            return
        c = constraints
        model = self.model
        for r, coureur in c.runners_data.items():
            if only_for is not None and r not in only_for:
                continue
            for k, spec in enumerate(coureur.relais):
                if spec.window is None:
                    continue
                if len(spec.window) == 1:
                    ws, we = spec.window[0]
                    model.add(self.start[r][k] >= ws)
                    model.add(self.end[r][k] <= we)
                else:
                    bools = []
                    for i, (ws, we) in enumerate(spec.window):
                        b = model.new_bool_var(f"win_{r}_{k}_{i}")
                        model.add(self.start[r][k] >= ws).only_enforce_if(b)
                        model.add(self.end[r][k] <= we).only_enforce_if(b)
                        bools.append(b)
                    model.add_bool_or(bools)


# ---------------------------------------------------------------------------
# Analyser principal
# ---------------------------------------------------------------------------

class FeasibilityAnalyser:
    """Diagnostique les contraintes causant l'infaisabilité d'un RelayConstraints."""

    def __init__(self, constraints: RelayConstraints, timeout: float = 10.0):
        self.c = constraints
        self.timeout = timeout
        self._suspects: list[str] = []

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Lance l'analyse complète et affiche le rapport."""
        print("=" * 65)
        print("ANALYSE DE FAISABILITÉ")
        print("=" * 65)

        # Étape 1 : modèle complet
        ok_full = self._check("Modèle complet")
        if ok_full:
            print("\nLe modèle complet est FAISABLE. Aucun problème détecté.")
            return

        print()
        print("Phase 1 — désactivation de chaque famille de contraintes")
        print("-" * 65)

        families = [
            ("Relais épinglés (pinned)",              dict(skip_fixed=True)),
            ("Plages de nuit (nuit_max)",              dict(skip_night=True)),
            ("Repos entre relais",                     dict(skip_rest=True)),
            ("Disponibilités / fenêtres",              dict(skip_availability=True)),
            ("Couverture des segments",                dict(skip_coverage=True)),
            ("Non-chevauchement inter-coureurs",       dict(skip_no_overlap=True)),
            ("Contraintes solo",                       dict(skip_solo=True)),
            ("Pairings forcés (SharedRelay)",          dict(skip_forced_pairings=True)),
            ("Max binômes par paire (add_max_binomes)", dict(skip_once_max=True)),
            ("Max même partenaire (max_same_partenaire)", dict(skip_max_same_partenaire=True)),
        ]

        suspects = []
        for label, kwargs in families:
            ok = self._check(label, **kwargs)
            if ok:
                suspects.append((label, kwargs))

        if not suspects:
            print()
            print("Aucune famille seule ne débloque le problème.")
            print("L'infaisabilité est probablement due à une combinaison de contraintes.")
            self._analyse_combinations()
            return

        print()
        print(f"Phase 2 — diagnostic fin ({len(suspects)} famille(s) suspecte(s))")
        print("-" * 65)
        for label, kwargs in suspects:
            print(f"\n  >> {label}")
            self._drill_down(label, kwargs)

        print()
        print("=" * 65)
        print("FIN DE L'ANALYSE")

    # ------------------------------------------------------------------
    # Méthodes internes
    # ------------------------------------------------------------------

    def _check(self, label: str, **kwargs) -> bool:
        m = _PartialModel()
        model = m.build_partial(self.c, **kwargs)
        ok = _solve_feasibility(model, self.timeout)
        print(f"  [{_label(ok)}]  {label}")
        return ok

    def _drill_down(self, family_label: str, family_kwargs: dict) -> None:
        """Identifie quels coureurs / relais causent le problème dans une famille."""
        key = list(family_kwargs.keys())[0]

        if key == "skip_rest":
            self._drill_per_runner("Repos", "only_rest_for")
        elif key == "skip_availability":
            self._drill_per_runner("Disponibilité", "only_avail_for")
        elif key == "skip_night":
            self._drill_per_runner("Nuit max", "only_night_for")
        elif key == "skip_fixed":
            self._drill_pinned()
        elif key == "skip_forced_pairings":
            self._drill_pairings()
        elif key == "skip_once_max":
            self._drill_once_max()
        elif key == "skip_max_same_partenaire":
            self._drill_max_same_partenaire()
        else:
            print(f"    (pas de diagnostic fin disponible pour cette famille)")

    def _drill_per_runner(self, family_name: str, kwarg_only: str) -> None:
        """Pour repos / dispo / nuit : teste chaque coureur séparément.

        On construit le modèle SANS la famille concernée, puis on la réactive
        coureur par coureur. Si réactiver UN coureur rend infaisable → suspect.
        """
        c = self.c
        guilty = []

        for r in c.runners:
            # Modèle de base sans la famille ; on réactive seulement pour r
            kwargs = {kwarg_only: {r}}
            m = _PartialModel()
            # Construire avec la contrainte réactivée uniquement pour r
            # Pour cela on doit passer les bons skip_* tout en activant only_for={r}
            model = self._build_with_one_runner(kwarg_only, r)
            ok = _solve_feasibility(model, self.timeout)
            if not ok:
                guilty.append(r)
                print(f"    SUSPECT [{family_name}] : {r}")

        if not guilty:
            print(f"    Aucun coureur isolément ne cause l'infaisabilité ({family_name}).")
            print(f"    → Probablement une interaction entre plusieurs coureurs.")

    def _build_with_one_runner(self, kwarg_only: str, runner: str) -> cp_model.CpModel:
        """Construit un modèle avec la contrainte réactivée uniquement pour `runner`."""
        m = _PartialModel()
        only_kw = {kwarg_only: {runner}}

        # Tous les skip_* à False sauf la famille testée qui reste désactivée pour les autres
        # → on passe only_for={runner} pour n'appliquer la contrainte qu'à ce coureur
        model = m.build_partial(self.c, **only_kw)
        return model

    def _drill_pinned(self) -> None:
        """Teste chaque relais épinglé individuellement."""
        c = self.c
        pinned_list = [
            (r, k, spec)
            for r, coureur in c.runners_data.items()
            for k, spec in enumerate(coureur.relais)
            if spec.pinned is not None
        ]
        if not pinned_list:
            print("    Aucun relais épinglé.")
            return

        for r, k, spec in pinned_list:
            h = c.segment_start_hour(spec.pinned)
            # Modèle sans fixed, puis on force uniquement ce relais
            m = _PartialModel()
            m.model = cp_model.CpModel()
            m._add_variables(c)
            m._add_night_relay_partial(c, skip=False, only_for=None)
            m._add_solo_intervals(c)
            m._add_rest_partial(c, skip=False, only_for=None)
            m._add_availability_partial(c, skip=False, only_for=None)
            m._add_same_relay(c)
            m._add_pause_constraints(c)
            m._add_coverage(c)
            m._add_inter_runner_no_overlap(c)
            m._add_solo_constraints(c)
            m._add_forced_pairings(c)
            # Épingler uniquement ce relais
            m.model.add(m.start[r][k] == spec.pinned)
            m.model.add(m.size[r][k] == max(spec.size))
            ok = _solve_feasibility(m.model, self.timeout)
            seg_info = f"seg {spec.pinned} ({h:.1f}h)"
            print(f"    [{_label(ok)}]  {r}[{k}] épinglé à {seg_info}")

    def _drill_pairings(self) -> None:
        """Teste chaque pairing forcé individuellement."""
        c = self.c
        pairings = c.paired_relays
        if not pairings:
            print("    Aucun pairing forcé.")
            return

        runner_idx = {r: i for i, r in enumerate(c.runners)}
        for r1, k1, r2, k2 in pairings:
            # Modèle sans forced pairings, puis on force uniquement ce pairing
            m = _PartialModel()
            model = m.build_partial(c, skip_forced_pairings=True)
            key = (r1, k1, r2, k2) if runner_idx[r1] < runner_idx[r2] else (r2, k2, r1, k1)
            bv = m.same_relay.get(key)
            if bv is not None:
                model.add(bv == 1)
            ok = _solve_feasibility(model, self.timeout)
            print(f"    [{_label(ok)}]  pairing {r1}[{k1}]+{r2}[{k2}]")

    def _drill_once_max(self) -> None:
        """Teste chaque contrainte add_max_binomes individuellement."""
        c = self.c
        if not c.once_max:
            print("    Aucune contrainte add_max_binomes déclarée.")
            return

        for r1, r2, nb in c.once_max:
            # Modèle sans once_max, puis on force uniquement cette contrainte
            m = _PartialModel()
            model = m.build_partial(c, skip_once_max=True)
            pair_vars = [
                bv
                for key, bv in m.same_relay.items()
                if (key[0] == r1 and key[2] == r2) or (key[0] == r2 and key[2] == r1)
            ]
            if pair_vars:
                model.add(sum(pair_vars) <= nb)
            ok = _solve_feasibility(model, self.timeout)
            print(f"    [{_label(ok)}]  max_binomes({r1}, {r2}) <= {nb}")

    def _drill_max_same_partenaire(self) -> None:
        """Teste chaque paire (r1, r2) soumise à max_same_partenaire individuellement."""
        c = self.c
        default = c.max_same_partenaire

        # Construire un modèle temporaire pour connaître les clés same_relay disponibles
        m_ref = _PartialModel()
        m_ref.build_partial(c, skip_max_same_partenaire=True)

        seen: set[frozenset] = set()
        pairs: list[tuple[str, str, int]] = []
        for (r1, _, r2, _) in m_ref.same_relay:
            key = frozenset({r1, r2})
            if key in seen:
                continue
            seen.add(key)
            lim1 = c.runners_data[r1].max_same_partenaire
            lim2 = c.runners_data[r2].max_same_partenaire
            individual = [v for v in (lim1, lim2) if v is not None]
            max_same = min(individual) if individual else default
            if max_same is not None:
                pairs.append((r1, r2, max_same))

        if not pairs:
            print("    Aucune contrainte max_same_partenaire effective.")
            return

        for r1, r2, max_same in pairs:
            m = _PartialModel()
            model = m.build_partial(c, skip_max_same_partenaire=True)
            pair_vars = [
                v for (a, _, b, _), v in m.same_relay.items()
                if (a == r1 and b == r2) or (a == r2 and b == r1)
            ]
            if len(pair_vars) > max_same:
                model.add(sum(pair_vars) <= max_same)
            ok = _solve_feasibility(model, self.timeout)
            print(f"    [{_label(ok)}]  max_same_partenaire({r1}, {r2}) <= {max_same}")

    def _analyse_combinations(self) -> None:
        """Teste des paires de familles désactivées simultanément."""
        print()
        print("Phase 3 — combinaisons de deux familles désactivées")
        print("-" * 65)

        families = [
            ("pinned",             dict(skip_fixed=True)),
            ("nuit_max",           dict(skip_night=True)),
            ("repos",              dict(skip_rest=True)),
            ("dispo",              dict(skip_availability=True)),
            ("solo",               dict(skip_solo=True)),
            ("pairings",           dict(skip_forced_pairings=True)),
            ("once_max",           dict(skip_once_max=True)),
            ("max_same_partenaire", dict(skip_max_same_partenaire=True)),
        ]

        found = False
        for i, (l1, k1) in enumerate(families):
            for l2, k2 in families[i + 1:]:
                combined = {**k1, **k2}
                m = _PartialModel()
                model = m.build_partial(self.c, **combined)
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

def analyse(constraints: RelayConstraints, timeout: float = 10.0) -> None:
    """Fonction utilitaire : crée un FeasibilityAnalyser et lance l'analyse."""
    FeasibilityAnalyser(constraints, timeout).run()


if __name__ == "__main__":
    from data import build_constraints
    c = build_constraints()
    analyse(c)
