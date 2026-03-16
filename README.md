# relais-planner

Planificateur de course en relais par contraintes (CP-SAT).

Problème : Lyon → Fessenheim, 440 km, 82 segments, vitesse ~9 km/h, départ mercredi 15h00.
14 coureurs doivent couvrir chaque segment (1 ou 2 coureurs par segment).
L'objectif est de maximiser le nombre de relais courus en binôme.

## Prérequis

Python 3.10+, puis :

```bash
python -m venv venv
source venv/bin/activate   # Windows : venv\Scripts\activate
pip install -r requirements.txt
```

## Scripts principaux

### `data.py`
Constantes du problème, données coureurs (`RUNNERS_DATA`, dataclass `Coureur`),
listes de binômes épinglés/obligatoires/limités (`BINOMES_PINNED`, `BINOMES_ONCE_MIN`,
`BINOMES_ONCE_MAX`). `build_constraints()` assemble un objet `RelayConstraints`.
Exécuter directement pour afficher un résumé complet.

```bash
python data.py
```

### `constraints.py`
Dataclass `RelayConstraints` : snapshot des données du problème passé au modèle.
Contient les propriétés dérivées (segments nuit, borne supérieure LP, etc.) et
`print_summary()`. Pas destiné à être exécuté directement.

### `compat.py`
`COMPAT_MATRIX` : scores de compatibilité (0, 1 ou 2) pour chaque paire de coureurs.
Généré automatiquement depuis `compat_coureurs.xlsx` par `refresh_compat.py`.

### `model.py`
Construction du modèle CP-SAT (`RelayModel`). Variables : `start/end/size` par relais,
`same_relay` (binômes), `relais_solo`, `relais_nuit`. Expose `build_model(constraints)`,
`build_model_fixed_config(active_keys, constraints)` et des méthodes publiques pour
l'énumération (`add_min_score`, `fix_binome_config`, `add_config_exclusion_cut`,
`add_schedule_exclusion_cut`). Pas destiné à être exécuté directement.

### `solver.py`
`RelaySolver` : itérateur streaming sur les solutions CP-SAT (thread séparé).
Objectif : maximiser la somme pondérée des `same_relay` (poids = score de compatibilité).
Écrit le planning dans `plannings/` (`.txt`, `.csv`, `.json` et `.html`).

```bash
python solver.py
```

### `solution.py`
`RelaySolution` : encapsule une solution avec vérification automatique et formatage.
API : `to_text()`, `to_csv()`, `to_json()`, `to_html()`, `save(verbose=)`, `stats()`.
Le HTML inclut une grille Gantt par coureur (vert = binôme, rose = solo, gris = repos minimal,
violet = indisponible) avec repères toutes les 6h. Coureurs triés alphabétiquement.

### `enumerate.py`
Énumère toutes les solutions optimales en trois phases :
1. Recherche du meilleur score réalisable (ignoré si `SCORE_MINIMAL` est fixé).
2. Collecte jusqu'à `MAX_CONFIGS` configurations de binômes distinctes.
3. Pour chaque configuration, énumère jusqu'à `MAX_PER_CONFIG` placements distincts.

Chaque solution est sauvegardée dans `enumerate_solutions/` (`.csv`, `.json` et `.html`,
nommés `run_<timestamp>_config_NNN_place_NN`).
À la fin, `analyze_solutions.py` est lancé automatiquement. Ctrl+C arrête proprement.

```bash
python enumerate.py
```

### `analyze_solutions.py`
Analyse les solutions JSON produites par `enumerate.py`.
Génère pour chaque coureur un histogramme PNG et une page HTML, ainsi qu'une page de
synthèse et des pages de diversité / solo-binôme. Sorties dans `explore_solutions/`.

```bash
python analyze_solutions.py
# Puis ouvrir : explore_solutions/index.html
```

### `utils/check_configs_unique.py`
Vérifie que toutes les configurations de binômes (phase 2) dans `enumerate_solutions/`
sont distinctes en comparant les empreintes des fichiers `place_00.json`.
Accepte un argument optionnel `run_ts` pour filtrer un run spécifique.

```bash
python utils/check_configs_unique.py
python utils/check_configs_unique.py 20260315_204953
```

### `utils/find_duplicate_solutions.py`
Détecte les solutions JSON identiques dans `enumerate_solutions/` à l'aide d'un hash SHA-256
canonique (insensible à l'ordre des lignes, paires de binômes normalisées).

```bash
python utils/find_duplicate_solutions.py
```

### `utils/reformat.py`
Recharge la solution JSON la plus récente depuis `plannings/` et régénère le HTML.
Accepte un chemin de fichier optionnel en argument.

```bash
python utils/reformat.py
python utils/reformat.py plannings/mon_planning.json
```

## Sorties

| Dossier / fichier       | Contenu                                                              |
|-------------------------|----------------------------------------------------------------------|
| `plannings/`            | Plannings `.txt`, `.csv`, `.json` et `.html` produits par `solver.py` |
| `enumerate_solutions/`  | Solutions énumérées (`.csv`, `.json` et `.html`)                     |
| `explore_solutions/`    | Pages HTML et histogrammes d'analyse                                 |

## Licence

MIT — voir [LICENSE](LICENSE).
