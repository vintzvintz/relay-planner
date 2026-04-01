"""
Données du problème
"""

from relay import Constraints, Intervals, R10, R13_F, R15, R15_F, R20, R30
from compat import COMPAT_MATRIX


# --- Données générales de la course ---
c = Constraints(
    total_km=440,
    nb_segments=176, # valeurs typiques  : 440=1k, 290=1k5 220=2k, 176=2k5 135=3k3, 88=5k
    speed_kmh=9.0,
    start_hour=15.0,  # départ à 15 heures pile
    solo_max_km=17,  # pas de solo sur 17km et plus
    solo_max_default=1,  # 1 relais solo max par coureur
    nuit_max_default=1,  # 1 relais nocturne max par coureur
    repos_jour_heures=7,
    repos_nuit_heures=9,
    nuit_debut=23.5,  # définition des relais nocturnes (repos nuit si au moins 1 segment dans cette plage)
    nuit_fin=6.0,
    solo_autorise_debut=6.5,  # plage d'autorisation des solos (indépendante de nuit_debut/nuit_fin)
    solo_autorise_fin=23.0,
    max_same_partenaire=2,  # nombre maximal de binômes entre deux mêmes coureurs
    compat_matrix=COMPAT_MATRIX,
    enable_flex=False,   # si False, ignore la flexibilité à la baisse
    allow_flex_flex=True,  # autorise un relais plus court que le max commun de deux flexibles (trouve plus vite une 1ere solution moins optimale)
    profil_csv="gpx/altitude.csv",
)

# Exempe de pause : jeudi 19h00 pour la pasta party
c.add_pause(seg=c.km_to_seg(250), duree=1.8)  # placement géographique plutot que horaire
#c.add_pause(seg=c.hour_to_seg(19.0, jour=1), duree=2)  # jeudi 15h00 (mercredi 15h + 24h), durée 1h30

# --- Déclaration des coureurs ---
# ils doivent aussi exister dans la matrice de compatibilité
pierre = c.new_runner("Pierre")
alexis = c.new_runner("Alexis")
olivier = c.new_runner("Olivier")
vincent = c.new_runner("Vincent")
matthieu = c.new_runner("Matthieu")
guillaume = c.new_runner("Guillaume")
eric = c.new_runner("Eric")
yacine = c.new_runner("Yacine")
alexandre = c.new_runner("Alexandre")
antoine = c.new_runner("Antoine")
ludovic = c.new_runner("Ludovic")
nelly = c.new_runner("Nelly")
gaelle = c.new_runner("Gaelle")
clemence = c.new_runner("Clemence")
leo = c.new_runner("Leo")
alsacien_10 = c.new_runner("Alsacien_10")
alsacien_15 = c.new_runner("Alsacien_15")


# --- Relais ---

(ludovic
    .add_relay(R20)
    .add_relay(R15_F, nb=3)
)

(pierre
    # pinned = test de relais fixé après un premier 10km
    #.add_relay( R20, pinned=c.size_of(R10))
    .add_relay(R20)
    .add_relay(R15_F, nb=3)
)

(matthieu
    .add_relay(R15_F, nb=4)
)

(alexandre
    .add_relay(R13_F, nb=2)
    .add_relay(R15_F, nb=2)
)

(antoine
    .add_relay(R15_F, nb=2)
    .add_relay(R15_F)
    .add_relay(R13_F)
)

leo_clem = c.new_relay(R10)
(leo
    .set_options(solo_max=0)
    .add_relay(R10, nb=4)
    #.add_relay(leo_clem)
)

(vincent
    # test de surcharge des temps de repos
    .set_options(repos_jour=6, repos_nuit=8)
    .add_relay(R13_F, nb=2)# 2x3km en 'upside' sur le 10km demandé, comme certains aiment le dire :)
    .add_relay(R10, nb=2)
)

# --- participants avec dispo partielle  ---
# la disponibilité est associée à chaque relais plutot que globalement au coureur pour une modélisation plus fine.
# ceci permet de contraindre seulement une partie des relais,
# Exemple : 1 gros relais le premier jour puis un petit relais le dernier jour.
dispo_guillaume = Intervals([(0, c.hour_to_seg(15.0, jour=1))])
(guillaume
    # .set_options( max_same_partenaire=1)        # decommenter pour forcer des binomes différents
    # .add_relay(R20, window=dispo_guillaume, pinned=c.size_of(R10))
    .add_relay(R20, nb=2, window=dispo_guillaume)
)

dispo_eric = Intervals([(0, c.hour_to_seg(17.0, jour=1))])
(eric
    # .set_options( max_same_partenaire=1)        # decommenter pour forcer des binomes différents
    .add_relay(R15_F, nb=2, window=dispo_eric)
)

dispo_yacine = Intervals([(0, c.hour_to_seg(17.0, jour=1))])
(yacine
    .set_options(repos_jour=5, repos_nuit=8)
    # .set_options( max_same_partenaire=1)        # decommenter pour forcer des binomes différents
    .add_relay(R10, window=dispo_yacine)
    .add_relay(R15_F, window=dispo_yacine)
    #.add_relay(R15_F, window=dispo_yacine)
)

# --- coureurs elite - pairing imposé sur les 30km avec placement nuit ---
alexis_olivier_1 = c.new_relay(R30)
alexis_olivier_2 = c.new_relay(R30)
# entre 22h30 et 3h
nuit1_30k = Intervals( [(c.hour_to_seg(23, jour=0), c.hour_to_seg(3, jour=1))] )
nuit2_30k = Intervals( [(c.hour_to_seg(23, jour=1), c.hour_to_seg(3, jour=2))] )

(alexis
    # max_same_partenaire = 3 correspond à 2x30 + 1x10 avec olivier.
    # Les deux relais restants seront forcés avec d'autres coureurs (ou seul).
    .set_options(nuit_max=5, max_same_partenaire=3)
    .add_relay(alexis_olivier_1, window=nuit1_30k)
    .add_relay(alexis_olivier_2, window=nuit2_30k)
    #.add_relay(alexis_olivier_2, window=nuit2_30k, pinned=c.km_to_seg(270))  # test : pinned sur point kilometrique
    #.add_relay(R10, pinned=0)   # premier relais forcé
    .add_relay(R10)   # placement libre
    .add_relay(R10, nb=2)  # 2 relais de 10km contraints uniquement par le repos
)

(olivier
    .set_options(nuit_max=5, max_same_partenaire=3)
    .add_relay(alexis_olivier_1, window=nuit1_30k)
    .add_relay(alexis_olivier_2, window=nuit2_30k)
    .add_relay(R10, nb=2)
    #.add_relay(R10, pinned=c.last_active_seg - c.size_of(R10))  # forcé sur derniers segments
    .add_relay(R10)   # relais libre
)


# binomes imposés
nelly_gaelle = c.new_relay(R10)
nelly_clem = c.new_relay(R10)
# segments nuit selon heures de début/fin de nuit passés à RelayConstraints
girls_night = c.night_windows()

#fixe un nombre max de relais entre 2 courreurs
c.add_max_binomes(gaelle, nelly, nb=1)
c.add_max_binomes(gaelle, leo, nb=1)

(nelly
    #.set_options(solo_max=0)
    #.add_relay(nelly_gaelle, window=girls_night)
    .set_options(nuit_max=0)  # pas de nuit
    .add_relay(nelly_clem)
    .add_relay(nelly_gaelle)
    .add_relay(R10, nb=2)
)

(gaelle
    #.set_options(solo_max=0)
    #.add_relay(nelly_gaelle, window=girls_night)
    .set_options(nuit_max=0)  # pas de nuit
    .add_relay(nelly_gaelle)
    .add_relay(R13_F)
    .add_relay(R10, nb=2)
)

# Astuce : 1 relais par intervalle est plus performant que 2 relais sur l'union de 2 intervalles
dispo_clemence1 = Intervals([(0, c.hour_to_seg(23, jour=0))])
dispo_clemence2 = Intervals([(c.hour_to_seg(9, jour=2), c.last_active_seg)])
(clemence
    #.set_options(solo_max=0)
    .add_relay(nelly_clem, window=dispo_clemence1)
#    .add_relay(R10, window=dispo_clemence2)
)


# --- Alsaciens: 2 relais en bonus ---
dispo_site = Intervals([(c.hour_to_seg(6.5, jour=2), c.last_active_seg)]) # de 6h30 jusqu'à la fin

(alsacien_10
    #.set_options(solo_max=0)
    .add_relay(R10, window=dispo_site)
)
(alsacien_15
    #.set_options(solo_max=0)
    .add_relay(R15_F, window=dispo_site)
)


##################################################################################

if __name__ == "__main__":
    # Usage :
    #   python replanif/replanif.py --replanif replanif/solution_reference.json --min-score 88
    from relay import entry_point
    entry_point(c)
