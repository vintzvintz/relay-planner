"""
Données du problème : 440 km, 88 segments de 5 km, vitesse 9 km/h
Départ : mercredi 15h00
"""

import math

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


def check_compatible_symmetric():
    """Vérifie que COMPATIBLE est symétrique et affiche les asymétries éventuelles."""
    asymmetries = []
    for a, partners in COMPATIBLE.items():
        for b in partners:
            if b not in COMPATIBLE or a not in COMPATIBLE[b]:
                asymmetries.append((a, b))
    if asymmetries:
        print("AVERTISSEMENT : COMPATIBLE n'est pas symétrique :")
        for a, b in asymmetries:
            print(f"  {a} → {b} mais pas l'inverse")


# Segments nuit (précalculés)
NIGHT_SEGMENTS = set(s for s in range(N_SEGMENTS) if is_night(s))


# --- Coureurs ---
# Format : nom -> liste de tailles de relais en segments (10km=2, 15km=3, 20km=4, 30km=6)

RUNNER_RELAYS = {
    "Pierre": [4, 3, 3, 3],      # en gras → distance adaptable à la baisse
    "Vincent": [2, 2, 2, 2],
    "Matthieu": [3, 3, 3, 3],    # en gras
    "Olivier": [2, 2, 2, 6, 6],
    "Alexis": [2, 2, 2, 6, 6],
    "Guillaume": [4, 4],
    "Eric": [3, 3],              # en gras
    "Yacine": [2, 3, 3],         # en gras
    "Alexandre": [2, 2, 3, 3],   # en gras
    "Antoine": [3, 3, 3, 2],     # en gras
    "Ludovic": [4, 3, 3, 3],     # en gras
    "Nelly": [2, 2, 2, 2],
    "Gaelle": [2, 2, 2, 2],
    "Clemence": [2, 2],
}


# Coureurs dont la taille des relais peut être réduite (en gras dans le CCTP)
# NOT IMPLMENTED
FLEXIBLE_RUNNERS = {
    "Pierre",
    "Matthieu",
    "Eric",
    "Yacine",
    "Alexandre",
    "Antoine",
    "Ludovic",
}


# --- Disponibilités partielles (fenêtres en segments) ---
# Par défaut chaque coureur est disponible sur toute la course.
# Format : nom -> liste de (debut_seg_dispo, fin_seg_dispo)  [borne fin exclue]
# Un coureur ne peut commencer un relais que dans l'une de ses fenêtres de disponibilité.
# Les coureurs absents de ce dict sont disponibles sur tous les segments.
PARTIAL_AVAILABILITY: dict[str, list[tuple[int, int]]] = {
    # Guillaume : disponible uniquement sur les premières 24h
    "Guillaume": [(0, hour_to_seg(24))],
    # Eric : disponible uniquement sur les premières 26h
    "Eric": [(0, hour_to_seg(26))],
    # Clémence : sur les 10 premieres heures et le dernier jour après 10h
    "Clemence": [(0, hour_to_seg(10)), (hour_to_seg(9 + 24 + 10 + 1), N_SEGMENTS)],
}

# --- Contraintes spéciales ---

# Fenêtres imposées pour des coureurs individuels : chaque entrée force le coureur
# à avoir un relais dont la plage couvre entièrement [start_seg, end_seg].
PINNED_RUNNERS = [
    # ("Clemence", [hour_to_seg(9 + 24 + 11.5), hour_to_seg(9 + 24 + 12)])
]

# Fenêtres imposées pour des binômes : chaque entrée force les deux coureurs à partager
# un relais dont la plage couvre entièrement [start_seg, end_seg].
PINNED_BINOMES = [
    # 4 segments fixes entre 0h et 2h chaque nuit (les 2 restants sont flottants)
    (("Olivier", "Alexis"), [hour_to_seg(9), hour_to_seg(11)]),  # 0h jeudi
    (("Olivier", "Alexis"), [hour_to_seg(9 + 24), hour_to_seg(11 + 24)]),  # 0h vendredi
]

# Coureurs autorisés à courir plusieurs fois la nuit
MULTI_NIGHT_ALLOWED = {"Alexis", "Olivier"}

# --- Compatibilités binômes ---
# Qui peut courir avec qui (symétrique)
# Guillaume peut courir avec Pierre et Ludovic uniquement
# Nelly : Gaelle (obligatoire 1x), Clemence (obligatoire 1x), Vincent, Alexandre, Yacine, Antoine
# Gaelle : Nelly (obligatoire 1x), Vincent, Yacine, Alexandre, Antoine

COMPATIBLE = {
    "Pierre": {
        "Guillaume",
        "Ludovic",
        "Alexis",
        "Olivier",
        "Vincent",
        "Matthieu",
        "Eric",
        "Yacine",
        "Alexandre",
        "Antoine",
    },
    "Vincent": {
        "Pierre",
        "Matthieu",
        "Olivier",
        "Alexis",
        "Eric",
        "Yacine",
        "Alexandre",
        "Antoine",
        "Ludovic",
        "Nelly",
        "Gaelle",
    },
    "Matthieu": {
        "Pierre",
        "Vincent",
        "Olivier",
        "Alexis",
        "Eric",
        "Yacine",
        "Alexandre",
        "Antoine",
        "Ludovic",
    },
    "Olivier": {"Alexis"},  # contraint à courir avec Alexis sur les 30km
    "Alexis": {"Olivier"},  # idem
    "Guillaume": {"Pierre", "Ludovic"},
    "Eric": {
        "Pierre",
        "Vincent",
        "Matthieu",
        "Yacine",
        "Alexandre",
        "Antoine",
        "Ludovic",
    },
    "Yacine": {
        "Pierre",
        "Vincent",
        "Matthieu",
        "Eric",
        "Alexandre",
        "Antoine",
        "Ludovic",
        "Nelly",
        "Gaelle",
    },
    "Alexandre": {
        "Pierre",
        "Vincent",
        "Matthieu",
        "Eric",
        "Yacine",
        "Antoine",
        "Ludovic",
        "Nelly",
        "Gaelle",
    },
    "Antoine": {
        "Pierre",
        "Vincent",
        "Matthieu",
        "Eric",
        "Yacine",
        "Alexandre",
        "Ludovic",
        "Nelly",
        "Gaelle",
    },
    "Ludovic": {
        "Pierre",
        "Guillaume",
        "Vincent",
        "Matthieu",
        "Eric",
        "Yacine",
        "Alexandre",
        "Antoine",
    },
    "Nelly": {"Gaelle", "Clemence", "Vincent", "Alexandre", "Yacine", "Antoine"},
    "Gaelle": {"Nelly", "Vincent", "Yacine", "Alexandre", "Antoine"},
    "Clemence": {"Nelly"},
}

# Binômes obligatoires (au moins 1 relais ensemble)
MANDATORY_PAIRS = [
    ("Nelly", "Gaelle"),
    ("Nelly", "Clemence"),
    ("Alexis", "Olivier"),  # sur les relais de 30km (x2)
]

if __name__ == "__main__":
    print(f"Nombre de segments : {N_SEGMENTS}")
    print(f"Segments nuit : {sorted(NIGHT_SEGMENTS)}")
    print()
    print("Disponibilités partielles :")
    for name, windows in PARTIAL_AVAILABILITY.items():
        print(f"  {name:12s} : {windows}")
    print()
    print("Binômes épinglés :")
    for pair, window in PINNED_BINOMES:
        print(f"  {set(pair)} : segments {window}")
    print()
    print("Coureurs épinglés :")
    for runner, window in PINNED_RUNNERS:
        print(f"  {runner} : segments {window}")
    print()
    print("Relais par coureur (en segments) :")
    total = 0
    for name, relays in RUNNER_RELAYS.items():
        km = sum(relays) * SEGMENT_KM
        total += km
        print(f"  {name:12s} : {relays}  ({km} km)")
    print(f"  Total engagé : {total} km")
    check_compatible_symmetric()
