"""
Construction du modèle CP-SAT — relais Lyon-Fessenheim.

Ce module expose :
- RelayModel : classe contenant le modèle CP-SAT et toutes ses variables
- build_model(constraints) : factory qui construit et retourne un RelayModel
- build_model_fixed_config(active_keys, optimal_score, constraints) : idem avec binômes fixés
"""

from ortools.sat.python import cp_model

class RelayModel:
    """Modèle CP-SAT complet : variables, contraintes et formatage de solution."""

    def __init__(self):
        self.model = None    # construit par build()
        # self.solver = None   # Attaché après résolution

        # Variables CP-SAT (remplies par build())
        self.start = {}        # start[r][k]: IntVar
        self.end = {}          # end[r][k]: IntVar
        self.size = {}         # size[r][k]: IntVar
        self.same_relay = {}   # same_relay[(r,k,rp,kp)]: BoolVar
        self.relais_solo = {}  # relais_solo[r][k]: BoolVar
        self.relais_nuit = {}  # relais_nuit[r][k]: BoolVar
        self._intervals_all = []  # [(r, k, sz_max, interval_var)]
        self._cut_count = 0

    # ------------------------------------------------------------------
    # Construction du modèle
    # ------------------------------------------------------------------

    def build(self, constraints):
        assert not self.model, "RelayModel déja intialisé"
        self.model = cp_model.CpModel()

        self._add_variables(constraints)
        self._add_night_relay(constraints)
        self._add_rest_constraints(constraints)
        self._add_availability(constraints)
        self._add_same_relay(constraints)
        self._add_coverage(constraints)
        self._add_inter_runner_no_overlap(constraints)
        self._add_solo_constraints(constraints)
        self._add_binomes_min_max(constraints)
        return self

    def _size_domain(self, r, sz_max, constraints):
        """Retourne le domaine de taille pour le relais de taille déclarée sz_max du coureur r.

        - Coureur non-flexible : domaine singleton [sz_max].
        - Coureur flexible     : sz_max + tailles des partenaires non-flexibles compatibles
                                strictement inférieures à sz_max et >= MIN_RELAY_SIZE.
        """
        c = constraints
        if not c.runners_data[r].flexible:
            return [sz_max]
        partner_sizes = set()
        for rp, cp in c.runners_data.items():
            if rp == r or cp.flexible:
                continue
            if not c.is_compatible(r, rp):
                continue
            for sz_p in cp.relais:
                if c.min_relay_size <= sz_p < sz_max:
                    partner_sizes.add(sz_p)
        return sorted(partner_sizes | {sz_max})

    def _add_variables(self, constraints):
        """Crée les variables start/end/size et intervalles pour chaque relais.

        size[r][k] est toujours une variable CP-SAT. Pour les coureurs non-flexibles,
        le domaine est un singleton. Pour les flexibles, le domaine inclut les tailles
        des partenaires non-flexibles compatibles.
        """
        c = constraints
        model = self.model
        for r in c.runners:
            self.start[r], self.end[r], self.size[r] = [], [], []
            runner_ivs = []
            coureur = c.runners_data[r]
            for k, sz_max in enumerate(coureur.relais):
                s = model.new_int_var(0, c.nb_segments - c.min_relay_size, f"s_{r}_{k}")
                domain_vals = self._size_domain(r, sz_max, constraints)
                sz_var = model.new_int_var_from_domain(
                    cp_model.Domain.from_values(domain_vals), f"sz_{r}_{k}"
                )
                e = model.new_int_var(c.min_relay_size, c.nb_segments, f"e_{r}_{k}")
                model.add(e == s + sz_var)
                iv = model.new_interval_var(s, sz_var, e, f"iv_{r}_{k}")
                self.start[r].append(s)
                self.end[r].append(e)
                self.size[r].append(sz_var)
                self._intervals_all.append((r, k, sz_max, iv))
                runner_ivs.append(iv)
            if len(runner_ivs) > 1:
                model.add_no_overlap(runner_ivs)

    def _add_night_relay(self, constraints):
        """Crée les variables night_relay[r][k] et applique la contrainte au plus 1 nuit."""
        c = constraints
        model = self.model
        seg_night_list = sorted(c.night_segments)
        for r in c.runners:
            self.relais_nuit[r] = []
            for k, sz in enumerate(c.runners_data[r].relais):
                night_starts = sorted(
                    set(
                        n - off
                        for n in seg_night_list
                        for off in range(sz)
                        if 0 <= n - off <= c.nb_segments - sz
                    )
                )
                rhn = model.new_bool_var(f"rn_{r}_{k}")
                if not night_starts:
                    model.add(rhn == 0)
                else:
                    nd = cp_model.Domain.from_values(night_starts)
                    dd = nd.complement().intersection_with(
                        cp_model.Domain(0, c.nb_segments - sz)
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
            if rd.nuit_max < len(rd.relais):
                model.add(sum(self.relais_nuit[r]) <= rd.nuit_max)

    def _add_rest_constraints(self, constraints):
        """Repos minimum entre toute paire de relais d'un même coureur."""
        c = constraints
        model = self.model
        for r in c.runners:
            n_relays = len(c.runners_data[r].relais)
            if n_relays < 2:
                continue
            rd = c.runners_data[r]
            for k in range(n_relays):
                for kp in range(k + 1, n_relays):
                    k_before_kp = model.new_bool_var(f"bef_{r}_{k}_{kp}")
                    k_day_then_kp = model.new_bool_var(f"bkd_{r}_{k}_{kp}")
                    k_night_then_kp = model.new_bool_var(f"bkn_{r}_{k}_{kp}")
                    model.add_bool_and([k_before_kp, ~self.relais_nuit[r][k]]).only_enforce_if(k_day_then_kp)
                    model.add_bool_or([~k_before_kp, self.relais_nuit[r][k]]).only_enforce_if(~k_day_then_kp)
                    model.add_bool_and([k_before_kp, self.relais_nuit[r][k]]).only_enforce_if(k_night_then_kp)
                    model.add_bool_or([~k_before_kp, ~self.relais_nuit[r][k]]).only_enforce_if(~k_night_then_kp)
                    model.add(self.end[r][k] + rd.repos_jour <= self.start[r][kp]).only_enforce_if(k_day_then_kp)
                    model.add(self.end[r][k] + rd.repos_nuit <= self.start[r][kp]).only_enforce_if(k_night_then_kp)
                    kp_day_then_k = model.new_bool_var(f"bkpd_{r}_{k}_{kp}")
                    kp_night_then_k = model.new_bool_var(f"bkpn_{r}_{k}_{kp}")
                    model.add_bool_and([~k_before_kp, ~self.relais_nuit[r][kp]]).only_enforce_if(kp_day_then_k)
                    model.add_bool_or([k_before_kp, self.relais_nuit[r][kp]]).only_enforce_if(~kp_day_then_k)
                    model.add_bool_and([~k_before_kp, self.relais_nuit[r][kp]]).only_enforce_if(kp_night_then_k)
                    model.add_bool_or([k_before_kp, ~self.relais_nuit[r][kp]]).only_enforce_if(~kp_night_then_k)
                    model.add(self.end[r][kp] + rd.repos_jour <= self.start[r][k]).only_enforce_if(kp_day_then_k)
                    model.add(self.end[r][kp] + rd.repos_nuit <= self.start[r][k]).only_enforce_if(kp_night_then_k)

    def _add_availability(self, constraints):
        """Applique les disponibilités partielles et affectations fixes"""
        c = constraints
        model = self.model
        for r, coureur in c.runners_data.items():
            if not coureur.dispo:
                continue
            for k in range(len(coureur.relais)):
                # start[r][k] must fall within one of the availability windows
                window_bools = []
                for i, (avail_start, avail_end) in enumerate(coureur.dispo):
                    b = model.new_bool_var(f"avail_{r}_{k}_{i}")
                    model.add(self.start[r][k] >= avail_start).only_enforce_if(b)
                    model.add(self.end[r][k] <= avail_end).only_enforce_if(b)
                    window_bools.append(b)
                model.add_bool_or(window_bools)

        # Pinned binômes: force a pair to share a relay covering the window.
        pair_relay_counters = {}
        for r1, r2, window_start, window_end in c.binomes_pinned:
            pair_key = (r1, r2)
            idx = pair_relay_counters.get(pair_key, 0)
            min_relay_size = window_end - window_start

            r1_relays = [k for k, sz in enumerate(c.runners_data[r1].relais) if sz >= min_relay_size]
            r2_relays = [k for k, sz in enumerate(c.runners_data[r2].relais) if sz >= min_relay_size]
            if idx < len(r1_relays) and idx < len(r2_relays):
                k1, k2 = r1_relays[idx], r2_relays[idx]
                sz1 = c.runners_data[r1].relais[k1]
                model.add(self.start[r1][k1] <= window_start)
                model.add(self.start[r1][k1] >= window_end - sz1)
                model.add(self.start[r2][k2] == self.start[r1][k1])
            pair_relay_counters[pair_key] = idx + 1

        # Pinned runners: force a single runner to have a relay covering the window.
        for r, coureur in c.runners_data.items():
            for idx, window in enumerate(coureur.pinned_segments):
                window_start, window_end = window[0], window[1]
                min_relay_size = window_end - window_start

                r_relays = [k for k, sz in enumerate(coureur.relais) if sz >= min_relay_size]
                if idx < len(r_relays):
                    k = r_relays[idx]
                    sz = coureur.relais[k]
                    model.add(self.start[r][k] <= window_start)
                    model.add(self.start[r][k] >= window_end - sz)

    def _add_same_relay(self, constraints):
        """Crée les variables same_relay pour les binômes potentiels.

        Cas flexible×non-flexible : même start ET size[flexible] == sz_non_flexible.
        Cas non-flex×non-flex ou flex×flex : même start ET sz_r == sz_rp (taille déclarée).
        """
        c = constraints
        model = self.model
        n_runners = len(c.runners)
        for ri, r in enumerate(c.runners):
            r_flex = c.runners_data[r].flexible
            for k, sz_r in enumerate(c.runners_data[r].relais):
                for rpi in range(ri + 1, n_runners):
                    rp = c.runners[rpi]
                    if not c.is_compatible(r, rp):
                        continue
                    rp_flex = c.runners_data[rp].flexible
                    for kp, sz_rp in enumerate(c.runners_data[rp].relais):
                        # Détermine si ce binôme est potentiellement possible
                        if r_flex and not rp_flex:
                            # flexible r peut s'aligner sur sz_rp si sz_rp <= sz_r et >= MIN
                            if sz_rp > sz_r or sz_rp < c.min_relay_size:
                                continue
                        elif rp_flex and not r_flex:
                            # flexible rp peut s'aligner sur sz_r si sz_r <= sz_rp et >= MIN
                            if sz_r > sz_rp or sz_r < c.min_relay_size:
                                continue
                        else:
                            # non-flex×non-flex ou flex×flex : tailles déclarées identiques
                            if sz_r != sz_rp:
                                continue

                        key = (r, k, rp, kp)
                        b = model.new_bool_var(f"sr_{r}_{k}_{rp}_{kp}")
                        self.same_relay[key] = b

                        # Même start
                        model.add(self.start[r][k] == self.start[rp][kp]).only_enforce_if(b)

                        # Même taille effective
                        if r_flex and not rp_flex:
                            model.add(self.size[r][k] == sz_rp).only_enforce_if(b)
                        elif rp_flex and not r_flex:
                            model.add(self.size[rp][kp] == sz_r).only_enforce_if(b)
                        elif r_flex and rp_flex:
                            model.add(self.size[r][k] == self.size[rp][kp]).only_enforce_if(b)

                        # No-overlap quand ~b : start[r] >= end[rp] ou start[rp] >= end[r]
                        # i.e. start[r] - start[rp] >= sz_rp  ou  start[rp] - start[r] >= sz_r
                        diff = model.new_int_var(-c.nb_segments, c.nb_segments, f"d_{r}_{k}_{rp}_{kp}")
                        model.add(diff == self.start[r][k] - self.start[rp][kp])
                        no_overlap_dom = cp_model.Domain(-c.nb_segments, -sz_r).union_with(
                            cp_model.Domain(sz_rp, c.nb_segments)
                        )
                        model.add_linear_expression_in_domain(diff, no_overlap_dom).only_enforce_if(~b)


    def _add_coverage(self, constraints):
        """Contrainte de couverture : chaque segment couvert par 1 ou 2 relais."""
        c = constraints
        model = self.model
        all_ivs = [iv for _, _, _, iv in self._intervals_all]
        all_demand = [1 for _ in self._intervals_all]
        model.add_cumulative(all_ivs, all_demand, 2)

        for s in range(c.nb_segments):
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
                iv_rk = self._intervals_all[
                    [i for i, (rr, kk, _, _) in enumerate(self._intervals_all) if rr == r and kk == k][0]
                ][3]
                for rpi in range(ri + 1, n_runners):
                    rp = c.runners[rpi]
                    for kp in range(len(c.runners_data[rp].relais)):
                        iv_rpkp = self._intervals_all[
                            [i for i, (rr, kk, _, _) in enumerate(self._intervals_all) if rr == rp and kk == kp][0]
                        ][3]
                        key = (r, k, rp, kp)
                        key_rev = (rp, kp, r, k)
                        if key in self.same_relay or key_rev in self.same_relay:
                            continue
                        model.add_no_overlap([iv_rk, iv_rpkp])

    def _add_solo_constraints(self, constraints):
        """Crée relais_solo[r][k] et limite à au plus 1 solo par coureur.

        Pour un coureur flexible en solo, force la taille à sz_max (pas de réduction
        sans binôme).
        """
        c = constraints
        model = self.model
        for r in c.runners:
            self.relais_solo[r] = []
            coureur = c.runners_data[r]
            for k, sz_max in enumerate(coureur.relais):
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
                # Flexible en solo → taille déclarée obligatoire
                if coureur.flexible:
                    model.add(self.size[r][k] == sz_max).only_enforce_if(b)

        for r in c.runners:
            model.add(sum(self.relais_solo[r]) <= c.runner_solo_max[r])
            for k in range(len(c.relay_sizes[r])):
                model.add(self.relais_solo[r][k] + self.relais_nuit[r][k] <= 1)

    def _add_binomes_min_max(self, constraints):
        """
        ajoute les requetes de relais en binome once_min et once_max
        """
        # au moins un relais en binôme pour chaque paire obligatoire.
        model = self.model
        for r1, r2 in constraints.binomes_once_min:
            pair_vars = self._pair_vars(r1, r2)
            if pair_vars:
                model.add_bool_or(pair_vars)
            else:
                print(f"AVERTISSEMENT: aucun binôme possible {r1}-{r2}")

        # au plus un relais en binôme pour chaque paire limitée
        model = self.model
        for r1, r2 in constraints.binomes_once_max:
            pair_vars = self._pair_vars(r1, r2)
            if pair_vars:
                model.add(sum(pair_vars) <= 1)
            else:
                print(f"AVERTISSEMENT: aucun binôme possible {r1}-{r2}")


    def _pair_vars(self, r1, r2):
        """Retourne les BoolVar same_relay pour la paire (r1, r2) dans les deux sens."""
        return [
            bv
            for key, bv in self.same_relay.items()
            if (key[0] == r1 and key[2] == r2) or (key[0] == r2 and key[2] == r1)
        ]

    def _weighted_binome_sum(self, constraints):
        return sum(
            constraints.compat_score(r, rp) * var
            for (r, _k, rp, _kp), var in self.same_relay.items()
        )

    def add_optimisation_func(self, constraints):
        """Ajoute la fonction que le solveur va optimiser."""
        self.model.maximize(self._weighted_binome_sum(constraints))

    def add_min_score(self, constraints, score):
        """Contraint le score pondéré des binômes actifs à être >= score."""
        self.model.add(self._weighted_binome_sum(constraints) >= score)

    def fix_binome_config(self, active_keys):
        """Fixe toutes les variables same_relay à la configuration donnée (phase 2)."""
        for key, bv in self.same_relay.items():
            if key in active_keys:
                self.model.add(bv == 1)
            else:
                self.model.add(bv == 0)

    def add_config_exclusion_cut(self, active_keys):
        """Ajoute une coupure excluant la configuration de binômes courante (phase 1).

        La prochaine solution devra différer sur au moins un binôme actif.
        """
        active_bvs = [bv for key, bv in self.same_relay.items() if key in active_keys]
        self.model.add_bool_or([~b for b in active_bvs])

    def add_schedule_exclusion_cut(self, solver, constraints):
        """Ajoute une coupure excluant le placement courant (phase 2).

        La prochaine solution devra différer sur au moins un start de relais.
        """
        cut_idx = self._cut_count
        self._cut_count += 1
        cut_lits = []
        for r in constraints.runners:
            for k in range(len(constraints.runners_data[r].relais)):
                val = solver.value(self.start[r][k])
                b = self.model.new_bool_var(f"cut_{cut_idx}_{r}_{k}")
                self.model.add(self.start[r][k] != val).only_enforce_if(b)
                self.model.add(self.start[r][k] == val).only_enforce_if(~b)
                cut_lits.append(b)
        self.model.add_bool_or(cut_lits)


# ------------------------------------------------------------------
# Factory functions
# ------------------------------------------------------------------

def build_model(constraints):
    """Construit et retourne un RelayModel avec toutes les contraintes."""
    relay_model = RelayModel()
    relay_model.build(constraints)
    return relay_model

def build_model_fixed_config(active_keys, constraints=None):
    """Construit un RelayModel avec les binômes fixés à la configuration donnée."""
    relay_model = build_model(constraints)
    for key, bv in relay_model.same_relay.items():
        if key in active_keys:
            relay_model.model.add(bv == 1)
        else:
            relay_model.model.add(bv == 0)
    return relay_model


# test unitaire
if __name__ == "__main__":
    from data import build_constraints
    c = build_constraints()
    m = build_model(c)
