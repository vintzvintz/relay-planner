"""
Construction du modèle CP-SAT — relais Lyon-Fessenheim.

Ce module expose :
- RelayModel : classe contenant le modèle CP-SAT et toutes ses variables
- build_model(constraints) : factory qui construit et retourne un RelayModel
- build_model_fixed_config(active_keys, optimal_score, constraints) : idem avec binômes fixés
"""

import math

from ortools.sat.python import cp_model

# Poids des binômes vs pénalité flex dans l'objectif.
# binome_sum_max ≈ 47,  flex_penalty_max ≈ 51  → coef=2 donne ~2x plus de poids aux binômes.
BINOME_WEIGHT = 2


class RelayModel:
    """Modèle CP-SAT complet : variables, contraintes et formatage de solution."""

    def __init__(self):
        self.model = None    # construit par build()

        # Variables CP-SAT (remplies par build())
        self.start = {}        # start[r][k]: IntVar
        self.end = {}          # end[r][k]: IntVar
        self.size = {}         # size[r][k]: IntVar
        self.same_relay = {}   # same_relay[(r,k,rp,kp)]: BoolVar
        self.relais_solo = {}         # relais_solo[r][k]: BoolVar
        self.relais_nuit = {}         # relais_nuit[r][k]: BoolVar
        self.relais_solo_interdit = {}  # relais_solo_interdit[r][k]: BoolVar (solo forbidden window)
        self._intervals_all = []  # [(r, k, sz_max, interval_var)]
        self._iv_index = {}       # (r, k) -> interval_var

    # ------------------------------------------------------------------
    # Construction du modèle
    # ------------------------------------------------------------------

    def build(self, constraints):
        assert not self.model, "RelayModel déja intialisé"
        self.model = cp_model.CpModel()

        self._add_variables(constraints)
        self._add_symmetry_breaking(constraints)
        self._add_fixed_relays(constraints)
        self._add_night_relay(constraints)
        self._add_solo_intervals(constraints)
        self._add_rest_constraints(constraints)
        self._add_availability(constraints)
        self._add_same_relay(constraints)
        self._add_pause_constraints(constraints)
        self._add_coverage(constraints)
        self._add_inter_runner_no_overlap(constraints)
        self._add_solo_constraints(constraints)
        self._add_forced_pairings(constraints)
        self._add_once_max(constraints)
        self._add_max_same_partenaire(constraints)
        return self

    def _add_symmetry_breaking(self, constraints):
        """Brise la symétrie par permutation des relais identiques d'un même coureur.

        Pour chaque groupe de relais partageant exactement le même descripteur
        (size, window, non pinnés, non partagés), impose start[r][k] <= start[r][k']
        pour toute paire consécutive k < k' au sein du groupe.
        """
        c = constraints
        model = self.model
        sym_lines = []
        for r in c.runners:
            eligible_groups: dict[tuple, list[int]] = {}
            for k, spec in enumerate(c.runners_data[r].relais):
                if spec.pinned is not None or spec.paired_with is not None:
                    continue
                window_key = (
                    tuple(tuple(iv) for iv in spec.window)
                    if spec.window is not None
                    else None
                )
                key = (frozenset(spec.size), window_key)
                eligible_groups.setdefault(key, []).append(k)

            factor = math.prod(
                math.factorial(len(v)) for v in eligible_groups.values() if len(v) >= 2
            )
            if factor > 1:
                sym_lines.append((r, factor))
            for indices in eligible_groups.values():
                for i in range(len(indices) - 1):
                    k, kp = indices[i], indices[i + 1]
                    model.add(self.start[r][k] <= self.start[r][kp])
        if sym_lines:
            total = math.prod(f for _, f in sym_lines)
            print("Symétries brisées (facteur de réduction) :")
            for r, f in sym_lines:
                print(f"  {r} : ×{f}")
            print(f"  total : ×{total}")

    def _add_fixed_relays(self, constraints):
        """Fixe start et size des relais dont pinned[k] n'est pas None."""
        model = self.model
        for r, coureur in constraints.runners_data.items():
            for k, spec in enumerate(coureur.relais):
                if spec.pinned is None:
                    continue
                model.add(self.start[r][k] == spec.pinned)
                model.add(self.size[r][k] == max(spec.size))

    def _add_variables(self, constraints):
        """Crée les variables start/end/size et intervalles pour chaque relais."""
        c = constraints
        model = self.model
        for r in c.runners:
            self.start[r], self.end[r], self.size[r] = [], [], []
            runner_ivs = []
            coureur = c.runners_data[r]
            for k, spec in enumerate(coureur.relais):
                sizes = spec.size
                sz_lo = min(sizes)
                s = model.new_int_var(0, c.nb_segments - sz_lo, f"s_{r}_{k}")
                domain = cp_model.Domain.from_values(sorted(sizes))
                sz_var = model.new_int_var_from_domain(domain, f"sz_{r}_{k}")
                e = model.new_int_var(sz_lo, c.nb_segments, f"e_{r}_{k}")
                model.add(e == s + sz_var)
                iv = model.new_interval_var(s, sz_var, e, f"iv_{r}_{k}")
                self.start[r].append(s)
                self.end[r].append(e)
                self.size[r].append(sz_var)
                self._intervals_all.append((r, k, max(sizes), iv))
                self._iv_index[(r, k)] = iv
                runner_ivs.append(iv)

    def _add_night_relay(self, constraints):
        """Crée les variables night_relay[r][k] et applique la contrainte au plus 1 nuit."""
        c = constraints
        model = self.model
        seg_night_list = sorted(c.night_segments)
        for r in c.runners:
            self.relais_nuit[r] = []
            for k, spec in enumerate(c.runners_data[r].relais):
                # Pour le calcul des starts possibles la nuit, on utilise la taille minimale
                # du domaine (un relais court peut quand même commencer la nuit).
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

        for r in c.runners:
            rd = c.runners_data[r]
            nuit_max = c._resolved_nuit_max(rd)
            if nuit_max < len(rd.relais):
                model.add(sum(self.relais_nuit[r]) <= nuit_max)

    def _add_solo_intervals(self, constraints):
        """Crée relais_solo_interdit[r][k] : vrai si le relais démarre hors de la plage solo autorisée."""
        c = constraints
        if c.solo_autorise_debut is None:
            for r in c.runners:
                self.relais_solo_interdit[r] = [
                    self.model.new_constant(0) for _ in c.runners_data[r].relais
                ]
            return
        model = self.model
        seg_forbidden_list = sorted(c.solo_forbidden_segments)
        for r in c.runners:
            self.relais_solo_interdit[r] = []
            for k, spec in enumerate(c.runners_data[r].relais):
                sizes = spec.size
                sz_lo, sz_hi = min(sizes), max(sizes)
                forbidden_starts = sorted(
                    set(
                        n - off
                        for n in seg_forbidden_list
                        for off in range(sz_hi)
                        if 0 <= n - off <= c.nb_segments - sz_lo
                    )
                )
                rsi = model.new_bool_var(f"rsi_{r}_{k}")
                if not forbidden_starts:
                    model.add(rsi == 0)
                else:
                    fd = cp_model.Domain.from_values(forbidden_starts)
                    dd = fd.complement().intersection_with(
                        cp_model.Domain(0, c.nb_segments - sz_lo)
                    )
                    model.add_linear_expression_in_domain(self.start[r][k], fd).only_enforce_if(rsi)
                    if not dd.is_empty():
                        model.add_linear_expression_in_domain(
                            self.start[r][k], dd
                        ).only_enforce_if(~rsi)
                    else:
                        model.add(rsi == 1)
                self.relais_solo_interdit[r].append(rsi)

    def _add_rest_constraints(self, constraints):
        """Repos minimum entre relais consécutifs d'un même coureur.

        Dans le modèle espace-temps, les pauses sont encodées comme des segments inactifs.
        Le gap entre end[ka] et start[kb] inclut automatiquement les pauses intercalées,
        donc la contrainte est simplement : end[ka] + repos <= start[kb].

        La disjonction (k avant k') OU (k' avant k) est gérée par un BoolVar d'ordre.
        """
        c = constraints
        model = self.model
        for r in c.runners:
            rd = c.runners_data[r]
            repos_jour = c._resolved_repos_jour(rd)
            repos_nuit = c._resolved_repos_nuit(rd)
            delta = repos_nuit - repos_jour
            n = len(rd.relais)
            for k in range(n):
                for kp in range(k + 1, n):
                    order = model.new_bool_var(f"ord_{r}_{k}_{kp}")

                    for ka, kb in [(k, kp), (kp, k)]:
                        b_fwd = order if (ka == k) else ~order
                        repos = repos_jour + delta * self.relais_nuit[r][ka]
                        model.add(
                            self.end[r][ka] + repos <= self.start[r][kb]
                        ).only_enforce_if(b_fwd)

    def _add_availability(self, constraints):
        """Applique les fenêtres de placement par relais et les affectations fixes."""
        c = constraints
        model = self.model

        # Fenêtres par relais : start+end dans l'un des intervalles.
        for r, coureur in c.runners_data.items():
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


    @staticmethod
    def _feasible_start_ranges(spec, nb_segments: int) -> list[tuple[int, int]]:
        """Retourne la liste des plages de start possibles pour un relais.

        Chaque plage est [ws, we - size_min] (un start valide doit laisser la place au relais).
        Si window=None, une seule plage couvre tout le parcours.
        Les plages vides (ws > we - size_min) sont ignorées.
        """
        size_min = min(spec.size)
        if spec.window is None:
            return [(0, nb_segments - size_min)]
        return [
            (ws, we - size_min)
            for ws, we in spec.window
            if ws <= we - size_min
        ]

    @staticmethod
    def _ranges_overlap(ranges_a: list[tuple[int, int]], ranges_b: list[tuple[int, int]]) -> bool:
        """Vérifie si deux listes de plages [lo, hi] ont un segment en commun."""
        for lo_a, hi_a in ranges_a:
            for lo_b, hi_b in ranges_b:
                if max(lo_a, lo_b) <= min(hi_a, hi_b):
                    return True
        return False

    def _add_same_relay(self, constraints):
        """Crée les variables same_relay pour les binômes potentiels.

        Deux relais (r,k) et (rp,kp) peuvent former un binôme si :
        - leurs domaines de taille se chevauchent (intersection non vide), ET
        - leurs plages de start feasibles se chevauchent (compatibilité temporelle).
        Quand b=1 : même start ET même taille effective.

        Variante fixed : quand les deux relais ont une taille fixe, seuls ceux
        de même taille peuvent former un binôme ; la contrainte size==size et
        le bloc allow_flex_flex sont inutiles.
        """
        c = constraints
        model = self.model
        n_runners = len(c.runners)
        for ri, r in enumerate(c.runners):
            for k, spec_r in enumerate(c.runners_data[r].relais):
                lo_r, hi_r = min(spec_r.size), max(spec_r.size)
                fixed_r = lo_r == hi_r
                starts_r = self._feasible_start_ranges(spec_r, c.nb_segments)
                for rpi in range(ri + 1, n_runners):
                    rp = c.runners[rpi]
                    if not c.is_compatible(r, rp):
                        continue
                    for kp, spec_rp in enumerate(c.runners_data[rp].relais):
                        lo_rp, hi_rp = min(spec_rp.size), max(spec_rp.size)
                        fixed_rp = lo_rp == hi_rp
                        both_fixed = fixed_r and fixed_rp

                        if both_fixed:
                            # Tailles fixes différentes → binôme impossible
                            if hi_r != hi_rp:
                                continue
                        else:
                            # Domaines se chevauchent ?
                            if max(lo_r, lo_rp) > min(hi_r, hi_rp):
                                continue

                        # Plages de start temporellement compatibles ?
                        starts_rp = self._feasible_start_ranges(spec_rp, c.nb_segments)
                        if not self._ranges_overlap(starts_r, starts_rp):
                            continue

                        key = (r, k, rp, kp)
                        b = model.new_bool_var(f"sr_{r}_{k}_{rp}_{kp}")
                        self.same_relay[key] = b

                        # Même start
                        model.add(self.start[r][k] == self.start[rp][kp]).only_enforce_if(b)

                        if not both_fixed:
                            # Même taille effective (dans l'intersection des domaines)
                            model.add(self.size[r][k] == self.size[rp][kp]).only_enforce_if(b)

                            # Quand allow_flex_flex=False : binôme flex+flex forcé aux tailles max
                            both_flex = not fixed_r and not fixed_rp
                            if both_flex and not c.allow_flex_flex:
                                model.add(self.size[r][k] == hi_r).only_enforce_if(b)
                                model.add(self.size[rp][kp] == hi_rp).only_enforce_if(b)

                        # No-overlap quand ~b
                        order = model.new_bool_var(f"ord_{r}_{k}_{rp}_{kp}")
                        model.add(
                            self.start[r][k] + self.size[r][k] <= self.start[rp][kp]
                        ).only_enforce_if([~b, order])
                        model.add(
                            self.start[rp][kp] + self.size[rp][kp] <= self.start[r][k]
                        ).only_enforce_if([~b, ~order])


    def _add_pause_constraints(self, constraints):
        """Interdit tout relais qui chevaucherait une plage inactive (pause).

        Pour chaque plage inactive [a, b) et chaque relais : end <= a OU start >= b.
        """
        c = constraints
        if not c.inactive_ranges:
            return
        model = self.model
        for i, (a, b) in enumerate(c.inactive_ranges):
            for r in c.runners:
                for k in range(len(c.runners_data[r].relais)):
                    bv = model.new_bool_var(f"pause_{i}_{r}_{k}")
                    model.add(self.end[r][k] <= a).only_enforce_if(bv)
                    model.add(self.start[r][k] >= b).only_enforce_if(~bv)

    def _add_coverage(self, constraints):
        """Contrainte de couverture : chaque segment couvert par 1 ou 2 relais.

        Formulation étendue : un BoolVar par (relais, segment actif) indique si le
        relais couvre ce segment.  Plus verbeuse qu'une contrainte globale sur les
        tailles, mais fournit une relaxation LP bien plus serrée qui guide
        efficacement la recherche — même quand toutes les tailles sont fixes.
        """
        c = constraints
        model = self.model
        all_ivs = [iv for _, _, _, iv in self._intervals_all]
        all_demand = [1 for _ in self._intervals_all]
        model.add_cumulative(all_ivs, all_demand, 2)

        for s in c.active_segments:
            covers_s = []
            for r in c.runners:
                for k in range(len(c.runners_data[r].relais)):
                    b = model.new_bool_var(f"c_{r}_{k}_{s}")
                    b_start_le_s = model.new_bool_var(f"c_sle_{r}_{k}_{s}")
                    b_end_gt_s = model.new_bool_var(f"c_egt_{r}_{k}_{s}")
                    model.add(self.start[r][k] <= s).only_enforce_if(b_start_le_s)
                    model.add(self.start[r][k] > s).only_enforce_if(~b_start_le_s)
                    model.add(self.end[r][k] >= s + 1).only_enforce_if(b_end_gt_s)
                    model.add(self.end[r][k] < s + 1).only_enforce_if(~b_end_gt_s)
                    model.add_bool_and([b_start_le_s, b_end_gt_s]).only_enforce_if(b)
                    model.add_bool_or([~b_start_le_s, ~b_end_gt_s]).only_enforce_if(~b)
                    covers_s.append(b)
            model.add(sum(covers_s) >= 1)

    def _add_inter_runner_no_overlap(self, constraints):
        """Force la disjonction entre relais de coureurs différents non binômables."""
        model = self.model
        c = constraints
        n_runners = len(c.runners)
        for ri, r in enumerate(c.runners):
            for k in range(len(c.runners_data[r].relais)):
                iv_rk = self._iv_index[(r, k)]
                for rpi in range(ri + 1, n_runners):
                    rp = c.runners[rpi]
                    for kp in range(len(c.runners_data[rp].relais)):
                        iv_rpkp = self._iv_index[(rp, kp)]
                        key = (r, k, rp, kp)
                        key_rev = (rp, kp, r, k)
                        if key in self.same_relay or key_rev in self.same_relay:
                            continue
                        model.add_no_overlap([iv_rk, iv_rpkp])

    def _add_solo_constraints(self, constraints):
        """Crée relais_solo[r][k] et limite à au plus 1 solo par coureur.

        Pour un relais flexible en solo, force la taille à req (pas de réduction sans binôme).
        """
        c = constraints
        model = self.model
        for r in c.runners:
            self.relais_solo[r] = []
            coureur = c.runners_data[r]
            for k, spec in enumerate(coureur.relais):
                partners = [
                    bv
                    for key, bv in self.same_relay.items()
                    if (key[0] == r and key[1] == k) or (key[2] == r and key[3] == k)
                ]
                b = model.new_bool_var(f"solo_{r}_{k}")
                if partners:
                    model.add_bool_or(partners).only_enforce_if(~b)
                    model.add_bool_and([~p for p in partners]).only_enforce_if(b)
                else:
                    model.add(b == 1)
                self.relais_solo[r].append(b)
                req = max(spec.size)
                # Flexible en solo → taille nominale obligatoire
                if len(spec.size) > 1:
                    model.add(self.size[r][k] == req).only_enforce_if(b)
                # Solo interdit si taille nominale > solo_max_size
                if req > c.solo_max_size:
                    model.add(self.size[r][k] <= c.solo_max_size).only_enforce_if(b)

        for r in c.runners:
            model.add(sum(self.relais_solo[r]) <= c.runner_solo_max[r])
            for k in range(len(c.relay_sizes[r])):
                model.add(self.relais_solo[r][k] + self.relais_solo_interdit[r][k] <= 1)

    def _add_forced_pairings(self, constraints):
        """Force les pairings explicites (same_relay == 1) déclarés via SharedRelay sans window."""
        model = self.model
        runner_idx = {r: i for i, r in enumerate(constraints.runners)}
        for r1, k1, r2, k2 in constraints.paired_relays:
            key = (r1, k1, r2, k2) if runner_idx[r1] < runner_idx[r2] else (r2, k2, r1, k1)
            bv = self.same_relay.get(key)
            if bv is not None:
                model.add(bv == 1)
            else:
                print(f"AVERTISSEMENT: pas de variable same_relay pour {r1}[{k1}]-{r2}[{k2}]")


    def _add_once_max(self, constraints):
        """Au plus 1 binôme entre chaque paire déclarée via once_max."""
        model = self.model
        for r1, r2, nb in constraints.once_max:
            pair_vars = [
                bv
                for key, bv in self.same_relay.items()
                if (key[0] == r1 and key[2] == r2) or (key[0] == r2 and key[2] == r1)
            ]
            if pair_vars:
                model.add(sum(pair_vars) <= nb)
            else:
                print(f"AVERTISSEMENT add_max_binomes: aucun binôme possible {r1}-{r2}")

    def _add_max_same_partenaire(self, constraints):
        """Limite le nombre de binômes entre chaque paire de coureurs.

        La limite retenue pour une paire (r1, r2) est le min des limites individuelles
        (surcharge par coureur via set_max_same_partenaire()) ou la limite globale par défaut.
        Si aucune limite n'est définie pour la paire, aucune contrainte n'est ajoutée.
        """
        c = constraints
        default = c.max_same_partenaire
        model = self.model
        seen: set[frozenset] = set()
        for (r1, _, r2, _) in self.same_relay:
            key = frozenset({r1, r2})
            if key in seen:
                continue
            seen.add(key)
            lim1 = c.runners_data[r1].max_same_partenaire
            lim2 = c.runners_data[r2].max_same_partenaire
            # Si au moins une surcharge individuelle est définie, elle prend le dessus sur le défaut.
            # La limite effective est le min des surcharges présentes (le coureur le plus restrictif
            # l'emporte), ou le défaut global si aucune surcharge n'est définie.
            individual = [v for v in (lim1, lim2) if v is not None]
            max_same = min(individual) if individual else default
            if max_same is None:
                continue
            pair_vars = [
                v for (a, _, b, _), v in self.same_relay.items()
                if (a == r1 and b == r2) or (a == r2 and b == r1)
            ]
            if len(pair_vars) > max_same:
                model.add(sum(pair_vars) <= max_same)

    # ------------------------------------------------------------------
    # Fonctions d'évaluation des solutions
    # ------------------------------------------------------------------

    def _objective_expr(self, constraints):
        """BINOME_WEIGHT * binome_sum - flex_penalty.

        binome_sum  = somme pondérée des binômes actifs (poids = compat_score).
        flex_penalty = sum(sz_max - size[r][k]) sur les relais flex uniquement.
        Sans relais flex, la pénalité est nulle et l'objectif se réduit à la
        somme pondérée des binômes.
        """
        binome_terms = [
            constraints.compat_score(r, rp) * var
            for (r, _k, rp, _kp), var in self.same_relay.items()
        ]
        binome_sum = cp_model.LinearExpr.sum(binome_terms)
        flex_penalty = sum(
            max(spec.size) - self.size[r][k]
            for r, coureur in constraints.runners_data.items()
            for k, spec in enumerate(coureur.relais)
            if len(spec.size) > 1
        )
        return BINOME_WEIGHT * binome_sum - flex_penalty

    def add_optimisation_func(self, constraints):
        """Ajoute la fonction que le solveur va optimiser."""
        self.model.maximize(self._objective_expr(constraints))
        return self

    def add_min_score(self, constraints, score):
        """Contraint le score à être >= score."""
        self.model.add(self._objective_expr(constraints) >= score)
        return self


# ------------------------------------------------------------------
# Factory functions
# ------------------------------------------------------------------

def build_model(constraints):
    """Construit et retourne un RelayModel avec toutes les contraintes."""
    relay_model = RelayModel()
    relay_model.build(constraints)
    return relay_model

# test de construction du modèle, sans résolution
if __name__ == "__main__":
    from data import build_constraints
    c = build_constraints()
    m = build_model(c)
