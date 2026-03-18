"""
Données du problème
"""

import math
from dataclasses import dataclass, field
from constraints import RelayConstraints
from compat import COMPAT_MATRIX


TOTAL_KM = 440.0
NB_SEGMENTS = 82
SPEED_KMH = 9.0
START_HOUR = 14.5  # mercredi 14h30


def hours_to_segs(hours: float) -> int:
    """Convertit une durée en heures en nombre de segments (arrondi au supérieur)."""
    return math.ceil(hours * SPEED_KMH * NB_SEGMENTS / TOTAL_KM)

def hour_to_seg(hours_from_start: float) -> int:
    """Convertit une durée depuis le départ en numéro de segment."""
    return int(hours_from_start * SPEED_KMH * NB_SEGMENTS / TOTAL_KM)


# contraintes globales sur l'affectation des relais 
# modifiables pour chaque coureur ( ex: 2 nuits, solo interdit, etc.. )
NUIT_MAX_DEFAULT = 1  # au plus 1 relais nuit par coureur
SOLO_MAX_DEFAULT = 1  # au plus 1 relais solo par coureur

# Repos minimum en nombre de segments
REPOS_JOUR_DEFAULT = hours_to_segs(7)  # 7 heures
REPOS_NUIT_DEFAULT = hours_to_segs(9)  # 9 heures
SOLO_MAX_SIZE = 3 # relais solo sur 10 et 15km, mais pas sur 20 km et 30km

ENABLE_FLEX = True  # si False, ignore la flexibilité (size == req pour tous les relais)


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

    pinned : liste de même longueur que relais, une entrée par relais.
      - None          : le relais est libre, le solveur choisit sa position.
      - (size, start) : le relais est fixé — start et size sont imposés au modèle
                        CP-SAT (contraintes d'égalité strictes). Utile pour
                        figer des relais déjà courus ou imposer une contrainte
                        de placement précise. L'index dans pinned correspond
                        directement à l'index dans relais.
      Liste vide autorisée (équivalent à tout None) : aucun relais fixé.
    """
    relais: list[tuple[int, int]]
    pinned: list[tuple[int, int] | None] = field(default_factory=list)  # par index de relais : (size, start_seg) ou None
    dispo: list[tuple[int, int]] = field(default_factory=list)  # vide = toujours disponible
    repos_jour: int = REPOS_JOUR_DEFAULT  # repos après un relais de jour (13 segs = 7h)
    repos_nuit: int = REPOS_NUIT_DEFAULT  # repos après un relais de nuit (17 segs = 9h)
    solo_max: int = SOLO_MAX_DEFAULT  # nombre max de relais solo (0 = interdit)
    nuit_max: int = NUIT_MAX_DEFAULT  # nombre max de relais nuit


RUNNERS_DATA: dict[str, Coureur] = {
    "Pierre": Coureur(
        relais=[(4, 4), (3, 2), (3, 2), (3, 2)],
        pinned=[(4,2), None, None, None],
    ),
    "Vincent": Coureur(
        relais=[(2, 2), (2, 2), (2, 2), (2, 2)],
        pinned=[None, None, None, None],
        repos_jour=hours_to_segs(5.5),
        repos_nuit=hours_to_segs(8),
    ),
    "Matthieu": Coureur(
        relais=[(3, 2), (3, 2), (3, 2), (3, 2)],
        pinned=[None, None, None, None],
    ),
    "Olivier": Coureur(
        relais=[(2, 2), (2, 2), (2, 2), (6, 6), (6, 6)],
        pinned=[(2, 0) , None, None, None, None],
        nuit_max=5,  # autorisé plusieurs nuits
    ),
    "Alexis": Coureur(
        relais=[(2, 2), (2, 2), (2, 2), (6, 6), (6, 6)],
        pinned=[(2, 0), None, None, None, None],  # test: pinned sur les 10 premiers km
        nuit_max=5,  # autorisé plusieurs nuits
    ),
    "Guillaume": Coureur(
        relais=[(4, 4), (4, 4)],
        pinned=[(4, 2), None],     # test: 4 segments à partir du 10eme km
        dispo=[(0, hour_to_seg(24))],
    ),
    "Eric": Coureur(
        relais=[(3, 3), (3, 2)],
        pinned=[None, None],
        dispo=[(0, hour_to_seg(26))],
    ),
    "Yacine": Coureur(
        relais=[(2, 2), (3, 2), (3, 2)],
        pinned=[None, None, None],
        dispo=[(0, hour_to_seg(26))],
        repos_jour=hours_to_segs(5),
        repos_nuit=hours_to_segs(8),
    ),
    "Alexandre": Coureur(
        relais=[(2, 2), (2, 2), (3, 2), (3, 2)],
        #pinned=[(2,NB_SEGMENTS-2), None, None, None],   # pour test : affectation forcée sur les derniers 10km
    ),
    "Antoine": Coureur(
        relais=[(3, 3), (3, 3), (3, 2), (2, 2)],
        pinned=[None, None, None, None],
    ),
    "Ludovic": Coureur(
        relais=[(4, 4), (3, 3), (3, 2), (3, 2)],
        pinned=[None, None, None, None],
    ),
    "Nelly": Coureur(
        relais=[(2, 2), (2, 2), (2, 2), (2, 2)],
        pinned=[None, None, None, None],
    ),
    "Gaelle": Coureur(
        relais=[(2, 2), (2, 2), (2, 2), (2, 2)],
        pinned=[None, None, None, None],
    ),
    "Clemence": Coureur(
        relais=[(2, 2), (2, 2)],
        pinned=[None, (2, NB_SEGMENTS-2)], # pour test : affectation forcée sur les derniers 10 km
        dispo=[(0, hour_to_seg(8)),
               (hour_to_seg(48-START_HOUR+11), NB_SEGMENTS)],
    ),
    "Leo": Coureur(
        relais=[(2, 2), (2, 2), (2, 2), (2, 2)],
        pinned=[None, None, None, None],
    ),
}

 # Binômes épinglés sur certains segments, pas forcément le relais entier: 
 # (r1, r2, start_seg, end_seg)
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
        solo_max_size=SOLO_MAX_SIZE,
        solo_max_default=SOLO_MAX_DEFAULT,
        nuit_max_default=NUIT_MAX_DEFAULT,
        repos_jour_default=REPOS_JOUR_DEFAULT,
        repos_nuit_default=REPOS_NUIT_DEFAULT,
        enable_flex=ENABLE_FLEX,
    )

if __name__ == "__main__":
    c = build_constraints()
    c.print_summary()
    
