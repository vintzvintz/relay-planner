"""
Construction du modèle CP-SAT — relais Lyon-Fessenheim.

Ce module expose :
- build_model() : construit et retourne le modèle avec toutes les contraintes
- build_model_fixed_config() : idem, avec les binômes fixés à une configuration donnée
"""

from ortools.sat.python import cp_model
from data import (
    N_SEGMENTS,
    MIN_RELAY_SIZE,
    ENABLE_FLEXIBILITY,
    RUNNERS_DATA,
    MATCHING_CONSTRAINTS,
    NIGHT_SEGMENTS,
)

RUNNERS = list(RUNNERS_DATA.keys())
N_RUNNERS = len(RUNNERS)
SEG_NIGHT_LIST = sorted(NIGHT_SEGMENTS)


def _flexible_size_domain(r: str, sz_max: int) -> list[int]:
    """Retourne les tailles valides pour un relais flexible (r, sz_max).

    Valeurs possibles : sz_max (défaut) + tailles des partenaires non-flexibles
    compatibles strictement inférieures à sz_max et >= MIN_RELAY_SIZE.
    """
    partner_sizes = set()
    for rp, cp in RUNNERS_DATA.items():
        if rp == r or cp.flexible:
            continue
        if r not in cp.compatible:
            continue
        for sz_p in cp.relais:
            if MIN_RELAY_SIZE <= sz_p < sz_max:
                partner_sizes.add(sz_p)
    return sorted(partner_sizes | {sz_max})


def _add_variables(model):
    """Crée les variables start/end/size et intervalles pour chaque relais.

    Pour les coureurs flexibles, size[r][k] est une variable CP-SAT dont le
    domaine inclut la taille déclarée et les tailles des partenaires non-flexibles
    compatibles (>= MIN_RELAY_SIZE et < sz_max). Pour les autres, size[r][k]
    est simplement sz (entier constant).
    """
    start, end, size, intervals_all = {}, {}, {}, []
    for r in RUNNERS:
        start[r], end[r], size[r] = [], [], []
        runner_ivs = []
        coureur = RUNNERS_DATA[r]
        for k, sz_max in enumerate(coureur.relais):
            s = model.new_int_var(0, N_SEGMENTS - MIN_RELAY_SIZE, f"s_{r}_{k}")
            if coureur.flexible and ENABLE_FLEXIBILITY:
                domain_vals = _flexible_size_domain(r, sz_max)
                if len(domain_vals) == 1:
                    # Aucun partenaire non-flexible de taille différente : taille fixe
                    sz_var = sz_max
                    e = model.new_int_var(sz_max, N_SEGMENTS, f"e_{r}_{k}")
                    model.add(e == s + sz_max)
                    model.add(s <= N_SEGMENTS - sz_max)
                    iv = model.new_interval_var(s, sz_max, e, f"iv_{r}_{k}")
                else:
                    sz_var = model.new_int_var_from_domain(
                        cp_model.Domain.from_values(domain_vals), f"sz_{r}_{k}"
                    )
                    e = model.new_int_var(MIN_RELAY_SIZE, N_SEGMENTS, f"e_{r}_{k}")
                    model.add(e == s + sz_var)
                    iv = model.new_interval_var(s, sz_var, e, f"iv_{r}_{k}")
            else:
                sz_var = sz_max
                e = model.new_int_var(sz_max, N_SEGMENTS, f"e_{r}_{k}")
                model.add(e == s + sz_max)
                model.add(s <= N_SEGMENTS - sz_max)
                iv = model.new_interval_var(s, sz_max, e, f"iv_{r}_{k}")
            start[r].append(s)
            end[r].append(e)
            size[r].append(sz_var)
            intervals_all.append((r, k, sz_max, iv))
            runner_ivs.append(iv)
        if len(runner_ivs) > 1:
            model.add_no_overlap(runner_ivs)
    return start, end, size, intervals_all


def _add_night_relay(model, start, size):
    """Crée les variables night_relay[r][k] et applique la contrainte au plus 1 nuit."""
    night_relay = {}
    for r in RUNNERS:
        night_relay[r] = []
        for k, sz in enumerate(RUNNERS_DATA[r].relais):
            night_starts = sorted(
                set(
                    n - off
                    for n in SEG_NIGHT_LIST
                    for off in range(sz)
                    if 0 <= n - off <= N_SEGMENTS - sz
                )
            )
            rhn = model.new_bool_var(f"rn_{r}_{k}")
            if not night_starts:
                model.add(rhn == 0)
            else:
                nd = cp_model.Domain.from_values(night_starts)
                dd = nd.complement().intersection_with(
                    cp_model.Domain(0, N_SEGMENTS - sz)
                )
                model.add_linear_expression_in_domain(start[r][k], nd).only_enforce_if(rhn)
                if not dd.is_empty():
                    model.add_linear_expression_in_domain(
                        start[r][k], dd
                    ).only_enforce_if(~rhn)
                else:
                    model.add(rhn == 1)
            night_relay[r].append(rhn)

    for r in RUNNERS:
        if RUNNERS_DATA[r].nuit_max < len(RUNNERS_DATA[r].relais):
            model.add(sum(night_relay[r]) <= RUNNERS_DATA[r].nuit_max)

    return night_relay


def _add_rest_constraints(model, start, end, night_relay):
    """Repos minimum entre toute paire de relais d'un même coureur."""
    for r in RUNNERS:
        n_relays = len(RUNNERS_DATA[r].relais)
        if n_relays < 2:
            continue
        for k in range(n_relays):
            for kp in range(k + 1, n_relays):
                k_before_kp = model.new_bool_var(f"bef_{r}_{k}_{kp}")
                k_day_then_kp = model.new_bool_var(f"bkd_{r}_{k}_{kp}")
                k_night_then_kp = model.new_bool_var(f"bkn_{r}_{k}_{kp}")
                model.add_bool_and([k_before_kp, ~night_relay[r][k]]).only_enforce_if(k_day_then_kp)
                model.add_bool_or([~k_before_kp, night_relay[r][k]]).only_enforce_if(~k_day_then_kp)
                model.add_bool_and([k_before_kp, night_relay[r][k]]).only_enforce_if(k_night_then_kp)
                model.add_bool_or([~k_before_kp, ~night_relay[r][k]]).only_enforce_if(~k_night_then_kp)
                model.add(end[r][k] + RUNNERS_DATA[r].repos_jour <= start[r][kp]).only_enforce_if(k_day_then_kp)
                model.add(end[r][k] + RUNNERS_DATA[r].repos_nuit <= start[r][kp]).only_enforce_if(k_night_then_kp)
                kp_day_then_k = model.new_bool_var(f"bkpd_{r}_{k}_{kp}")
                kp_night_then_k = model.new_bool_var(f"bkpn_{r}_{k}_{kp}")
                model.add_bool_and([~k_before_kp, ~night_relay[r][kp]]).only_enforce_if(kp_day_then_k)
                model.add_bool_or([k_before_kp, night_relay[r][kp]]).only_enforce_if(~kp_day_then_k)
                model.add_bool_and([~k_before_kp, night_relay[r][kp]]).only_enforce_if(kp_night_then_k)
                model.add_bool_or([k_before_kp, ~night_relay[r][kp]]).only_enforce_if(~kp_night_then_k)
                model.add(end[r][kp] + RUNNERS_DATA[r].repos_jour <= start[r][k]).only_enforce_if(kp_day_then_k)
                model.add(end[r][kp] + RUNNERS_DATA[r].repos_nuit <= start[r][k]).only_enforce_if(kp_night_then_k)


def _add_availability(model, start, end):
    """Applique les disponibilités partielles et affectations fixes (Olivier/Alexis)."""
    for r, coureur in RUNNERS_DATA.items():
        if not coureur.dispo:
            continue
        for k in range(len(coureur.relais)):
            # start[r][k] must fall within one of the availability windows
            window_bools = []
            for i, (avail_start, avail_end) in enumerate(coureur.dispo):
                b = model.new_bool_var(f"avail_{r}_{k}_{i}")
                model.add(start[r][k] >= avail_start).only_enforce_if(b)
                model.add(end[r][k] <= avail_end).only_enforce_if(b)
                window_bools.append(b)
            model.add_bool_or(window_bools)

    # Pinned binômes: force a pair to share a relay covering the window.
    pair_relay_counters = {}
    for r1, r2, window_start, window_end in MATCHING_CONSTRAINTS["pinned_binomes"]:
        pair_key = (r1, r2)
        idx = pair_relay_counters.get(pair_key, 0)
        min_relay_size = window_end - window_start

        r1_relays = [k for k, sz in enumerate(RUNNERS_DATA[r1].relais) if sz >= min_relay_size]
        r2_relays = [k for k, sz in enumerate(RUNNERS_DATA[r2].relais) if sz >= min_relay_size]
        if idx < len(r1_relays) and idx < len(r2_relays):
            k1, k2 = r1_relays[idx], r2_relays[idx]
            sz1 = RUNNERS_DATA[r1].relais[k1]
            model.add(start[r1][k1] <= window_start)
            model.add(start[r1][k1] >= window_end - sz1)
            model.add(start[r2][k2] == start[r1][k1])
        pair_relay_counters[pair_key] = idx + 1

    # Pinned runners: force a single runner to have a relay covering the window.
    for r, coureur in RUNNERS_DATA.items():
        for idx, window in enumerate(coureur.pinned_segments):
            window_start, window_end = window[0], window[1]
            min_relay_size = window_end - window_start

            r_relays = [k for k, sz in enumerate(coureur.relais) if sz >= min_relay_size]
            if idx < len(r_relays):
                k = r_relays[idx]
                sz = coureur.relais[k]
                model.add(start[r][k] <= window_start)
                model.add(start[r][k] >= window_end - sz)


def _add_same_relay(model, start, size):
    """Crée les variables same_relay pour les binômes potentiels.

    Cas flexible×non-flexible : même start ET size[flexible] == sz_non_flexible.
    Cas non-flex×non-flex ou flex×flex : même start ET sz_r == sz_rp (taille déclarée).
    """
    same_relay = {}
    for ri, r in enumerate(RUNNERS):
        r_flex = RUNNERS_DATA[r].flexible
        for k, sz_r in enumerate(RUNNERS_DATA[r].relais):
            for rpi in range(ri + 1, N_RUNNERS):
                rp = RUNNERS[rpi]
                if rp not in RUNNERS_DATA[r].compatible:
                    continue
                rp_flex = RUNNERS_DATA[rp].flexible
                for kp, sz_rp in enumerate(RUNNERS_DATA[rp].relais):
                    # Détermine si ce binôme est potentiellement possible
                    if r_flex and not rp_flex and ENABLE_FLEXIBILITY:
                        # flexible r peut s'aligner sur sz_rp si sz_rp <= sz_r et >= MIN
                        if sz_rp > sz_r or sz_rp < MIN_RELAY_SIZE:
                            continue
                        # sz_rp doit être dans le domaine de size[r][k]
                        if isinstance(size[r][k], int) and size[r][k] != sz_rp:
                            continue
                    elif rp_flex and not r_flex and ENABLE_FLEXIBILITY:
                        # flexible rp peut s'aligner sur sz_r si sz_r <= sz_rp et >= MIN
                        if sz_r > sz_rp or sz_r < MIN_RELAY_SIZE:
                            continue
                        if isinstance(size[rp][kp], int) and size[rp][kp] != sz_r:
                            continue
                    else:
                        # non-flex×non-flex ou flex×flex : tailles déclarées identiques
                        if sz_r != sz_rp:
                            continue

                    key = (r, k, rp, kp)
                    b = model.new_bool_var(f"sr_{r}_{k}_{rp}_{kp}")
                    same_relay[key] = b

                    # Même start
                    model.add(start[r][k] == start[rp][kp]).only_enforce_if(b)

                    # Même taille effective
                    if r_flex and not rp_flex and not isinstance(size[r][k], int):
                        model.add(size[r][k] == sz_rp).only_enforce_if(b)
                    elif rp_flex and not r_flex and not isinstance(size[rp][kp], int):
                        model.add(size[rp][kp] == sz_r).only_enforce_if(b)

                    # No-overlap quand ~b : utilise la taille effective minimale
                    # (pour être conservatif : si les starts se chevauchent c'est toujours faux)
                    sz_min = min(sz_r, sz_rp)
                    diff = model.new_int_var(-N_SEGMENTS, N_SEGMENTS, f"d_{r}_{k}_{rp}_{kp}")
                    model.add(diff == start[r][k] - start[rp][kp])
                    no_overlap_dom = cp_model.Domain(-N_SEGMENTS, -sz_min).union_with(
                        cp_model.Domain(sz_min, N_SEGMENTS)
                    )
                    model.add_linear_expression_in_domain(diff, no_overlap_dom).only_enforce_if(~b)
    return same_relay


def _add_coverage(model, start, end, size, intervals_all):
    """Contrainte de couverture : chaque segment couvert par 1 ou 2 relais."""
    all_ivs = [iv for _, _, _, iv in intervals_all]
    all_demand = [1 for _ in intervals_all]
    model.add_cumulative(all_ivs, all_demand, 2)

    for s in range(N_SEGMENTS):
        covers_s = []
        for r in RUNNERS:
            for k, sz_max in enumerate(RUNNERS_DATA[r].relais):
                sz_var = size[r][k]
                b = model.new_bool_var(f"c_{r}_{k}_{s}")
                if isinstance(sz_var, int):
                    # Taille fixe : domaine statique
                    sz = sz_var
                    lo = max(0, s - sz + 1)
                    hi = min(s, N_SEGMENTS - sz)
                    if lo > hi:
                        continue
                    dom_in = cp_model.Domain(lo, hi)
                    dom_out = dom_in.complement().intersection_with(
                        cp_model.Domain(0, N_SEGMENTS - sz)
                    )
                    model.add_linear_expression_in_domain(start[r][k], dom_in).only_enforce_if(b)
                    if not dom_out.is_empty():
                        model.add_linear_expression_in_domain(start[r][k], dom_out).only_enforce_if(~b)
                else:
                    # Taille variable : b=1 ssi start[r][k] <= s < start[r][k] + size[r][k]
                    # i.e. start <= s  AND  start + size > s  (i.e. end > s)
                    # On encode : start <= s  AND  end >= s+1
                    b_start_le_s = model.new_bool_var(f"c_sle_{r}_{k}_{s}")
                    b_end_gt_s = model.new_bool_var(f"c_egt_{r}_{k}_{s}")
                    model.add(start[r][k] <= s).only_enforce_if(b_start_le_s)
                    model.add(start[r][k] > s).only_enforce_if(~b_start_le_s)
                    model.add(end[r][k] >= s + 1).only_enforce_if(b_end_gt_s)
                    model.add(end[r][k] < s + 1).only_enforce_if(~b_end_gt_s)
                    model.add_bool_and([b_start_le_s, b_end_gt_s]).only_enforce_if(b)
                    model.add_bool_or([~b_start_le_s, ~b_end_gt_s]).only_enforce_if(~b)
                covers_s.append(b)
        model.add(sum(covers_s) >= 1)


def _add_inter_runner_no_overlap(model, intervals_all, same_relay):
    """Force la disjonction entre relais de coureurs différents non binômables."""
    for ri, r in enumerate(RUNNERS):
        for k, _ in enumerate(RUNNERS_DATA[r].relais):
            iv_rk = intervals_all[
                [i for i, (rr, kk, _, _) in enumerate(intervals_all) if rr == r and kk == k][0]
            ][3]
            for rpi in range(ri + 1, N_RUNNERS):
                rp = RUNNERS[rpi]
                for kp, _ in enumerate(RUNNERS_DATA[rp].relais):
                    iv_rpkp = intervals_all[
                        [i for i, (rr, kk, _, _) in enumerate(intervals_all) if rr == rp and kk == kp][0]
                    ][3]
                    key = (r, k, rp, kp)
                    key_rev = (rp, kp, r, k)
                    if key in same_relay or key_rev in same_relay:
                        continue
                    model.add_no_overlap([iv_rk, iv_rpkp])


def _add_solo_constraints(model, same_relay, size):
    """Crée relais_solo[r][k] et limite à au plus 1 solo par coureur.

    Pour un coureur flexible en solo, force la taille à sz_max (pas de réduction
    sans binôme).
    """
    relais_solo = {}
    for r in RUNNERS:
        relais_solo[r] = []
        coureur = RUNNERS_DATA[r]
        for k, sz_max in enumerate(coureur.relais):
            partners = [
                bv
                for key, bv in same_relay.items()
                if (key[0] == r and key[1] == k) or (key[2] == r and key[3] == k)
            ]
            b = model.new_bool_var(f"solo_{r}_{k}")
            if partners:
                model.add_bool_or(partners).only_enforce_if(~b)
                model.add_bool_and([~p for p in partners]).only_enforce_if(b)
            else:
                model.add(b == 1)
            relais_solo[r].append(b)

            # Flexible en solo → taille déclarée obligatoire
            if coureur.flexible and ENABLE_FLEXIBILITY and not isinstance(size[r][k], int):
                model.add(size[r][k] == sz_max).only_enforce_if(b)

    for r in RUNNERS:
        model.add(sum(relais_solo[r]) <= RUNNERS_DATA[r].solo_max)

    return relais_solo


def _add_no_solo_runners(model, relais_solo):
    """Interdit tout relais solo pour les coureurs dont solo_max == 0."""
    for r, coureur in RUNNERS_DATA.items():
        if coureur.solo_max == 0:
            for b in relais_solo[r]:
                model.add(b == 0)


def _add_no_solo_night(model, relais_solo, night_relay):
    """Interdit les relais solo la nuit."""
    for r in RUNNERS:
        for k in range(len(RUNNERS_DATA[r].relais)):
            model.add(relais_solo[r][k] + night_relay[r][k] <= 1)


def _add_pair_at_least_once(model, same_relay):
    """Impose au moins un relais en binôme pour chaque paire obligatoire."""
    for r1, r2 in MATCHING_CONSTRAINTS["pair_at_least_once"]:
        pair_vars = [
            bv
            for key, bv in same_relay.items()
            if (key[0] == r1 and key[2] == r2) or (key[0] == r2 and key[2] == r1)
        ]
        if pair_vars:
            model.add_bool_or(pair_vars)
        else:
            print(f"AVERTISSEMENT: aucun binôme possible {r1}-{r2}")


def _add_pair_at_most_once(model, same_relay):
    """Impose au plus un relais en binôme pour chaque paire limitée."""
    for r1, r2 in MATCHING_CONSTRAINTS["pair_at_most_once"]:
        pair_vars = [
            bv
            for key, bv in same_relay.items()
            if (key[0] == r1 and key[2] == r2) or (key[0] == r2 and key[2] == r1)
        ]
        if pair_vars:
            model.add(sum(pair_vars) <= 1)
        else:
            print(f"AVERTISSEMENT: aucun binôme possible {r1}-{r2}")


def build_model():
    """Construit le modèle CP-SAT avec toutes les contraintes (sans objectif).

    Retourne (model, start, same_relay, relais_solo, night_relay).
    """
    model = cp_model.CpModel()
    start, end, size, intervals_all = _add_variables(model)
    night_relay = _add_night_relay(model, start, size)
    _add_rest_constraints(model, start, end, night_relay)
    _add_availability(model, start, end)
    same_relay = _add_same_relay(model, start, size)
    _add_coverage(model, start, end, size, intervals_all)
    _add_inter_runner_no_overlap(model, intervals_all, same_relay)
    relais_solo = _add_solo_constraints(model, same_relay, size)
    _add_no_solo_runners(model, relais_solo)
    _add_no_solo_night(model, relais_solo, night_relay)
    _add_pair_at_least_once(model, same_relay)
    _add_pair_at_most_once(model, same_relay)
    return model, start, same_relay, relais_solo, night_relay


def build_model_fixed_config(active_keys, optimal_score):
    """Construit le modèle avec les binômes fixés à la configuration donnée.

    active_keys : frozenset de clés same_relay devant valoir 1.
    optimal_score : valeur cible de la somme des same_relay.
    """
    model, start, same_relay, relais_solo, night_relay = build_model()

    for key, bv in same_relay.items():
        if key in active_keys:
            model.add(bv == 1)
        else:
            model.add(bv == 0)

    model.add(sum(same_relay.values()) == optimal_score)
    return model, start, same_relay, relais_solo, night_relay
