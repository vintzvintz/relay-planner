"""
Données du problème : 440 km, 88 segments de 5 km, vitesse 9 km/h
Départ : mercredi 15h00
"""

import math
from dataclasses import dataclass, field

# --- Temporel ---
TOTAL_KM = 440
SEGMENT_KM = 5
N_SEGMENTS = TOTAL_KM // SEGMENT_KM  # 88

SPEED_KMH = 9
SEGMENT_DURATION_H = SEGMENT_KM / SPEED_KMH  # ~0.5556h = 33.33 min

START_HOUR = 15  # mercredi 15h00

# Repos minimum en nombre de segments
# 7h / (5/9 h) = 12.6 → 13 segments
# 9h / (5/9 h) = 16.2 → 17 segments
REST_NORMAL = math.ceil(7 * SPEED_KMH / SEGMENT_KM)
REST_NIGHT = math.ceil(9 * SPEED_KMH / SEGMENT_KM)

# --- Feature flags ---
ENABLE_FLEXIBILITY = True  # active la réduction de taille des relais pour former des binômes

# Limites par défaut
SOLO_MAX_DEFAULT = 1  # au plus 1 relais solo par coureur
NUIT_MAX_DEFAULT = 1  # au plus 1 relais nuit par coureur
MIN_RELAY_SIZE = 2  # taille minimale d'un relais flexible (10 km)


def segment_start_hour(seg: int) -> float:
    """Heure de début du segment (0-indexé), en heures depuis minuit mercredi."""
    return START_HOUR + seg * SEGMENT_DURATION_H


def is_night(seg: int) -> bool:
    """Vrai si le segment démarre entre 0h et 6h (n'importe quel jour)."""
    h = segment_start_hour(seg) % 24
    return 0.0 <= h < 6.0


def hour_to_seg(hours_from_start: float) -> int:
    """Convertit une durée depuis le départ en numéro de segment."""
    return int(hours_from_start / SEGMENT_DURATION_H)


# Segments nuit (précalculés)
NIGHT_SEGMENTS = set(s for s in range(N_SEGMENTS) if is_night(s))


# --- Structure par coureur ---

@dataclass
class Coureur:
    relais: list[int]
    compatible: set[str] = field(default_factory=set)
    dispo: list[tuple[int, int]] = field(default_factory=list)  # vide = toujours disponible
    pinned_segments: list[list[int]] = field(default_factory=list)  # liste de [start_seg, end_seg]
    repos_jour: int = REST_NORMAL  # repos après un relais de jour (13 segs = 7h)
    repos_nuit: int = REST_NIGHT  # repos après un relais de nuit (17 segs = 9h)
    solo_max: int = SOLO_MAX_DEFAULT  # nombre max de relais solo (0 = interdit)
    nuit_max: int = NUIT_MAX_DEFAULT  # nombre max de relais nuit
    flexible: bool = False  # peut réduire la taille de ses relais pour former un binôme avec un non-flexible


RUNNERS_DATA: dict[str, Coureur] = {
    "Pierre": Coureur(
        relais=[4, 3, 3, 3],
        compatible={"Guillaume", "Ludovic", "Alexis", "Olivier", "Vincent", "Matthieu", "Eric", "Yacine", "Alexandre", "Antoine"},  # fmt: skip
        flexible=True,
    ),
    "Vincent": Coureur(
        relais=[2, 2, 2, 2],
        compatible={"Pierre", "Matthieu", "Olivier", "Alexis", "Eric", "Yacine", "Alexandre", "Antoine", "Ludovic", "Nelly", "Gaelle"},  # fmt: skip
        repos_jour=math.ceil(5.5 * SPEED_KMH / SEGMENT_KM),
        repos_nuit=math.ceil(8 * SPEED_KMH / SEGMENT_KM),
    ),
    "Matthieu": Coureur(
        relais=[3, 3, 3, 3],
        compatible={"Pierre", "Vincent", "Olivier", "Alexis", "Eric", "Yacine", "Alexandre", "Antoine", "Ludovic"},  # fmt: skip
        flexible=True,
    ),
    "Olivier": Coureur(
        relais=[2, 2, 2, 6, 6],
        compatible={"Alexis"},
        nuit_max=5,  # autorisé plusieurs nuits
    ),
    "Alexis": Coureur(
        relais=[2, 2, 2, 6, 6],
        compatible={"Olivier"},
        nuit_max=5,  # autorisé plusieurs nuits
    ),
    "Guillaume": Coureur(
        relais=[4, 4],
        compatible={"Pierre", "Ludovic"},
        dispo=[(0, hour_to_seg(24))],
    ),
    "Eric": Coureur(
        relais=[3, 3],
        compatible={"Pierre", "Vincent", "Matthieu", "Yacine", "Alexandre", "Antoine", "Ludovic"},  # fmt: skip
        dispo=[(0, hour_to_seg(26))],
        flexible=True,
    ),
    "Yacine": Coureur(
        relais=[2, 3, 3],
        compatible={"Pierre", "Vincent", "Matthieu", "Eric", "Alexandre", "Antoine", "Ludovic", "Nelly", "Gaelle"},  # fmt: skip
        dispo=[(0, hour_to_seg(26))],
        repos_jour=math.ceil(5 * SPEED_KMH / SEGMENT_KM),
        repos_nuit=math.ceil(8 * SPEED_KMH / SEGMENT_KM),
        flexible=True,
    ),
    "Alexandre": Coureur(
        relais=[2, 2, 3, 3],
        compatible={"Pierre", "Vincent", "Matthieu", "Eric", "Yacine", "Antoine", "Ludovic", "Nelly", "Gaelle"},  # fmt: skip
        flexible=True,
    ),
    "Antoine": Coureur(
        relais=[3, 3, 3, 2],
        compatible={"Pierre", "Vincent", "Matthieu", "Eric", "Yacine", "Alexandre", "Ludovic", "Nelly", "Gaelle"},  # fmt: skip
        flexible=True,
    ),
    "Ludovic": Coureur(
        relais=[4, 3, 3, 3],
        compatible={"Pierre", "Guillaume", "Vincent", "Matthieu", "Eric", "Yacine", "Alexandre", "Antoine"},  # fmt: skip
        flexible=True,
    ),
    "Nelly": Coureur(
        relais=[2, 2, 2, 2],
        compatible={"Gaelle", "Clemence", "Vincent", "Alexandre", "Yacine", "Antoine"},
    ),
    "Gaelle": Coureur(
        relais=[2, 2, 2, 2],
        compatible={"Nelly", "Vincent", "Yacine", "Alexandre", "Antoine"},
    ),
    "Clemence": Coureur(
        relais=[2, 2],
        compatible={"Nelly"},
        # solo_max=0,
        dispo=[(0, hour_to_seg(8)), (hour_to_seg(9 + 24 + 10 + 1), N_SEGMENTS)],
    ),
}


MATCHING_CONSTRAINTS: dict = {
    # Binômes épinglés : (r1, r2, start_seg, end_seg)
    "pinned_binomes": [
        ("Olivier", "Alexis", hour_to_seg(9), hour_to_seg(11)),  # 0h jeudi
        ("Olivier", "Alexis", hour_to_seg(9 + 24), hour_to_seg(11 + 24)),  # 0h vendredi
    ],
    # Binômes obligatoires (au moins 1 relais ensemble)
    "pair_at_least_once": [
        ("Nelly", "Gaelle"),
        ("Nelly", "Clemence"),
        # ("Alexis", "Olivier"),  # sur les relais de 30km (x2)
    ],
    # Binômes limités (au plus 1 relais ensemble)
    "pair_at_most_once": [
        ("Gaelle", "Nelly"),
    ],
}


def check_compatible_symmetric():
    """Vérifie que les champs 'compatible' sont symétriques et affiche les asymétries éventuelles."""
    asymmetries = []
    for a, coureur in RUNNERS_DATA.items():
        for b in coureur.compatible:
            if b not in RUNNERS_DATA or a not in RUNNERS_DATA[b].compatible:
                asymmetries.append((a, b))
    if asymmetries:
        print("AVERTISSEMENT : compatible n'est pas symétrique :")
        for a, b in asymmetries:
            print(f"  {a} → {b} mais pas l'inverse")



def print_summary(with_upper_bound: bool = True) -> None:
    """Affiche un résumé complet des données d'entrée du problème."""
    n_night = len(NIGHT_SEGMENTS)
    night_pct = 100 * n_night / N_SEGMENTS
    print("=" * 60)
    print("RÉSUMÉ DES DONNÉES D'ENTRÉE")
    print("=" * 60)
    print(f"  Parcours    : {TOTAL_KM} km, {N_SEGMENTS} segments de {SEGMENT_KM} km")
    print(f"  Vitesse     : {SPEED_KMH} km/h → {SEGMENT_DURATION_H * 60:.1f} min/segment")
    print(f"  Départ      : mercredi {START_HOUR}h00")
    print(f"  Repos jour  : {REST_NORMAL} segments = {REST_NORMAL * SEGMENT_DURATION_H:.1f}h (min 7h)")  # fmt: skip
    print(f"  Repos nuit  : {REST_NIGHT} segments = {REST_NIGHT * SEGMENT_DURATION_H:.1f}h (min 9h)")   # fmt: skip
    print(f"  Segments nuit (0h–6h) : {n_night} / {N_SEGMENTS} ({night_pct:.0f}%)")

    print()
    print("COUREURS")
    print("-" * 60)
    total_km = 0
    for name, coureur in RUNNERS_DATA.items():
        km = sum(coureur.relais) * SEGMENT_KM
        total_km += km
        flags = []
        if coureur.nuit_max == 0:
            flags.append("nuit interdit")
        elif coureur.nuit_max != NUIT_MAX_DEFAULT:
            flags.append(f"nuit_max={coureur.nuit_max}")
        if coureur.solo_max == 0:
            flags.append("solo interdit")
        elif coureur.solo_max != SOLO_MAX_DEFAULT:
            flags.append(f"solo_max={coureur.solo_max}")
        if coureur.repos_jour != REST_NORMAL:
            flags.append(f"repos_jour={coureur.repos_jour} segs ({coureur.repos_jour * SEGMENT_DURATION_H:.1f}h)") # fmt: skip
        if coureur.repos_nuit != REST_NIGHT:
            flags.append(f"repos_nuit={coureur.repos_nuit} segs ({coureur.repos_nuit * SEGMENT_DURATION_H:.1f}h)") # fmt: skip
        if coureur.dispo:
            flags.append("dispo partielle")
        if coureur.pinned_segments:
            flags.append(f"épinglé×{len(coureur.pinned_segments)}")
        flag_str = f"  [{', '.join(flags)}]" if flags else ""
        sizes_str = "+".join(str(s * SEGMENT_KM) for s in coureur.relais)
        print(f"  {name:12s} : {km:4d} km = {sizes_str} km{flag_str}")
    print(f"  {'TOTAL':12s}   {total_km} km engagés  ({total_km - TOTAL_KM} km de surplus)")

    print()
    print("COMPATIBILITÉS (binômes possibles)")
    print("-" * 60)
    for name, coureur in RUNNERS_DATA.items():
        compat_str = ", ".join(sorted(coureur.compatible)) if coureur.compatible else "— aucune"
        print(f"  {name:12s} : {compat_str}")
    check_compatible_symmetric()

    print()
    print("DISPONIBILITÉS PARTIELLES")
    print("-" * 60)
    any_dispo = False
    for name, coureur in RUNNERS_DATA.items():
        if coureur.dispo:
            windows = ", ".join(f"[seg {s}–{e}]" for s, e in coureur.dispo)
            print(f"  {name:12s} : {windows}")
            any_dispo = True
    if not any_dispo:
        print("  (aucune)")

    print()
    print("CONTRAINTES DE MATCHING")
    print("-" * 60)
    pinned = MATCHING_CONSTRAINTS["pinned_binomes"]
    if pinned:
        print("  Binômes épinglés :")
        for r1, r2, s, e in pinned:
            h_s = segment_start_hour(s)
            h_e = segment_start_hour(e)
            print(f"    {r1}+{r2} : segs [{s},{e}]  ({h_s:.1f}h–{h_e:.1f}h depuis départ)")
    else:
        print("  Binômes épinglés : (aucun)")

    pinned_runners = [(n, w) for n, c in RUNNERS_DATA.items() for w in c.pinned_segments]
    if pinned_runners:
        print("  Coureurs épinglés :")
        for name, w in pinned_runners:
            print(f"    {name} : segs {w}")

    at_least = MATCHING_CONSTRAINTS["pair_at_least_once"]
    if at_least:
        print(f"  Au moins 1 relais ensemble : {', '.join(f'{a}+{b}' for a, b in at_least)}")

    at_most = MATCHING_CONSTRAINTS["pair_at_most_once"]
    if at_most:
        print(f"  Au plus 1 relais ensemble  : {', '.join(f'{a}+{b}' for a, b in at_most)}")

    if with_upper_bound:
        print()
        print("BORNE SUPÉRIEURE (relaxation LP)")
        print("-" * 60)
        from upper_bound import compute_upper_bound

        compute_upper_bound()

    print("=" * 60)


if __name__ == "__main__":
    print_summary()
