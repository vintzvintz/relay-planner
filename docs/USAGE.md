# Guide d'utilisation

Ce guide décrit les deux modes d'utilisation du solveur. Les données d'entrée (coureurs, relais, contraintes) sont toujours déclarées via un objet `Constraints` — voir [CONSTRAINTS.md](CONSTRAINTS.md) pour la référence complète de l'API.

---

## Mode simple

Le mode simple convient à la majorité des usages : résoudre, replanifier, diagnostiquer, afficher le résumé. Tout passe par `entry_point()` qui parse la ligne de commande et dispatche le mode souhaité.

### Structure type (`example.py`)

```python
from relay.constraints import Constraints, Preset
from relay import entry_point

R15 = Preset(km=15, min=13, max=17)
R20 = Preset(km=20, min=16, max=21)

c = Constraints(
    parcours_gpx="gpx/parcours.gpx",   # waypoints + profil altimétrique + export GPX/KML
    speed_kmh=9.0, start_hour=14.0,
    compat_matrix="compat_coureurs.xlsx",
    solo_max_km=17, solo_max_default=1,
    nuit_max_default=1, repos_jour_heures=7, repos_nuit_heures=9,
)

c.add_night(c.interval_time(start_h=23.5, start_j=0, end_h=6.0, end_j=1))

alice = c.new_runner("Alice", lvl=3)
alice.add_relay(R20).add_relay(R15).add_relay(R15).add_relay(R15)

bob = c.new_runner("Bob", lvl=2)
bob.add_relay(R15).add_relay(R15).add_relay(R15).add_relay(R15)

if __name__ == "__main__":
    entry_point(c)   # dispatch selon sys.argv
```

### Commandes disponibles

```bash
python example.py                           # résoudre (défaut)
python example.py data                      # résumé des données
python example.py diag                      # diagnostic de faisabilité
python example.py dplus                     # résoudre en maximisant D+/D- pondéré
python example.py dplus --min-score 88      # idem avec score minimal garanti
python example.py solve --min-score 88      # résoudre avec score minimal garanti
python example.py solve --ref hint.json     # résoudre avec hint initial
python example.py replanif --ref ref.json   # replanifier (minimiser écarts)
python example.py solve --no-split          # désactiver l'export GPX/KML individuels (activé par défaut)
```

L'action est un **argument positionnel** (pas un flag). `--ref <fichier.json>` sert de hint pour `solve`/`dplus` et de référence obligatoire pour `replanif`.

Les plannings produits (`.json`, `.csv`, `.html`, `.txt`) sont écrits dans `plannings/<ts>_<action>/` avec un horodatage. Si `parcours_gpx=` est renseigné dans les contraintes, `.gpx` est également produit. Les fichiers GPX/KML individuels par relais vont dans `plannings/<ts>_<action>/split/`.

### Mode `dplus` — maximiser le dénivelé des coureurs forts

Ce mode remplace l'objectif par défaut (maximiser les binômes compatibles) par une maximisation pondérée du dénivelé total D+ + D− cumulé sur tous les relais, avec un poids par coureur défini par `lvl`.

**Prérequis :** `parcours_gpx=` doit pointer vers un GPX contenant un profil altimétrique, et au moins un coureur doit avoir un `lvl` non nul.

```python
alice = c.new_runner("Alice", lvl=3)   # coureur fort → poids 3
bob   = c.new_runner("Bob",   lvl=1)   # coureur léger → poids 1
carol = c.new_runner("Carol", lvl=0)   # ignoré dans l'objectif D+
```

```bash
python example.py dplus                 # maximise sum(lvl[r] * (D+ + D-)[r])
python example.py dplus --min-score 80  # idem, score binômes >= 80 garanti
python example.py dplus --ref hint.json # idem, avec hint initial
```

**Contrainte `dplus_max` sur un relais individuel :** indépendamment du mode solveur, il est possible de limiter le dénivelé d'un relais donné directement dans la déclaration :

```python
runner.add_relay(R20, dplus_max=500)   # D+ + D- ≤ 500 m pour ce relais
```

Cette contrainte est active dans tous les modes (solve, dplus, replanif). Voir [CONSTRAINTS.md](CONSTRAINTS.md#paramètre-dplus_max) pour les détails.

### Export GPX / KML

Si `parcours_gpx=` est renseigné dans `Constraints`, `solution.save()` génère automatiquement `.gpx` et `.kml` en plus des sorties habituelles.

Le fichier GPX contient :
- un `<trk>` par relais (découpe de la trace source entre `start_km` et `end_km`)
- un `<wpt>` par borne de relais unique

Le fichier KML (Google Maps / Google Earth) contient :
- une `<Folder>` par coureur avec ses lignes de parcours, colorées par coureur
- des marqueurs aux points de passage

Pour importer dans **Google Mes Cartes** : [mymaps.google.com](https://mymaps.google.com) → Importer → choisir le `.kml`.

### Export GPX/KML individuels par relais

L'export GPX/KML par relais est **activé par défaut**. Il génère un fichier GPX et KML par relais, dans un sous-répertoire horodaté sous `plannings/`. Pour le désactiver :

```bash
python example.py solve --no-split
```

Les fichiers sont nommés avec le timestamp, le partenaire et le coureur pour faciliter la distribution.

### Avantages / inconvénients

| | |
|---|---|
| **Avantage** | Code minimal — imports + `entry_point(c)` |
| **Inconvénient** | Personnalisation limitée aux options de la ligne de commande |

---

## Mode avancé

Le mode avancé donne un accès direct à chaque étape du pipeline : construction du modèle, ajout de contraintes supplémentaires, choix de la fonction objectif, itération sur les solutions. Il est adapté à :

- L'exploration automatisée de variantes (ex : forcer `solo_max=0`, bloquer la nuit, tester plusieurs horizons)
- La mise à jour dynamique des contraintes (ex : épingler les relais courus depuis un fichier CSV)
- La génération de solutions en boucle avec exploitation directe (sans passer par save/load JSON)

### Pipeline complet

```python
from relay.constraints import Constraints, Preset
from relay.model import build_model
from relay import Solver, Solution

R15 = Preset(km=15, min=13, max=17)
R20 = Preset(km=20, min=16, max=21)

# 1. Déclarer les contraintes
c = Constraints(
    parcours_gpx="gpx/parcours.gpx",
    speed_kmh=9.0, start_hour=14.0,
    compat_matrix="compat_coureurs.xlsx", ...
)
alice = c.new_runner("Alice", lvl=3)
alice.add_relay(R20).add_relay(R15).add_relay(R15).add_relay(R15)

# 2. Construire le modèle CP-SAT
m = build_model(c)

# 3. Ajouter des contraintes supplémentaires (optionnel)
m.add_min_score(c, 80)           # score de compatibilité minimal

# 4. Choisir la fonction objectif
m.add_optimisation_func(c)       # maximise score binômes
# ou : m.add_optimise_dplus(c)   # maximise D+/D- pondéré par lvl

# 5. Lancer le solveur (itérateur streaming)
from relay import _make_base
base = _make_base("solve")
solver = Solver(m, c)
for sol in solver.solve(timeout_sec=120):
    print(sol.to_text())         # exploiter directement
    sol.save(base=base)          # ou sauvegarder dans plannings/<ts>_solve/
```

### Sorties personnalisées

`save()` accepte des flags pour choisir les formats à produire (tous `True` par défaut) :

```python
base = _make_base("solve")
for sol in solver.solve(timeout_sec=120):
    sol.save(base=base, html=False, gpx=False)   # uniquement JSON, CSV et texte
    sol.save(base=base, as_json=True, csv=True, html=True, txt=True, gpx=True, kml=True)
```

### Replanification en mode avancé

```python
from relay.model import build_model
from relay import Solver, Solution

ref = Solution.from_json("plannings/ref.json")

m = build_model(c)
m.add_minimise_differences_with(ref, c)   # objectif : minimiser les écarts
m.add_min_score(c, 85)                    # optionnel : garantir un score minimal

base = _make_base("replanif")
solver = Solver(m, c)
for sol in solver.solve(timeout_sec=300):
    sol.save(base=base)
```

### Exploration de variantes

```python
def make_constraints(solo_max=1, nuit_max=1):
    c = Constraints(
        parcours_gpx="gpx/parcours.gpx",
        ..., solo_max_default=solo_max, nuit_max_default=nuit_max
    )
    # ... déclarer les coureurs ...
    return c

for solo in (0, 1):
    for nuit in (0, 1):
        c = make_constraints(solo_max=solo, nuit_max=nuit)
        m = build_model(c)
        m.add_optimisation_func(c)
        base = _make_base(f"solve_s{solo}_n{nuit}")
        for sol in Solver(m, c).solve(timeout_sec=60):
            print(f"solo={solo} nuit={nuit} score={sol.stats().score_duos}")
            sol.save(base=base)
```

### Warm-start (hint)

Injecter une solution existante comme point de départ accélère la recherche :

```python
ref = Solution.from_json("plannings/ref.json")
m = build_model(c)
m.add_optimisation_func(c)
m.add_hint_from_solution(ref)   # hint CP-SAT sur les variables start/end

base = _make_base("solve")
for sol in Solver(m, c).solve(timeout_sec=120):
    sol.save(base=base)
```

> **Avertissement** : CP-SAT ignore le hint en totalité si l'une des valeurs suggérées viole une contrainte du modèle. Si les contraintes ont changé par rapport à la solution de référence (coureur retiré, pause déplacée, fenêtre de disponibilité modifiée…), le hint risque d'être silencieusement ignoré. Dans ce cas, le mode replanification (`add_minimise_differences_with`) est plus adapté.

### Avantages / inconvénients

| | |
|---|---|
| **Avantages** | Flexibilité maximale ; exploitation directe des solutions sans I/O JSON intermédiaire |
| **Inconvénients** | Plus de code ; API plus complexe qu'`entry_point()` |

---

## Utilitaires (`utils/`)

### `utils/reformat.py` — Régénération des sorties sans résoudre

Recharge une solution JSON existante et régénère les fichiers de sortie (HTML, GPX, etc.) sans relancer le solveur.

```bash
python utils/reformat.py                                          # dernier planning dans plannings/
python utils/reformat.py plannings/X/planning.json               # fichier spécifique
```

### `utils/update_reference.py` — Mise à jour de la solution de référence

Détecte le timestamp le plus récent dans `plannings/` et copie tous les formats associés (`.txt`, `.csv`, `.json`, `.html`, `.gpx`, `.kml`) vers `replanif/reference.*`.

```bash
python utils/update_reference.py
```

À lancer avant une replanification pour garantir que `replanif/reference.json` correspond bien au dernier planning produit.
