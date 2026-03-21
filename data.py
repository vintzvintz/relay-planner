"""
Données du problème
"""

from constraints import RelayConstraints, RelayIntervals
from compat import COMPAT_MATRIX


ENABLE_FLEX = True  # si False, ignore la flexibilité à la baisse

# --- Constantes de type de relais : set des tailles permises (en segments) ---
R10       = {3}      # 10 km fixe
R15       = {5}      # 16 km fixe
R20       = {6}      # 19 km fixe
R30       = {9}      # 30 km
if ENABLE_FLEX:
    R13_F  = {3, 4}    # 10 à 13 km
    R15_F  = {3, 4, 5} # 10 à 16 km
else:
    R13_F  = {4}
    R15_F  = {5}


c = RelayConstraints(
    total_km=440,
    nb_segments=135,
    speed_kmh=9.0,
    start_hour=15.0,     # départ à 15 heures
    solo_max_km=17,      # pas de solo sur 17km et plus
    solo_max_default=1,   # 1 relais solo max par coureur
    nuit_max_default=1,   # 1 relais nocturne max par coureur
    repos_jour_heures=7,
    repos_nuit_heures=9,
    nuit_debut=0,          # définition des relais nocturnes
    nuit_fin=6,
    max_same_partenaire=2, # nombre maximal de binômes entre deux mêmes coureurs
    compat_matrix=COMPAT_MATRIX,
)


# --- Plages temporelles ---
nuit1_30k   = RelayIntervals([(c.hour_to_seg(23.5, jour=0), c.hour_to_seg(4, jour=1))])  # entre 23h30 et 4h
nuit2_30k   = RelayIntervals([(c.hour_to_seg(23.5, jour=1), c.hour_to_seg(4, jour=2))])  # entre 23h30 et 4h
girls_night = c.night_windows()

# --- Coureurs ---
pierre    = c.new_runner("Pierre")
alexis    = c.new_runner("Alexis",    nuit_max=5)
olivier   = c.new_runner("Olivier",   nuit_max=5)
vincent   = c.new_runner("Vincent",   repos_jour=6, repos_nuit=8)
matthieu  = c.new_runner("Matthieu")
guillaume = c.new_runner("Guillaume")
eric      = c.new_runner("Eric")
yacine    = c.new_runner("Yacine",    repos_jour=5, repos_nuit=8)
alexandre = c.new_runner("Alexandre")
antoine   = c.new_runner("Antoine")
ludovic   = c.new_runner("Ludovic")
nelly     = c.new_runner("Nelly")
gaelle    = c.new_runner("Gaelle")
clemence  = c.new_runner("Clemence")
leo       = c.new_runner("Leo",       solo_max=0)

# --- Disponibilités (fenêtres communes) ---
dispo_guillaume   = RelayIntervals([(0, c.hour_to_seg(15.0, jour=1))])
dispo_eric_yacine = RelayIntervals([(0, c.hour_to_seg(17.0, jour=1))])
dispo_clemence    = RelayIntervals([  # deux intervalles
    (0, c.hour_to_seg(23, jour=0)),
    (c.hour_to_seg(11, jour=2), c.nb_segments),
])

# --- Relais ---

(pierre
    .add_relay(R20, pinned=3)   # pinned = exemple de relais fixé au segment 3 (10eme km) ou déja couru
    .add_relay(R15_F, nb=3))


# pairing imposé
alexis_olivier_1 = c.new_relay(R30)
alexis_olivier_2 = c.new_relay(R30)

(alexis
    .set_max_same_partenaire(4)  # au moins un relais avec qqun d'autre que olivier, ou seul
    .add_relay(alexis_olivier_1, window=nuit1_30k)
    .add_relay(alexis_olivier_2, window=nuit2_30k)
    .add_relay(R10, pinned=0)   # premier relais
    .add_relay(R10, nb=2))

(olivier
    .set_max_same_partenaire(4)  # au moins un relais avec qqun d'autre que Alexis, ou seul
    .add_relay(alexis_olivier_1, window=nuit1_30k)
    .add_relay(alexis_olivier_2, window=nuit2_30k)
    .add_relay(R10, nb=2)
    .add_relay(R10, pinned=c.nb_segments - 3))  # dernier relais

(vincent
    .add_relay(R13_F, nb=2)  # 2x3km en 'upside' comme certains aiment le dire :)
    .add_relay(R10, nb=2))

matthieu.add_relay(R15_F, nb=4)

(guillaume
    #.set_max_same_partenaire(1)        # decommenter pour forcer des binomes différents
    .add_relay(R20, window=dispo_guillaume, pinned=3)
    .add_relay(R20, window=dispo_guillaume))

(eric
    #.set_max_same_partenaire(1)        # decommenter pour forcer des binomes différents
    .add_relay(R15, nb=2, window=dispo_eric_yacine))

(yacine
     #.set_max_same_partenaire(1)       # decommenter pour forcer des binomes différents
    .add_relay(R10, window=dispo_eric_yacine)
    .add_relay(R15_F, window=dispo_eric_yacine)
    .add_relay(R15_F, window=dispo_eric_yacine))

(alexandre
    .add_relay(R13_F, nb=2)
    .add_relay(R15_F, nb=2))

(antoine
    .add_relay(R15, nb=2)
    .add_relay(R15_F)
    .add_relay(R13_F))

(ludovic
    .add_relay(R20)
    .add_relay(R15, nb=3))


# binomes imposés
nelly_gaelle = c.new_relay(R10)
nelly_clemence = c.new_relay(R10)

c.add_max_binomes(gaelle, nelly, nb=1)

(nelly
    .add_relay(nelly_gaelle, window=girls_night)
    .add_relay(nelly_clemence)
    .add_relay(R10, nb=2))

(gaelle
    .add_relay(nelly_gaelle, window=girls_night)
    .add_relay(R13_F)
    .add_relay(R10, nb=2))

(clemence
    .add_relay(nelly_clemence, window=dispo_clemence)
    .add_relay(R10, window=dispo_clemence))

leo.add_relay(R10, nb=4)


##################################################################################

def build_constraints() -> RelayConstraints:
    """Retourne le RelayConstraints construit à partir des données module-level."""
    return c

if __name__ == "__main__":
    c.print_summary()
