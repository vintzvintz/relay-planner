"""
exemple.py

Scénario complet pour le modèle à points de passage (waypoints) :
définition des coureurs, gabarits de relais, contraintes et intervalles.
"""

from relay.constraints import Constraints, Preset


# Gabarits PRL (Preset Relay Lengths) réutilisables (target, min, max) en km
# les bornes min/max conditionnent les possibilités de duo, en complément compat_matrix.
R10    = Preset(km=10, min=8,  max=12)
R13    = Preset(km=13, min=11, max=14)
R13_F  = Preset(km=13, min=8,  max=14)
R15    = Preset(km=15, min=13, max=17)
R15_F  = Preset(km=15, min=11, max=17)   # eventuellement baisser le min à 8 ou 10 pour davantage de duo avec les R10
R20    = Preset(km=20, min=16, max=21)
R30    = Preset(km=30, min=25, max=31)

R13_20 = Preset(km=15, min=11, max=21)   # special quentin
R10_15 = Preset(km=10, min=8,  max=17)   # special quentin


c = Constraints(
    parcours="gpx/parcours_avec_waypoints.gpx",
    speed_kmh=9.0,
    start_hour=14.0,
    compat_matrix="compat_exemple.xlsx",
    solo_max_km=17,

    # paramètres par défaut des coureurs - modifiable avec coureur.set_options()
    solo_max_default=1,
    nuit_max_default=1,
    repos_jour_heures=7,
    repos_nuit_heures=9,
    max_same_partenaire=3,    # échangisme minimal
)


# Pauses et intervalles
(c
    # Exemple de pause - placement géographique plutot que horaire
    .add_pause(km=250, duree_heures=1.8)

    # Exemple de point de relais forcé -> pause de durée nulle
    #.add_pause(wp=154, duree_heures=0)

    # intervalles nuits 23h30 → 6h00
    # conditionne la durée de repos et les limites nuit_max par coureur
    .add_night(c.interval_time(start_h=23.5, start_j=0, end_h=6.0, end_j=1))
    .add_night(c.interval_time(start_h=23.5, start_j=1, end_h=6.0, end_j=2))

    # intervalles no-solo 23h30 → 7h00
    #.add_no_solo(c.interval_time(start_h=23.5, start_j=0, end_h=7.0, end_j=1))
    .add_no_solo(c.interval_time(end_h=7.0, end_j=1))  # aucun solo le 1er jour
    .add_no_solo(c.interval_time(start_h=22, start_j=1, end_h=7.0, end_j=2))

    # suggestion : interdire les solos sur les zones non cyclables (accompagnateurs vélo)
    # .add_no_solo(c.interval_km( start_km=666, end_km=666 )
)

# --- Déclaration des coureurs ---
# ils doivent aussi exister dans la matrice de compatibilité
# le paramètre lvl est uniquement une pondération pour l'optimisation des D+
pascal = c.new_runner("Pascal", lvl=3)
arthur = c.new_runner("Arthur", lvl=3)
oscar = c.new_runner("Oscar", lvl=3)
vincent = c.new_runner("Vincent", lvl=1)
martin = c.new_runner("Martin", lvl=3)
gabriel = c.new_runner("Gabriel", lvl=3)
emile = c.new_runner("Emile", lvl=1)
yannick = c.new_runner("Yannick", lvl=1)
adrien = c.new_runner("Adrien", lvl=1)
antoine = c.new_runner("Antoine", lvl=1)
laurent = c.new_runner("Laurent", lvl=3)
nadine = c.new_runner("Nadine", lvl=0)
gaelle = c.new_runner("Gaelle", lvl=0)
clemence = c.new_runner("Clemence", lvl=0)
lucas = c.new_runner("Lucas", lvl=0)
quentin = c.new_runner("Quentin", lvl=3)

# participants optionnels
# alsacien_10 = c.new_runner("Alsacien_10", lvl=3)
# alsacien_15 = c.new_runner("Alsacien_15", lvl=3)


# --- Relais ---


dispo_quentin_nuit = c.interval_time(start_h=22.0, start_j=1, end_h=6.5, end_j=2)  # premier double relais priorisé la nuit
dispo_quentin = c.interval_time(start_h=22.0, start_j=1)
(quentin
    .set_options(solo_max=0, nuit_max=5)
    .set_options(repos_jour=2.5, repos_nuit=2.5)
    .add_relay(R13_20, R13_20, window=dispo_quentin_nuit)      # 2 x 15km
    .add_relay(R10_15, R10_15, R10_15, window=dispo_quentin)     # 3 x 10km
)

(laurent
    .add_relay(R20)
    .add_relay(R15_F)
    .add_relay(R15_F)
    .add_relay(R15_F)
)

(pascal
    .add_relay(R20)
    .add_relay(R15_F)
    .add_relay(R15_F)
    .add_relay(R15_F)
)

(martin
    .add_relay(R15_F)
    .add_relay(R15_F)
    .add_relay(R15_F)
    .add_relay(R15_F)
)

(adrien
    .add_relay(R13_F)
    .add_relay(R15_F)
    .add_relay(R13_F)
    .add_relay(R15_F)
)

(antoine
    .add_relay(R15_F)
    .add_relay(R15_F)
    .add_relay(R15_F)
   # exemple de relais forcé en solo sur une zone précise (propice accompagnateur velo)
   # .add_relay(R13, solo=True, window=c.interval_km(start_km=200, end_km=250))
    .add_relay(R13_F)
)

#lucas_clem = c.new_shared_relay(R10)
(lucas
    .set_options(solo_max=0)
    .add_relay(R10, dplus_max=800)
    .add_relay(R10, dplus_max=800)
    .add_relay(R10, dplus_max=800)
    .add_relay(R10, dplus_max=800)
    #.add_relay(lucas_clem)
)

(vincent
    # test de surcharge des temps de repos
    .set_options(repos_jour=6, repos_nuit=8)
    .add_relay(R13_F)
    .add_relay(R13_F)
    .add_relay(R10)
    .add_relay(R10)
)

# --- participants avec dispo partielle  ---
dispo_gabriel = c.interval_time(end_h=15.0, end_j=1)
(gabriel
    # .set_options( max_same_partenaire=1)        # decommenter pour forcer des binomes différents
    .add_relay(R20, window=dispo_gabriel)
    .add_relay(R20, window=dispo_gabriel)
)

dispo_emile = c.interval_time(end_h=17.0, end_j=1)
(emile
    # .set_options( max_same_partenaire=1)        # decommenter pour forcer des binomes différents
    .add_relay(R15_F, window=dispo_emile)
    .add_relay(R15_F, window=dispo_emile)
)

dispo_yannick = c.interval_time(end_h=17.0, end_j=1)
(yannick
    .set_options(repos_jour=5, repos_nuit=8)
    .set_options( max_same_partenaire=1)
    .add_relay(R10, window=dispo_yannick)
    .add_relay(R15_F, window=dispo_yannick)
    .add_relay(R15_F, window=dispo_yannick)
)

# --- pairing imposé sur les 30km avec placement nuit ---
arthur_oscar_1 = c.new_shared_relay(R30)
arthur_oscar_2 = c.new_shared_relay(R30)
slot_30k_1 = c.interval_time( start_h=22.5, start_j=0, end_h=3.5, end_j=1 )
slot_30k_2 = c.interval_time( start_h=22,   start_j=1, end_h=3,   end_j=2 )

# exemple d'epinglage sur arthur et oscar
#pin_10km = c.new_pin( start_km=10, end_km=20 )
#pin_fin = c.new_pin( end_wp=c.last_point )  # le début du relais reste libre

(arthur
    # max_same_partenaire = 3 correspond à 2x30 + 1x10 avec oscar.
    # Les deux relais restants seront forcés avec d'autres coureurs (ou seul).
    .set_options(nuit_max=5, max_same_partenaire=3)
    .add_relay(arthur_oscar_1, window=slot_30k_1)
    .add_relay(arthur_oscar_2, window=slot_30k_2)
    .add_relay(R10) #, pinned=pin_10km)
    .add_relay(R10)
    .add_relay(R10)
)

(oscar
    .set_options(nuit_max=5, max_same_partenaire=3)
    .add_relay(arthur_oscar_1, window=slot_30k_1)
    .add_relay(arthur_oscar_2, window=slot_30k_2)
    .add_relay(R10)   # relais libre
    .add_relay(R10)
    .add_relay(R10) #, pinned=pin_fin)
)


# binomes imposés
nadine_gaelle = c.new_shared_relay(R10)
nadine_clem = c.new_shared_relay(R10)

#fixe un nombre max de relais entre 2 coureurs
c.add_max_duos(gaelle, nadine, nb=1)
c.add_max_duos(gaelle, lucas, nb=1)

(nadine
    .set_options(solo_max=0)
    .set_options(nuit_max=0)  # pas de nuit
    .add_relay(nadine_clem, dplus_max=600)
    .add_relay(nadine_gaelle, dplus_max=600)
    .add_relay(R10, dplus_max=600)
    .add_relay(R10, dplus_max=600)
)

(gaelle
    .set_options(solo_max=0)
    .set_options(nuit_max=0)  # pas de nuit
    .add_relay(nadine_gaelle)
    .add_relay(R13_F)
    .add_relay(R10)
    .add_relay(R10)
)

dispo_clemence1 = c.interval_time(end_h=23, end_j=0)    # debut implicite
dispo_clemence2 = c.interval_time(start_h=9, start_j=2)   # fin implicite
dispo_clemence = [ dispo_clemence1, dispo_clemence2 ]    # ensemble d'intervalles
(clemence
    .set_options(solo_max=0)
    .add_relay(nadine_clem, window=dispo_clemence)
    .add_relay(R10, window=dispo_clemence)
)

#--- Participation incertaine : 2 alsaciens en bonus ---
# dispo_site = c.interval_time(start_h=6.5, start_j=2) # de 6h30 jusqu'à la fin
# (alsacien_10
#     #.set_options(solo_max=0)
#     .add_relay(R10, window=dispo_site)
# )
# (alsacien_15
#     #.set_options(solo_max=0)
#     .add_relay(R15_F, window=dispo_site)
# )


if __name__ == "__main__":
    # c.to_json("constraints.json")   # pour debug
    from relay import entry_point
    entry_point(c)
