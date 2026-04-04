# relais-planner

Planificateur de course en relais par contraintes (CP-SAT).

Problème : Lyon → Fessenheim, 440 km, ~176 segments (2,5 km/segment), vitesse ~9 km/h, départ mercredi 15h00.
15 coureurs doivent couvrir chaque segment (1 ou 2 coureurs par segment).
L'objectif est de maximiser un score mixte (binômes pondérés par compatibilité + bonus km flex).

## Prérequis

Python 3.10+, puis :

```bash
python -m venv venv
source venv/Scripts/activate
pip install -r requirements.txt
```

## Déclaration des contraintes

Le problème est défini via une API déclarative dans `example.py` :

```python
from relay import Constraints, Intervals, R20, R15_F, R30, solve

c = Constraints(total_km=440, nb_segments=176, ...)

pierre = c.new_runner("Pierre")
pierre.add_relay(R20).add_relay(R15_F, nb=3)

nuit1 = c.new_relay(R30)           # relais partagé (binôme forcé)
alexis.add_relay(nuit1, window=nuit1_30k)
olivier.add_relay(nuit1, window=nuit1_30k)

solve(c)
```

Voir [CONSTRAINTS.md](docs/CONSTRAINTS.md) pour la référence complète de l'API.

## Utilisation

```bash
python example.py              # résoudre (défaut)
python example.py --summary    # résumé des données et borne LP
python example.py --diag       # diagnostic de faisabilité
python example.py --model      # construction du modèle uniquement
python example.py --dplus                              # résoudre en maximisant le D+/D- pondéré par lvl
python example.py --dplus --min-score 88               # idem avec score minimal garanti
python example.py --replanif ref.json                  # replanifier en minimisant la distance à une référence
python example.py --replanif ref.json --min-score 88   # idem avec score minimal
```

Toutes les options CLI passent par `relay.entry_point()`.

## Structure du projet

`example.py` déclare les paramètres globaux du parcours, les coureurs et leurs relais via l'API du package `relay`, et délègue à `relay.entry_point(c)`.

`relay/` est le package Python contenant le solveur. Voir [RELAY-PLANNER.md](RELAY-PLANNER.md) pour la description détaillée de chaque module et de l'API publique.

`compat.py` contient `COMPAT_MATRIX`, les scores de compatibilité (0, 1 ou 2) pour chaque paire de coureurs — généré automatiquement depuis `compat_coureurs.xlsx` par `utils/refresh_compat.py`.

## Sorties

| Dossier / fichier  | Contenu                                                                                          |
|--------------------|--------------------------------------------------------------------------------------------------|
| `plannings/`       | Plannings `.txt`, `.csv`, `.json`, `.html` et `.gpx` produits par `relay.solve()`                |
|                    | Le `.gpx` est généré si `parcours_gpx=` est renseigné dans `Constraints` (export GPX + KML dispo) |

## Documentation

- [USAGE.md](docs/USAGE.md) — Guide d'utilisation détaillé (mode simple, mode avancé, utilitaires)
- [RELAY-PLANNER.md](docs/RELAY-PLANNER.md) — Description des modules du package `relay` et API publique
- [CONSTRAINTS.md](docs/CONSTRAINTS.md) — Référence complète de l'API de déclaration des contraintes
- [REPLANIF.md](docs/REPLANIF.md) — Workflow de replanification (métrique de distance, exemples, API CLI et scriptable)

## Licence

MIT — voir [LICENSE](LICENSE).
