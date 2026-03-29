# Guide d'utilisation

Ce guide décrit les deux modes d'utilisation du solveur. Les données d'entrée (coureurs, relais, contraintes) sont toujours déclarées via un objet `Constraints` — voir [CONSTRAINTS.md](CONSTRAINTS.md) pour la référence complète de l'API.

---

## Mode simple

Le mode simple convient à la majorité des usages : résoudre, replanifier, diagnostiquer, afficher le résumé. Tout passe par `entry_point()` qui parse la ligne de commande et dispatche le mode souhaité.

### Structure type (`example.py`)

```python
from relay import Constraints, Intervals, R15, R20, solve, entry_point
from compat import COMPAT_MATRIX

# Contraintes déclarées au niveau module
c = Constraints(
    total_km=440, nb_segments=176, speed_kmh=9.0, start_hour=15.0,
    compat_matrix=COMPAT_MATRIX, solo_max_km=17, solo_max_default=1,
    nuit_max_default=1, repos_jour_heures=7, repos_nuit_heures=9,
    nuit_debut=23.5, nuit_fin=6.0,
)

alice = c.new_runner("Alice")
alice.add_relay(R20).add_relay(R15, nb=3)

bob = c.new_runner("Bob")
bob.add_relay(R15, nb=4)

if __name__ == "__main__":
    entry_point(c)   # dispatch selon sys.argv
```

### Commandes disponibles

```bash
python example.py                                      # résoudre (défaut)
python example.py --summary                            # résumé des données et borne LP
python example.py --diag                               # diagnostic de faisabilité
python example.py --model                              # construire le modèle sans résoudre
python example.py --replanif ref.json                  # replanifier (minimiser écarts)
python example.py --replanif ref.json --min-score 88   # idem avec score minimal garanti
```

Les plannings produits (`.txt`, `.csv`, `.json`, `.html`) sont écrits dans `plannings/` avec un horodatage.

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
from relay import Constraints, Intervals, R15, R20
from relay import model as build_model, Solver, Solution
from compat import COMPAT_MATRIX

# 1. Déclarer les contraintes (peut être dans une fonction ou une sous-classe)
c = Constraints(
    total_km=440, nb_segments=176, speed_kmh=9.0, start_hour=15.0,
    compat_matrix=COMPAT_MATRIX, ...
)
alice = c.new_runner("Alice")
alice.add_relay(R20).add_relay(R15, nb=3)

# 2. Construire le modèle CP-SAT
m = build_model(c)

# 3. Ajouter des contraintes supplémentaires (optionnel)
m.add_min_score(c, 80)           # score de compatibilité minimal

# 4. Choisir la fonction objectif
m.add_optimisation_func(c)       # maximise score binômes - pénalité flex

# 5. Lancer le solveur (itérateur streaming)
solver = Solver(m, c)
for sol in solver.solve(timeout_sec=120):
    print(sol.to_text())         # exploiter directement
    sol.save()                   # ou sauvegarder dans plannings/
```

### Replanification en mode avancé

```python
from relay import Solution, model as build_model, Solver

ref = Solution.from_json("plannings/ref.json")

m = build_model(c)
m.add_minimise_differences_with(ref)   # objectif : minimiser les écarts
m.add_min_score(c, 85)                 # optionnel : garantir un score minimal

solver = Solver(m, c)
for sol in solver.solve(timeout_sec=300):
    sol.save()
```

### Exploration de variantes

```python
def make_constraints(solo_max=1, nuit_max=1):
    c = Constraints(..., solo_max_default=solo_max, nuit_max_default=nuit_max)
    # ... déclarer les coureurs ...
    return c

for solo in (0, 1):
    for nuit in (0, 1):
        c = make_constraints(solo_max=solo, nuit_max=nuit)
        m = build_model(c)
        m.add_optimisation_func(c)
        for sol in Solver(m, c).solve(timeout_sec=60):
            print(f"solo={solo} nuit={nuit} score={sol.stats()[0]}")
            sol.save()
```

### Warm-start (hint)

Injecter une solution existante comme point de départ accélère la recherche :

```python
ref = Solution.from_json("plannings/ref.json")
m = build_model(c)
m.add_optimisation_func(c)
m.add_hint(ref)                # hint CP-SAT sur les variables start

for sol in Solver(m, c).solve(timeout_sec=120):
    sol.save()
```

> **Avertissement** : CP-SAT ignore le hint en totalité si l'une des valeurs suggérées viole une contrainte du modèle. Si les contraintes ont changé par rapport à la solution de référence (coureur retiré, pause déplacée, fenêtre de disponibilité modifiée…), le hint risque d'être silencieusement ignoré sans bénéfice sur la vitesse de convergence. Dans ce cas, le [mode replanification](REPLANIF.md) (`add_minimise_differences_with`) est plus adapté : il encode explicitement la proximité à la référence dans la fonction objectif, indépendamment des contraintes.

### Avantages / inconvénients

| | |
|---|---|
| **Avantages** | Flexibilité maximale ; exploitation directe des solutions sans I/O JSON intermédiaire |
| **Inconvénients** | Plus de code ; API plus complexe qu'`entry_point()` |

---

## Utilitaires (`utils/`)

### `utils/refresh_compat.py` — Régénération de la matrice de compatibilité

Lit `compat_coureurs.xlsx` (triangle inférieur, scores 0/1/2) et régénère `compat.py`.

```bash
python utils/refresh_compat.py
```

À relancer après chaque modification du fichier Excel. Le script valide la structure (matrice carrée, diagonale `X`, triangle supérieur vide) et lève une erreur explicite en cas de problème. Ne pas modifier `compat.py` manuellement.

### `utils/update_reference.py` — Mise à jour de la solution de référence

Copie les fichiers du planning le plus récent de `plannings/` vers `replanif/reference.*` (`.txt`, `.csv`, `.json`, `.html`).

```bash
python utils/update_reference.py
```

À utiliser avant de lancer une replanification : garantit que `replanif/reference.json` correspond bien au dernier planning produit. Voir [REPLANIF.md](REPLANIF.md) pour le workflow complet.
