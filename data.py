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

def segment_start_hour(seg: int) -> float:
    """Heure de début du segment (0-indexé), en heures depuis minuit mercredi."""
    return START_HOUR + seg * SEGMENT_DURATION_H

def is_night(seg: int) -> bool:
    """Vrai si le segment démarre entre 0h et 6h (n'importe quel jour)."""
    h = segment_start_hour(seg) % 24
    return 0.0 <= h < 6.0

# Segments nuit (précalculés)
NIGHT_SEGMENTS = set(s for s in range(N_SEGMENTS) if is_night(s))

# Repos minimum en nombre de segments
# 7h / (5/9 h) = 12.6 → 13 segments
# 9h / (5/9 h) = 16.2 → 17 segments
REST_NORMAL = math.ceil(7 * SPEED_KMH/SEGMENT_KM)
REST_NIGHT = math.ceil(9 * SPEED_KMH/SEGMENT_KM)

# --- Coureurs ---
# Format : nom -> liste de relais engagés [(nb_segments, nb_fois), ...]
# nb_segments = taille du relais en segments (10km=2, 15km=3, 20km=4, 30km=6)

KM_TO_SEG = {10: 2, 15: 3, 20: 4, 30: 6}

RUNNERS_RAW = {
    "Pierre":    [(20, 1), (15, 3)],       # en gras → distance adaptable à la baisse
    "Vincent":   [(10, 4)],
    "Matthieu":  [(15, 4)],                # en gras
    "Olivier":   [(10, 3), (30, 2)],
    "Alexis":    [(10, 3), (30, 2)],
    "Guillaume": [(20, 2)],
    "Eric":      [(15, 2)],                # en gras
    "Yacine":    [(10, 1), (15, 2)],       # en gras
    "Alexandre": [(10, 2), (15, 2)],       # en gras
    "Antoine":   [(15, 3), (10, 1)],       # en gras
    "Ludovic":   [(20, 1), (15, 3)],       # en gras
    "Nelly":     [(10, 4)],
    "Gaelle":    [(10, 4)],
    "Clemence":  [(10, 2)],
}

# Décompose en liste de tailles de relais (en segments)
def expand_relays(raw: dict) -> dict:
    result = {}
    for name, engagements in raw.items():
        sizes = []
        for (km, count) in engagements:
            sizes.extend([KM_TO_SEG[km]] * count)
        result[name] = sizes
    return result

RUNNER_RELAYS = expand_relays(RUNNERS_RAW)

# Coureurs dont la taille des relais peut être réduite (en gras dans le CCTP)
FLEXIBLE_RUNNERS = {"Pierre", "Matthieu", "Eric", "Yacine", "Alexandre", "Antoine", "Ludovic"}

# --- Indisponibilités (fenêtres en segments) ---
# Par défaut chaque coureur est disponible sur toute la course.
# Format : nom -> liste de (debut_seg_exclu, fin_seg_exclu)
# Un coureur ne peut pas commencer un relais dans une fenêtre d'indisponibilité.
def hour_to_seg(hours_from_start: float) -> int:
    """Convertit une durée depuis le départ en numéro de segment."""
    return int(hours_from_start / SEGMENT_DURATION_H)

UNAVAILABILITY: dict[str, list[tuple[int, int]]] = {
    # Guillaume : indisponible après les premières 24h
    "Guillaume": [(hour_to_seg(24), N_SEGMENTS)],
    # Eric : indisponible après les premières 26h
    "Eric":      [(hour_to_seg(26), N_SEGMENTS)],
    # Clémence : 1 relais sur les 10 premieres heures et 1 relais le dernier jour après 10h
    "Clemence":  [(hour_to_seg(10), hour_to_seg(9+24+10+1))],
}

# --- Contraintes spéciales ---

# Olivier : ses 2 relais de 30km (6 segments chacun) doivent contenir
# 4 segments fixes entre 0h et 2h chaque nuit (les 2 restants sont flottants)
# Nuit 1 : 0h jeudi = 9h après départ → seg 9*9/5 = ~16.2 → seg 16-19 pour 0h-2h
# Nuit 2 : 0h vendredi = 33h après départ → seg 33*9/5 = ~59.4 → seg 59-62

def night_window(night_hour_from_start: float) -> tuple[int, int]:
    """Retourne (premier_seg, dernier_seg) pour une fenêtre 0h-2h d'une nuit."""
    start_seg = hour_to_seg(night_hour_from_start)
    end_seg = hour_to_seg(night_hour_from_start + 2)
    return (start_seg, end_seg)

OLIVIER_NIGHT1 = night_window(9.0)   # 0h jeudi (9h après départ mercredi 15h)
OLIVIER_NIGHT2 = night_window(33.0)  # 0h vendredi (33h après départ)

# Alexis fait ses relais de 30km avec Olivier (même segments)
# → binôme forcé Alexis+Olivier sur ces deux relais

# --- Compatibilités binômes ---
# Qui peut courir avec qui (symétrique)
# Guillaume peut courir avec Pierre et Ludovic uniquement
# Nelly : Gaelle (obligatoire 1x), Clemence (obligatoire 1x), Vincent, Alexandre, Yacine, Antoine
# Gaelle : Nelly (obligatoire 1x), Vincent, Yacine, Alexandre, Antoine

COMPATIBLE = {
    "Pierre":    {"Guillaume", "Ludovic", "Alexis", "Olivier", "Vincent", "Matthieu",
                  "Eric", "Yacine", "Alexandre", "Antoine"},
    "Vincent":   {"Pierre", "Matthieu", "Olivier", "Alexis", "Eric", "Yacine",
                  "Alexandre", "Antoine", "Ludovic", "Nelly", "Gaelle"},
    "Matthieu":  {"Pierre", "Vincent", "Olivier", "Alexis", "Eric", "Yacine",
                  "Alexandre", "Antoine", "Ludovic"},
    "Olivier":   {"Alexis"},  # contraint à courir avec Alexis sur les 30km
    "Alexis":    {"Olivier"},  # idem
    "Guillaume": {"Pierre", "Ludovic"},
    "Eric":      {"Pierre", "Vincent", "Matthieu", "Yacine", "Alexandre", "Antoine", "Ludovic"},
    "Yacine":    {"Pierre", "Vincent", "Matthieu", "Eric", "Alexandre", "Antoine",
                  "Ludovic", "Nelly", "Gaelle"},
    "Alexandre": {"Pierre", "Vincent", "Matthieu", "Eric", "Yacine", "Antoine",
                  "Ludovic", "Nelly", "Gaelle"},
    "Antoine":   {"Pierre", "Vincent", "Matthieu", "Eric", "Yacine", "Alexandre",
                  "Ludovic", "Nelly", "Gaelle"},
    "Ludovic":   {"Pierre", "Guillaume", "Vincent", "Matthieu", "Eric", "Yacine",
                  "Alexandre", "Antoine"},
    "Nelly":     {"Gaelle", "Clemence", "Vincent", "Alexandre", "Yacine", "Antoine"},
    "Gaelle":    {"Nelly", "Vincent", "Yacine", "Alexandre", "Antoine"},
    "Clemence":  {"Nelly"},
}

# Binômes obligatoires (au moins 1 relais ensemble)
MANDATORY_PAIRS = [
    ("Nelly", "Gaelle"),
    ("Nelly", "Clemence"),
    ("Alexis", "Olivier"),  # sur les relais de 30km (x2)
]

# Coureurs autorisés à courir plusieurs fois la nuit
MULTI_NIGHT_ALLOWED = {"Alexis", "Olivier"}

if __name__ == "__main__":
    print(f"Nombre de segments : {N_SEGMENTS}")
    print(f"Segments nuit : {sorted(NIGHT_SEGMENTS)}")
    print(f"Indisponibilité Guillaume : à partir du seg {UNAVAILABILITY['Guillaume'][0][0]}")
    print(f"Indisponibilité Eric      : à partir du seg {UNAVAILABILITY['Eric'][0][0]}")
    print(f"Indisponibilité Clémence  : segs {UNAVAILABILITY['Clemence'][0]}")
    print(f"Olivier nuit 1 (0h-2h jeudi) : segments {OLIVIER_NIGHT1}")
    print(f"Olivier nuit 2 (0h-2h vendredi) : segments {OLIVIER_NIGHT2}")
    print()
    print("Relais par coureur (en segments) :")
    total = 0
    for name, relays in RUNNER_RELAYS.items():
        km = sum(relays) * SEGMENT_KM
        total += km
        print(f"  {name:12s} : {relays}  ({km} km)")
    print(f"  Total engagé : {total} km")
