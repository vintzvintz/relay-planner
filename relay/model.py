"""
relay/model.py

Modèle CP-SAT pour le planning à points de passage (waypoints).

Variables par relais (r, k) :
  start[r][k]    IntVar ∈ [0, P-2]  — indice du point de départ
  end[r][k]      IntVar ∈ [1, P-1]  — indice du point d'arrivée
  nb_arcs[r][k]  = end - start      — taille en arcs

Variables dérivées via AddElement sur les tables cumulatives :
  dist_start[r][k], dist_end[r][k], dist[r][k]   — distances en mètres
  time_start[r][k], time_end[r][k]                — temps en minutes
  flex[r][k]                                       — |dist - target_m|

Intervalles CP-SAT :
  iv[r][k] = NewIntervalVar(start, nb_arcs, end)

Objectif : maximise binômes pondérés (option : avec pénalité d'écart)
"""

from ortools.sat.python import cp_model

from .constraints import Constraints

class Model:
    """Modèle CP-SAT pour le planning à points de passage."""

    def __init__(self):
        self.model = None

        # Variables indexées par (runner_name, relay_index)
        self.start: dict[tuple[str, int], cp_model.IntVar] = {}
        self.end: dict[tuple[str, int], cp_model.IntVar] = {}
        self.nb_arcs_var: dict[tuple[str, int], cp_model.IntVar] = {}
        self.iv: dict[tuple[str, int], cp_model.IntervalVar] = {}

        # Variables dérivées distance / temps
        self.dist_start: dict[tuple[str, int], cp_model.IntVar] = {}
        self.dist_end: dict[tuple[str, int], cp_model.IntVar] = {}
        self.dist: dict[tuple[str, int], cp_model.IntVar] = {}
        self.time_start: dict[tuple[str, int], cp_model.IntVar] = {}
        self.time_end: dict[tuple[str, int], cp_model.IntVar] = {}
        self.flex: dict[tuple[str, int], cp_model.IntVar] = {}

        # BoolVars binômes
        self.same_relay: dict[tuple[str, int, str, int], cp_model.IntVar] = {}

        # BoolVars nuit / solo
        self.relais_nuit: dict[tuple[str, int], cp_model.IntVar] = {}
        self.relais_solo: dict[tuple[str, int], cp_model.IntVar] = {}

        # Intervalles temporels (minutes) pour no-overlap avec repos
        self.iv_time: dict[tuple[str, int], cp_model.IntervalVar] = {}
        self.iv_repos: dict[tuple[str, int], cp_model.IntervalVar] = {}
        self.repos_end: dict[tuple[str, int], cp_model.IntVar] = {}

        # Variables D+/D- mutualisées (créées à la demande par _ensure_dplus_vars)
        self.dp_s: dict[tuple[str, int], cp_model.IntVar] = {}
        self.dp_e: dict[tuple[str, int], cp_model.IntVar] = {}
        self.dm_s: dict[tuple[str, int], cp_model.IntVar] = {}
        self.dm_e: dict[tuple[str, int], cp_model.IntVar] = {}
        self._cumul_dp: list[int] | None = None
        self._cumul_dm: list[int] | None = None

    # Familles de contraintes disponibles pour build_without() dans les sous-classes.
    # L'ordre reflète les dépendances : same_relay avant solo/inter_runner,
    # night_relay avant rest_intervals.
    CONSTRAINT_FAMILIES = [
        "symmetry_breaking",
        "fixed_relays",
        "chained_relays",
        "pause_constraints",
        "coverage",
        "same_relay",        # requis par : solo, inter_runner_no_overlap, shared_relays, max_duos, max_same_partenaire
        "inter_runner_no_overlap",
        "night_relay",       # requis par : rest_intervals
        "solo",
        "rest_intervals",
        "availability",
        "shared_relays",
        "max_duos",
        "max_same_partenaire",
        "dplus_max",
    ]

    def build(self, c: Constraints) -> "Model":
        assert not self.model, "Modèle déja intialisé"
        self.model = cp_model.CpModel()

        c.validate()  # callback d'autovalidation des contraintes 
        self.add_variables(c)
        self.add_symmetry_breaking(c)
        self.add_fixed_relays(c)
        self.add_chained_relays(c)
        self.add_pause_constraints(c)
        self.add_coverage(c)
        self.add_same_relay(c)
        self.add_inter_runner_no_overlap(c)
        self.add_night_relay(c)
        self.add_solo_constraints(c)
        self.add_rest_intervals(c)
        self.add_availability(c)
        self.add_shared_relays(c)
        self.add_max_duos(c)
        self.add_max_same_partenaire(c)
        self.add_dplus_max_constraints(c)
        return self

    # ------------------------------------------------------------------
    # Variables (toujours appelé en premier, avant toute contrainte)
    # ------------------------------------------------------------------

    def add_variables(self, c: Constraints) -> None:
        P = c.nb_points
        for r, coureur in c.runners_data.items():
            for k, spec in enumerate(coureur.relais):
                max_arcs = c.nb_arcs

                s = self.model.new_int_var(0, P - 2, f"start_{r}_{k}")
                e = self.model.new_int_var(1, P - 1, f"end_{r}_{k}")
                na = self.model.new_int_var(1, max_arcs, f"nb_arcs_{r}_{k}")
                iv = self.model.new_interval_var(s, na, e, f"iv_{r}_{k}")
                self.model.add(e == s + na)

                self.start[(r, k)] = s
                self.end[(r, k)] = e
                self.nb_arcs_var[(r, k)] = na
                self.iv[(r, k)] = iv

                # Lookup distance via AddElement sur cumul_m
                ds = self.model.new_int_var(0, c.cumul_m[-1], f"ds_{r}_{k}")
                de = self.model.new_int_var(0, c.cumul_m[-1], f"de_{r}_{k}")
                self.model.add_element(s, c.cumul_m, ds)
                self.model.add_element(e, c.cumul_m, de)
                dist_var = self.model.new_int_var(0, c.cumul_m[-1], f"dist_{r}_{k}")
                self.model.add(dist_var == de - ds)
                self.dist_start[(r, k)] = ds
                self.dist_end[(r, k)] = de
                self.dist[(r, k)] = dist_var

                # Lookup temps via AddElement sur cumul_temps
                ts = self.model.new_int_var(0, c.cumul_temps[-1], f"ts_{r}_{k}")
                te = self.model.new_int_var(0, c.cumul_temps[-1], f"te_{r}_{k}")
                self.model.add_element(s, c.cumul_temps, ts)
                self.model.add_element(e, c.cumul_temps, te)
                self.time_start[(r, k)] = ts
                self.time_end[(r, k)] = te

                # Variable d'écart : flex >= |dist - target_m|
                flex = self.model.new_int_var(0, c.cumul_m[-1], f"flex_{r}_{k}")
                self.model.add(flex >= dist_var - spec.target_m)
                self.model.add(flex >= spec.target_m - dist_var)
                self.flex[(r, k)] = flex

                # Bornes de distance min/max
                if spec.min_m is not None:
                    self.model.add(dist_var >= spec.min_m)
                if spec.max_m is not None:
                    self.model.add(dist_var <= spec.max_m)

    # ------------------------------------------------------------------
    # Pauses : aucun relais ne peut traverser un arc pause
    # ------------------------------------------------------------------

    def add_pause_constraints(self, c: Constraints) -> None:
        """Interdit à tout relais de traverser un arc pause.

        Un arc pause ap a dist=0 et durée non nulle. Un relais qui le traverserait
        (start <= ap ET end >= ap+2) aurait une distance et un temps incorrects.
        On force : start > ap  OU  end <= ap+1.

        On encode b_after ↔ (start > ap) via les deux implications :
          b_after=1 → start > ap
          b_after=0 → start <= ap
        puis on contraint end <= ap+1 quand b_after=0 (relais avant la pause).
        """
        if not c.pause_arcs:
            return
        all_keys = [(r, k) for r, coureur in c.runners_data.items() for k in range(len(coureur.relais))]
        for ap in c.pause_arcs:
            for rk in all_keys:
                b_after = self.model.new_bool_var(f"pause_after_{rk[0]}_{rk[1]}_{ap}")
                # b_after = 1 ↔ start >= ap+1 (relais après la pause)
                self.model.add(self.start[rk] >= ap + 1).only_enforce_if(b_after)
                self.model.add(self.start[rk] <= ap).only_enforce_if(b_after.negated())
                # Si le relais est avant la pause, il doit se terminer sur le point de pause (end <= ap)
                # ce qui exclut l'arc pause (arc ap = point ap → point ap+1) du relais
                self.model.add(self.end[rk] <= ap).only_enforce_if(b_after.negated())

    # ------------------------------------------------------------------
    # D+/D- : tables cumulatives mutualisées
    # ------------------------------------------------------------------

    def _ensure_dplus_vars(self, c: Constraints, keys: list[tuple[str, int]] | None = None) -> None:
        """Construit (si absent) les tables cumul_dp/dm et les variables AddElement D+/D-.

        Les variables dp_s/dp_e/dm_s/dm_e sont créées une seule fois par (r, k) et
        réutilisées par add_dplus_max_constraints() et add_optimise_dplus().

        Parameters
        ----------
        keys : liste de (runner, k) pour lesquels créer les variables.
               Si None, crée pour tous les relais de c.runners_data.
        """
        if not c.parcours.has_profile:
            raise RuntimeError("_ensure_dplus_vars() requiert un profil altimétrique dans le Parcours.")

        if self._cumul_dp is None:
            self._cumul_dp, self._cumul_dm = c.cumul_dplus

        cumul_dp = self._cumul_dp
        cumul_dm = self._cumul_dm
        max_dp = cumul_dp[-1]
        max_dm = cumul_dm[-1]

        if keys is None:
            keys = [(r, k) for r, coureur in c.runners_data.items() for k in range(len(coureur.relais))]

        for rk in keys:
            if rk in self.dp_s:
                continue  # déjà créé
            r, k = rk
            dp_s = self.model.new_int_var(0, max_dp, f"dp_s_{r}_{k}")
            dp_e = self.model.new_int_var(0, max_dp, f"dp_e_{r}_{k}")
            dm_s = self.model.new_int_var(0, max_dm, f"dm_s_{r}_{k}")
            dm_e = self.model.new_int_var(0, max_dm, f"dm_e_{r}_{k}")
            self.model.add_element(self.start[rk], cumul_dp, dp_s)
            self.model.add_element(self.end[rk], cumul_dp, dp_e)
            self.model.add_element(self.start[rk], cumul_dm, dm_s)
            self.model.add_element(self.end[rk], cumul_dm, dm_e)
            self.dp_s[rk] = dp_s
            self.dp_e[rk] = dp_e
            self.dm_s[rk] = dm_s
            self.dm_e[rk] = dm_e

    # ------------------------------------------------------------------
    # dplus_max : borne sur D+ + D- par relais
    # ------------------------------------------------------------------

    def add_dplus_max_constraints(self, c: Constraints) -> None:
        """Borne D+ + D- par relais via AddElement sur les tables cumulatives du profil.

        Nécessite profil_csv= dans Constraints. No-op si aucun RelaySpec n'a dplus_max.
        Lève RuntimeError si profil_csv est absent et qu'un dplus_max est déclaré.
        """
        has_dplus = any(
            spec.dplus_max is not None
            for coureur in c.runners_data.values()
            for spec in coureur.relais
        )
        if not has_dplus:
            return
        if not c.parcours.has_profile:
            raise RuntimeError(
                "dplus_max requiert un profil altimétrique dans le Parcours."
            )

        keys = [
            (r, k)
            for r, coureur in c.runners_data.items()
            for k, spec in enumerate(coureur.relais)
            if spec.dplus_max is not None
        ]
        self._ensure_dplus_vars(c, keys)

        for r, coureur in c.runners_data.items():
            for k, spec in enumerate(coureur.relais):
                if spec.dplus_max is None:
                    continue
                rk = (r, k)
                self.model.add(
                    (self.dp_e[rk] - self.dp_s[rk]) + (self.dm_e[rk] - self.dm_s[rk]) <= spec.dplus_max
                )

    # ------------------------------------------------------------------
    # Couverture : chaque arc couvert 1 ou 2 fois
    # ------------------------------------------------------------------

    def add_coverage(self, c: Constraints) -> None:
        all_keys = [(r, k) for r, coureur in c.runners_data.items() for k in range(len(coureur.relais))]

        # AddCumulative(capacity=2) global sur tous les iv de points.
        # add_pause_constraints() garantit qu'aucun relais ne traverse une pause,
        # donc deux relais de segments différents ne peuvent jamais se chevaucher :
        # la capacité 2 est naturellement locale à chaque segment inter-pause.
        all_ivs = [self.iv[rk] for rk in all_keys]
        self.model.add_cumulative(all_ivs, [1] * len(all_ivs), 2)

        # Chaque arc réel (hors pauses) doit être couvert par au moins 1 relais
        for a in range(c.nb_arcs):
            if a in c.pause_arcs:
                continue
            covers = []
            for rk in all_keys:
                # b = 1 ssi start[r][k] <= a < end[r][k]
                b = self.model.new_bool_var(f"cov_{rk[0]}_{rk[1]}_{a}")
                b_start = self.model.new_bool_var(f"cov_s_{rk[0]}_{rk[1]}_{a}")
                b_end = self.model.new_bool_var(f"cov_e_{rk[0]}_{rk[1]}_{a}")
                self.model.add(self.start[rk] <= a).only_enforce_if(b_start)
                self.model.add(self.start[rk] > a).only_enforce_if(b_start.negated())
                self.model.add(self.end[rk] > a).only_enforce_if(b_end)
                self.model.add(self.end[rk] <= a).only_enforce_if(b_end.negated())
                self.model.add_bool_and([b_start, b_end]).only_enforce_if(b)
                self.model.add_bool_or([b_start.negated(), b_end.negated()]).only_enforce_if(b.negated())
                covers.append(b)
            self.model.add(sum(covers) >= 1)

    # ------------------------------------------------------------------
    # Binômes : même start ET même end
    # ------------------------------------------------------------------

    def add_same_relay(self, c: Constraints) -> None:
        runners = list(c.runners_data.keys())
        for i, r in enumerate(runners):
            for k in range(len(c.runners_data[r].relais)):
                for rp in runners[i + 1:]:
                    for kp in range(len(c.runners_data[rp].relais)):
                        if c.compat_score(r, rp) <= 0:
                            continue
                        key = (r, k, rp, kp)
                        b = self.model.new_bool_var(f"sr_{r}_{k}_{rp}_{kp}")
                        self.model.add(self.start[(r, k)] == self.start[(rp, kp)]).only_enforce_if(b)
                        self.model.add(self.end[(r, k)] == self.end[(rp, kp)]).only_enforce_if(b)
                        self.same_relay[key] = b

    # ------------------------------------------------------------------
    # Intervalles temporels de repos + no-overlap intra-coureur
    # ------------------------------------------------------------------

    def add_rest_intervals(self, c: Constraints) -> None:
        """Crée les intervalles temporels de course et de repos par relais,
        puis impose un no-overlap (course + repos) par coureur.

        Les intervalles iv_time[r][k] couvrent [time_start, time_end] en minutes.
        Les intervalles iv_repos[r][k] commencent à time_end et durent
        repos_jour + delta * relais_nuit[r][k] minutes, ce qui garantit
        automatiquement la contrainte de repos minimum entre deux relais
        consécutifs du même coureur.
        """
        T_MAX = c.cumul_temps[-1]

        for r, coureur in c.runners_data.items():
            nb = len(coureur.relais)
            opts = coureur.options
            repos_jour = opts.repos_jour_min if opts.repos_jour_min is not None else 0
            repos_nuit = opts.repos_nuit_min if opts.repos_nuit_min is not None else 0
            delta = max(0, repos_nuit - repos_jour)

            combined: list[cp_model.IntervalVar] = []

            for k in range(nb):
                spec = coureur.relais[k]
                ts = self.time_start[(r, k)]
                te = self.time_end[(r, k)]
                dur_time = self.model.new_int_var(0, T_MAX, f"dur_time_{r}_{k}")
                self.model.add(dur_time == te - ts)
                iv_t = self.model.new_interval_var(ts, dur_time, te, f"iv_time_{r}_{k}")
                self.iv_time[(r, k)] = iv_t
                combined.append(iv_t)

                if spec.chained_to_next:
                    continue

                if repos_jour == 0 and delta == 0:
                    # Pas de repos requis : pas d'intervalle de repos
                    continue

                nuit_k = self.relais_nuit.get((r, k))
                if nuit_k is not None and delta != 0:
                    repos_dur = self.model.new_int_var(repos_jour, repos_jour + delta, f"repos_dur_{r}_{k}")
                    self.model.add(repos_dur == repos_jour + delta * nuit_k)
                else:
                    repos_dur = self.model.new_constant(repos_jour)

                re = self.model.new_int_var(0, T_MAX + repos_jour + delta, f"repos_end_{r}_{k}")
                self.model.add(re == te + repos_dur)
                iv_r = self.model.new_interval_var(te, repos_dur, re, f"iv_repos_{r}_{k}")
                self.iv_repos[(r, k)] = iv_r
                self.repos_end[(r, k)] = re
                combined.append(iv_r)

            if len(combined) >= 2:
                self.model.add_no_overlap(combined)

    # ------------------------------------------------------------------
    # No-overlap entre coureurs non appariés
    # ------------------------------------------------------------------

    def add_inter_runner_no_overlap(self, c: Constraints) -> None:
        runners = list(c.runners_data.keys())
        for i, r in enumerate(runners):
            for rp in runners[i + 1:]:
                if c.compat_score(r, rp) == 0:
                    # Incompatibles : un seul no_overlap global pour la paire
                    ivs = (
                        [self.iv[(r, k)] for k in range(len(c.runners_data[r].relais))]
                        + [self.iv[(rp, k)] for k in range(len(c.runners_data[rp].relais))]
                    )
                    self.model.add_no_overlap(ivs)
                else:
                    # Compatibles : no_overlap relais par relais, conditionnel si same_relay existe
                    for k in range(len(c.runners_data[r].relais)):
                        for kp in range(len(c.runners_data[rp].relais)):
                            key = (r, k, rp, kp)
                            if key not in self.same_relay:
                                self.model.add_no_overlap([self.iv[(r, k)], self.iv[(rp, kp)]])
                            else:
                                # Quand ils ne font pas binôme, ils doivent être disjoints
                                b = self.same_relay[key]
                                b_order = self.model.new_bool_var(f"order_{r}_{k}_{rp}_{kp}")
                                self.model.add(self.end[(r, k)] <= self.start[(rp, kp)]).only_enforce_if([b_order, b.negated()])
                                self.model.add(self.end[(rp, kp)] <= self.start[(r, k)]).only_enforce_if([b_order.negated(), b.negated()])

    # ------------------------------------------------------------------
    # Relais nocturnes
    # ------------------------------------------------------------------

    def add_night_relay(self, c: Constraints) -> None:
        if not c._intervals_night:
            for r, coureur in c.runners_data.items():
                for k in range(len(coureur.relais)):
                    b = self.model.new_constant(0)
                    self.relais_nuit[(r, k)] = b
            return

        for r, coureur in c.runners_data.items():
            nuit_max = coureur.options.nuit_max if coureur.options.nuit_max is not None else 99
            nuit_vars = []
            for k in range(len(coureur.relais)):
                # relais_nuit = OR sur toutes les fenêtres nocturnes chevauchées
                window_bools = []
                for (lo, hi) in c._intervals_night:
                    # chevauche ssi start < ne+1 AND end > ns
                    bn = self.model.new_bool_var(f"nw_{r}_{k}_{lo}")
                    bs = self.model.new_bool_var(f"nws_{r}_{k}_{lo}")
                    be = self.model.new_bool_var(f"nwe_{r}_{k}_{lo}")
                    self.model.add(self.start[(r, k)] <= hi).only_enforce_if(bs)
                    self.model.add(self.start[(r, k)] > hi).only_enforce_if(bs.negated())
                    self.model.add(self.end[(r, k)] > lo).only_enforce_if(be)
                    self.model.add(self.end[(r, k)] <= lo).only_enforce_if(be.negated())
                    self.model.add_bool_and([bs, be]).only_enforce_if(bn)
                    self.model.add_bool_or([bs.negated(), be.negated()]).only_enforce_if(bn.negated())
                    window_bools.append(bn)
                rn = self.model.new_bool_var(f"rn_{r}_{k}")
                self.model.add_bool_or(window_bools).only_enforce_if(rn)
                self.model.add_bool_and([b.negated() for b in window_bools]).only_enforce_if(rn.negated())
                self.relais_nuit[(r, k)] = rn
                nuit_vars.append(rn)
            self.model.add(sum(nuit_vars) <= nuit_max)

            # Pour les chaînes : le repos après la chaîne doit être nocturne
            # si n'importe quel relais de la chaîne est nocturne.
            # On force relais_nuit du dernier relais de chaque chaîne à 1
            # si l'un des relais précédents de la chaîne est nocturne.
            relais = coureur.relais
            for k, spec in enumerate(relais):
                if spec.chained_to_next and k + 1 < len(relais):
                    # k est un relais non-final dans une chaîne :
                    # si k est nocturne, k+1 doit l'être aussi
                    rn_k = self.relais_nuit[(r, k)]
                    rn_next = self.relais_nuit[(r, k + 1)]
                    self.model.add_implication(rn_k, rn_next)

    # ------------------------------------------------------------------
    # Contraintes solo
    # ------------------------------------------------------------------

    def add_solo_constraints(self, c: Constraints) -> None:
        #TODO : add docstring
        for r, coureur in c.runners_data.items():
            solo_max = coureur.options.solo_max if coureur.options.solo_max is not None else 99
            solo_vars = []
            for k in range(len(coureur.relais)):
                rk = (r, k)
                # solo = 1 ssi aucun same_relay actif pour ce relais
                same_bools = [
                    bv for (r1, k1, r2, k2), bv in self.same_relay.items()
                    if (r1, k1) == rk or (r2, k2) == rk
                ]
                rs = self.model.new_bool_var(f"solo_{r}_{k}")
                if same_bools:
                    self.model.add_bool_or(same_bools).only_enforce_if(rs.negated())
                    self.model.add_bool_and([b.negated() for b in same_bools]).only_enforce_if(rs)
                else:
                    self.model.add(rs == 1)

                # Si solo : distance max
                self.model.add(self.dist[rk] <= c.solo_max_m).only_enforce_if(rs)

                # Si solo : arc interdit
                # Un relais solo ne doit pas chevaucher une zone interdite.
                # Sémantique identique à night_relay : chevauchement ssi start <= fin_intervalle AND end > début_intervalle
                for (lo, hi) in c._intervals_no_solo:
                    b_in = self.model.new_bool_var(f"sfi_{r}_{k}_{lo}")
                    b_s = self.model.new_bool_var(f"sfis_{r}_{k}_{lo}")
                    b_e = self.model.new_bool_var(f"sfie_{r}_{k}_{lo}")
                    self.model.add(self.start[rk] <= hi).only_enforce_if(b_s)
                    self.model.add(self.start[rk] > hi).only_enforce_if(b_s.negated())
                    self.model.add(self.end[rk] > lo).only_enforce_if(b_e)
                    self.model.add(self.end[rk] <= lo).only_enforce_if(b_e.negated())
                    self.model.add_bool_and([b_s, b_e]).only_enforce_if(b_in)
                    self.model.add_bool_or([b_s.negated(), b_e.negated()]).only_enforce_if(b_in.negated())
                    # Si solo et chevauche zone interdite → infaisable
                    self.model.add_bool_or([rs.negated(), b_in.negated()])

                # solo: True → solo obligatoire, False → binôme obligatoire
                spec_solo = coureur.relais[k].solo
                if spec_solo is True:
                    self.model.add(rs == 1)
                elif spec_solo is False:
                    self.model.add(rs == 0)

                self.relais_solo[rk] = rs
                solo_vars.append(rs)
            self.model.add(sum(solo_vars) <= solo_max)


    # ------------------------------------------------------------------
    # Fenêtres de placement (window)
    # ------------------------------------------------------------------

    def add_availability(self, c: Constraints) -> None:
        for r, coureur in c.runners_data.items():
            for k, spec in enumerate(coureur.relais):
                if spec.window is None:
                    continue
                if len(spec.window) == 1:
                    lo, hi = spec.window[0]
                    self.model.add(self.start[(r, k)] >= lo)
                    self.model.add(self.end[(r, k)] <= hi)
                else:
                    bools = []
                    for i, (lo, hi) in enumerate(spec.window):
                        b = self.model.new_bool_var(f"win_{r}_{k}_{i}")
                        self.model.add(self.start[(r, k)] >= lo).only_enforce_if(b)
                        self.model.add(self.end[(r, k)] <= hi).only_enforce_if(b)
                        bools.append(b)
                    self.model.add_bool_or(bools)

    # ------------------------------------------------------------------
    # Relais épinglés (pinned)
    # ------------------------------------------------------------------

    def add_fixed_relays(self, c: Constraints) -> None:
        for r, coureur in c.runners_data.items():
            for k, spec in enumerate(coureur.relais):
                if spec.pinned_start is not None:
                    self.model.add(self.start[(r, k)] == spec.pinned_start)
                if spec.pinned_end is not None:
                    self.model.add(self.end[(r, k)] == spec.pinned_end)

    # ------------------------------------------------------------------
    # Relais enchaînés (chained_to_next)
    # ------------------------------------------------------------------

    def add_chained_relays(self, c: Constraints) -> None:
        """end[r][k] == start[r][k+1] pour les relais enchaînés."""
        for r, coureur in c.runners_data.items():
            for k, spec in enumerate(coureur.relais):
                if spec.chained_to_next and k + 1 < len(coureur.relais):
                    self.model.add(self.end[(r, k)] == self.start[(r, k + 1)])

    # ------------------------------------------------------------------
    # Brise-symétrie
    # ------------------------------------------------------------------

    def add_symmetry_breaking(self, c: Constraints) -> None:
        for r, coureur in c.runners_data.items():
            relais = coureur.relais
            # Groupes de relais "identiques" (même target_m + min_m + max_m, pas de window/pinned/paired)
            groups: dict[tuple, list[int]] = {}
            for k, spec in enumerate(relais):
                is_chained = spec.chained_to_next or (k > 0 and relais[k - 1].chained_to_next)
                if is_chained:
                    continue
                if spec.window is None and spec.pinned_start is None and spec.pinned_end is None and spec.paired_with is None:
                    key = (spec.target_m, spec.min_m, spec.max_m, spec.solo)
                    groups.setdefault(key, []).append(k)
            for indices in groups.values():
                for i in range(len(indices) - 1):
                    ka, kb = indices[i], indices[i + 1]
                    self.model.add(self.start[(r, ka)] < self.start[(r, kb)])

    # ------------------------------------------------------------------
    # Pairings forcés (SharedLeg)
    # ------------------------------------------------------------------

    def add_shared_relays(self, c: Constraints) -> None:
        for r1, k1, r2, k2 in c.paired_relays:
            key = (r1, k1, r2, k2)
            #TODO: remplacer par un assert. l'absence de same_relay ici est une violation d'intégrité
            if key in self.same_relay:
                self.model.add(self.same_relay[key] == 1)

    # ------------------------------------------------------------------
    # once_max (add_max_binomes)
    # ------------------------------------------------------------------

    def add_max_duos(self, c: Constraints) -> None:
        for r1_name, r2_name, nb in c.max_duos:
            relevant = [
                bv for (r1, k1, r2, k2), bv in self.same_relay.items()
                if {r1, r2} == {r1_name, r2_name}
            ]
            if relevant:
                self.model.add(sum(relevant) <= nb)

    # ------------------------------------------------------------------
    # max_same_partenaire
    # ------------------------------------------------------------------

    def add_max_same_partenaire(self, c: Constraints) -> None:
        runners = list(c.runners_data.keys())
        for i, r in enumerate(runners):
            msp = c.runners_data[r].options.max_same_partenaire
            if msp is None:
                continue
            for rp in runners:
                if rp == r:
                    continue
                relevant = [
                    bv for (r1, k1, r2, k2), bv in self.same_relay.items()
                    if {r1, r2} == {r, rp}
                ]
                if relevant:
                    self.model.add(sum(relevant) <= msp)

    # ------------------------------------------------------------------
    # Objectif
    # ------------------------------------------------------------------

    def add_optimisation_func(self, c: Constraints) -> None:
        """Maximise binômes pondérés."""
        binome_sum = sum(
            c.compat_score(r1, r2) * bv
            for (r1, k1, r2, k2), bv in self.same_relay.items()
        )
        self.model.maximize(binome_sum)

    def _binome_score_expr(self, c: Constraints):
        """Expression CP-SAT de la somme pondérée des binômes."""
        return sum(
            c.compat_score(r1, r2) * bv
            for (r1, k1, r2, k2), bv in self.same_relay.items()
        )

    def add_min_score(self, c: Constraints, score: int) -> None:
        """Contraint le score binôme à être >= score."""
        self.model.add(self._binome_score_expr(c) >= score)

    def add_max_flex(self, max_delta: int) -> None:
        """Contraint la somme des écarts |dist - target| à être <= max_delta (en mètres)."""
        self.model.add(sum(self.flex.values()) <= max_delta)

    def add_optimise_flex(self) -> None:
        """Minimise la somme des écarts |dist - target| sur tous les relais."""
        self.model.minimize(sum(self.flex.values()))

    def add_minimise_differences_with(self, ref_solution, c: Constraints) -> "Model":
        """Minimise la somme des |dist_start[r][k] - ref_km_start| (en mètres).

        ref_solution : Solution de référence chargée via Solution.from_json().
        Pour chaque relais (runner, k) présent dans les deux solutions, on minimise
        l'écart en mètres entre dist_start du nouveau planning et celui de référence.
        """
        model = self.model
        max_m = c.cumul_m[-1]
        diffs = []
        for row in ref_solution.relays:
            runner = row["runner"]
            k = row["k"]
            rk = (runner, k)
            if rk not in self.dist_start:
                continue
            ref_m = round(row["km_start"] * 1000)
            d = model.new_int_var(0, max_m, f"replanif_diff_{runner}_{k}")
            model.add(d >= self.dist_start[rk] - ref_m)
            model.add(d >= ref_m - self.dist_start[rk])
            diffs.append(d)
        if diffs:
            model.minimize(cp_model.LinearExpr.sum(diffs))
        return self

    def add_optimise_dplus(self, c: Constraints) -> None:
        """Maximise sum(lvl[r] * (D+[r][k] + D-[r][k])) sur tous les relais.

        Requiert profil_csv= dans Constraints.
        Les coureurs sans lvl déclaré (lvl=None ou 0) sont ignorés.

        D+/D- sont linéarisés via une table cumulatif pré-calculée aux points
        waypoints :
            cumul_dp[i] = D+ cumulé de km[0] à km[i]
            cumul_dm[i] = D- cumulé de km[0] à km[i]

        Ainsi D+[r][k] = cumul_dp[end] - cumul_dp[start], et idem pour D-.
        """
        if not c.parcours.has_profile:
            raise RuntimeError(
                "add_optimise_dplus() requiert un profil altimétrique dans le Parcours."
            )

        keys = [
            (r, k)
            for r, coureur in c.runners_data.items()
            if coureur.options.lvl
            for k in range(len(coureur.relais))
        ]
        self._ensure_dplus_vars(c, keys)

        terms = []
        for r, coureur in c.runners_data.items():
            lvl = coureur.options.lvl
            if not lvl:
                continue
            for k in range(len(coureur.relais)):
                rk = (r, k)
                terms.append(lvl * ((self.dp_e[rk] - self.dp_s[rk]) + (self.dm_e[rk] - self.dm_s[rk])))

        if not terms:
            raise RuntimeError(
                "add_optimise_dplus() : aucun coureur avec lvl déclaré."
            )
        self.model.maximize(cp_model.LinearExpr.sum(terms))

    def add_hint_from_solution(self, ref_solution) -> None:
        """Fournit au solveur une solution initiale (hint) pour accélérer la recherche.

        Pour chaque relais (runner, k) présent dans ref_solution, on fixe les hints
        sur start[r][k] et end[r][k]. Les relais absents de la référence sont ignorés.
        """
        by_rk = {(row["runner"], row["k"]): row for row in ref_solution.relays}
        for rk, row in by_rk.items():
            if rk not in self.start:
                continue
            self.model.add_hint(self.start[rk], row["start"])
            self.model.add_hint(self.end[rk], row["end"])



def build_model(c: Constraints, *, min_score: int | None = None) -> Model:
    """Construit et retourne un Model prêt à résoudre."""
    c.validate()  # raise ValueError if constraints are invalid
    m = Model()
    m.build(c)   # raise ValueError if model building fails
    if min_score is not None:
        m.add_min_score(c, min_score)
    return m
