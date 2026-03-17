"""
Données du problème : 440 km, 80 segments, vitesse 9 km/h
Départ : mercredi 15h00
"""

import math
from dataclasses import dataclass, field
from constraints import RelayConstraints
from compat import COMPAT_MATRIX

# --- Temporel ---
TOTAL_KM = 440.0
NB_SEGMENTS = 82
SPEED_KMH = 9.0
START_HOUR = 15  # mercredi 15h00

def hours_to_segs(hours: float) -> int:
    """Convertit une durée en heures en nombre de segments (arrondi au supérieur)."""
    return math.ceil(hours * SPEED_KMH * NB_SEGMENTS / TOTAL_KM)


# Limites par défaut
SOLO_MAX_DEFAULT = 1  # au plus 1 relais solo par coureur
SOLO_MAX_SIZE = 3     # taille maximale d'un relais solo (relais de taille > SOLO_MAX_SIZE interdit en solo)
NUIT_MAX_DEFAULT = 1  # au plus 1 relais nuit par coureur
#TODO calculer dynamiquement à partir des relais déclarés
MIN_RELAY_SIZE = 2  # taille minimale d'un relais (utilisée comme borne basse dans les domaines)

# Repos minimum en nombre de segments
# 7h / (5/9 h) = 12.6 → 13 segments
REPOS_JOUR_DEFAULT = hours_to_segs(7)
# 9h / (5/9 h) = 16.2 → 17 segments
REPOS_NUIT_DEFAULT = hours_to_segs(9)


ENABLE_FLEX = True  # si False, ignore la flexibilité (size == req pour tous les relais)

# Fonction objectif à maximiser. Valeurs possibles :
#
#   'compat_score'  — maximise la somme pondérée des binômes (poids = score de compatibilité).
#                     Objectif linéaire en BoolVar → relaxation LP serrée, coupes efficaces.
#                     Temps de résolution le plus court. Recommandé par défaut.
#
#   'distance_solo' — minimise le nombre total de segments courus en solo.
#                     Nécessite une linéarisation (size × relais_solo), ce qui affaiblit
#                     la relaxation LP et ralentit la résolution (+50–200 % estimé).
#                     Utile pour équilibrer la charge physique entre coureurs.
#
#   'flex_minimal'  — minimise la réduction de taille des relais flexibles (préserve
#                     les distances déclarées). Objectif linéaire en IntVar, peu discriminant
#                     (beaucoup de solutions à score égal) → convergence plus lente à prouver
#                     mais premières solutions rapides. Utile si on veut éviter les "petits" relais.
#
OPTIMISE_SUR = 'compat_score'

def hour_to_seg(hours_from_start: float) -> int:
    """Convertit une durée depuis le départ en numéro de segment."""
    return int(hours_from_start * SPEED_KMH * NB_SEGMENTS / TOTAL_KM)


# --- Structure par coureur ---
@dataclass
class Coureur:
    """Contraintes sur chaque coureur avec valeurs par défaut.

    relais : liste de tuples (nb_seg_requested, nb_seg_flex).
      - nb_seg_requested : taille nominale du relais (segments).
      - nb_seg_flex      : taille flexible du relais (segments).
      Quand nb_seg_requested == nb_seg_flex, le relais est non-flexible.
      Sinon, la taille effective peut prendre n'importe quelle valeur entière
      dans [min(req, flex), max(req, flex)].
    """
    relais: list[tuple[int, int]]
    dispo: list[tuple[int, int]] = field(default_factory=list)  # vide = toujours disponible
    pinned_segments: list[list[int]] = field(default_factory=list)  # liste de [start_seg, end_seg]
    repos_jour: int = REPOS_JOUR_DEFAULT  # repos après un relais de jour (13 segs = 7h)
    repos_nuit: int = REPOS_NUIT_DEFAULT  # repos après un relais de nuit (17 segs = 9h)
    solo_max: int = SOLO_MAX_DEFAULT  # nombre max de relais solo (0 = interdit)
    nuit_max: int = NUIT_MAX_DEFAULT  # nombre max de relais nuit


RUNNERS_DATA: dict[str, Coureur] = {
    "Pierre": Coureur(
        relais=[(4, 4), (3, 2), (3, 2), (3, 2)],
    ),
    "Vincent": Coureur(
        relais=[(2, 2), (2, 2), (2, 2), (2, 2)],
        repos_jour=hours_to_segs(5.5),
        repos_nuit=hours_to_segs(8),
    ),
    "Matthieu": Coureur(
        relais=[(3, 2), (3, 2), (3, 2), (3, 2)],
    ),
    "Olivier": Coureur(
        relais=[(2, 2), (2, 2), (2, 2), (6, 6), (6, 6)],
        nuit_max=5,  # autorisé plusieurs nuits
    ),
    "Alexis": Coureur(
        relais=[(2, 2), (2, 2), (2, 2), (6, 6), (6, 6)],
        nuit_max=5,  # autorisé plusieurs nuits
    ),
    "Guillaume": Coureur(
        relais=[(4, 4), (4, 4)],
        dispo=[(0, hour_to_seg(24))],
    ),
    "Eric": Coureur(
        relais=[(3, 3), (3, 2)],
        dispo=[(0, hour_to_seg(26))],
    ),
    "Yacine": Coureur(
        relais=[(2, 2), (3, 2), (3, 2)],
        dispo=[(0, hour_to_seg(26))],
        repos_jour=hours_to_segs(5),
        repos_nuit=hours_to_segs(8),
    ),
    "Alexandre": Coureur(
        relais=[(2, 2), (2, 2), (3, 2), (3, 2)],
    ),
    "Antoine": Coureur(
        relais=[(3, 3), (3, 3), (3, 2), (2, 2)],
    ),
    "Ludovic": Coureur(
        relais=[(4, 4), (3, 3), (3, 2), (3, 2)],
    ),
    "Nelly": Coureur(
        relais=[(2, 2), (2, 2), (2, 2), (2, 2)],
    ),
    "Gaelle": Coureur(
        relais=[(2, 2), (2, 2), (2, 2), (2, 2)],
    ),
    "Clemence": Coureur(
        relais=[(2, 2), (2, 2)],
        dispo=[(0, hour_to_seg(8)),
               (hour_to_seg(48-START_HOUR+11), NB_SEGMENTS)],
    ),
    "Leo": Coureur(
        relais=[(2, 2), (2, 2), (2, 2), (2, 2)],
    ),
}

 # Binômes épinglés : (r1, r2, start_seg, end_seg)
BINOMES_PINNED = [
    ("Olivier", "Alexis", hour_to_seg(9), hour_to_seg(11)),  # 0h jeudi
    ("Olivier", "Alexis", hour_to_seg(9 + 24), hour_to_seg(11 + 24)),  # 0h vendredi
]

# Binômes obligatoires (au moins 1 relais ensemble)
BINOMES_ONCE_MIN = [
    ("Nelly", "Gaelle"),
    ("Nelly", "Clemence"),
]

# Binômes limités (au plus 1 relais ensemble)
BINOMES_ONCE_MAX = [
    ("Gaelle", "Nelly"),
]

def build_constraints() -> RelayConstraints:
    """Construit et retourne un RelayConstraints à partir des données module-level."""
    return RelayConstraints(
        total_km=TOTAL_KM,
        nb_segments=NB_SEGMENTS,
        speed_kmh=SPEED_KMH,
        start_hour=START_HOUR,
        runners_data=RUNNERS_DATA,
        compat_matrix=COMPAT_MATRIX,
        binomes_pinned=BINOMES_PINNED,
        binomes_once_min=BINOMES_ONCE_MIN,
        binomes_once_max=BINOMES_ONCE_MAX,
        min_relay_size=MIN_RELAY_SIZE,
        solo_max_default=SOLO_MAX_DEFAULT,
        solo_max_size=SOLO_MAX_SIZE,
        nuit_max_default=NUIT_MAX_DEFAULT,
        repos_jour_default=REPOS_JOUR_DEFAULT,
        repos_nuit_default=REPOS_NUIT_DEFAULT,
        optimise_sur=OPTIMISE_SUR,
        enable_flex=ENABLE_FLEX,
    )

if __name__ == "__main__":
    c = build_constraints()
    c.print_summary()
    
