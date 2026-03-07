# relais-planner

Planificateur de course en relais par contraintes (CP-SAT).

Problème : Lyon → Fessenheim, 440 km, 88 segments de 5 km, vitesse ~9 km/h, départ mercredi 15h00.
14 coureurs doivent couvrir chaque segment (1 ou 2 coureurs par segment).
L'objectif est de maximiser le nombre de relais courus en binôme.

## Prérequis

Python 3.10+, puis :

```bash
python -m venv venv
source venv/bin/activate   # Windows : venv\Scripts\activate
pip install -r requirements.txt
```

## Scripts

### `data.py`
Toutes les constantes et données du problème : coureurs, relais engagés, indisponibilités,
compatibilités binômes, fenêtres de nuit. Peut être exécuté directement pour vérifier la
cohérence des données.

```bash
python data.py
```

### `constraint_model.py`
Construction du modèle CP-SAT (variables, contraintes). Importé par les autres scripts,
pas destiné à être exécuté directement.

### `solver.py`
Résout le problème une fois, maximise les binômes, écrit le planning dans `plannings/`.

```bash
python solver.py
```

### `upper_bound.py`
Calcule un majorant analytique du nombre de binômes atteignables (matching biparti +
contrainte de couverture), sans lancer de solveur CP-SAT.

```bash
python upper_bound.py
```

### `solution_formatter.py`
Affichage et sauvegarde d'une solution (planning chronologique, récapitulatif par coureur,
vérifications). Importé par `solver.py` et `enumerate_optimal_solutions.py`.

### `enumerate_optimal_solutions.py`
Énumère toutes les solutions optimales en deux étapes :
1. Collecte jusqu'à `MAX_CONFIGS` configurations de binômes distinctes (Ctrl+C pour passer à l'étape 2 avant la limite).
2. Pour chaque configuration, énumère jusqu'à `MAX_PER_CONFIG` placements (Ctrl+C pour terminer).

Chaque solution est sauvegardée dans `enumerate_solutions/` (`.txt` + `.csv`).
À la fin de l'étape 2, `analyze_solutions.py` est lancé automatiquement.

```bash
python enumerate_optimal_solutions.py
```

### `analyze_solutions.py`
Analyse les solutions CSV produits par `enumerate_optimal_solutions.py`.
Génère pour chaque coureur un histogramme PNG et une page HTML, ainsi qu'une page de
synthèse et des pages de diversité / solo-binôme. Sorties dans `explore_solutions/`.
Peut aussi être lancé manuellement.

```bash
python analyze_solutions.py
# Puis ouvrir : explore_solutions/index.html
```

## Sorties

| Dossier / fichier            | Contenu                                          |
|------------------------------|--------------------------------------------------|
| `plannings/`                 | Plannings `.txt` et `.csv` produits par `solver.py` |
| `enumerate_solutions/`       | Solutions énumérées (`.txt` + `.csv`)            |
| `explore_solutions/`         | Pages HTML et histogrammes d'analyse             |
| `planning_exemple.txt`       | Exemple de planning formaté                      |

## Licence

MIT — voir [LICENSE](LICENSE).
