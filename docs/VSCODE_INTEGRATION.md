# Intégration VSCode

## Prérequis

Installer l'extension **Python** (`ms-python.python`) dans VSCode.

## Configurer l'interpréteur Python

Le `launch.json` utilise `${command:python.interpreterPath}` pour sélectionner automatiquement l'interpréteur actif. Il faut pointer cet interpréteur vers le venv du projet :

1. Ouvrir la palette de commandes : `Ctrl+Shift+P`
2. Taper `Python: Select Interpreter`
3. Choisir l'interpréteur dans `./venv/bin/python` (affiché comme `Python 3.13.x ('venv': venv)`)

Si le venv n'apparaît pas dans la liste, utiliser **Enter interpreter path...** et saisir le chemin manuellement :

```
/home/<user>/projets/relais-planner/venv/bin/python
```

Une fois sélectionné, toutes les configurations de lancement (`Résolution`, `Optimisation D+/D-`, etc.) utiliseront automatiquement cet interpréteur.

## Lancer le solveur

Les configurations disponibles dans `.vscode/launch.json` sont accessibles via `Run > Start Debugging` (`F5`) ou le panneau **Run and Debug** (`Ctrl+Shift+D`) :

| Configuration | Équivalent CLI |
|---|---|
| Données d'entrée | `python example.py data` |
| Résolution | `python example.py` |
| Optimisation D+/D- | `python example.py dplus --ref replanif/reference.json --min-score <N>` |
| Replanification | `python example.py replanif --ref replanif/reference.json --min-score <N>` |
| Faisabilité | `python example.py diag` |
| Reformater derniere solution | `python utils/reformat.py --all` |

## Ajuster le score minimum pour D+ et Replanification

Les configurations **Optimisation D+/D-** et **Replanification** incluent un argument `--min-score` qui contraint le score de duos minimal acceptable. Ce score doit être ajusté manuellement dans `.vscode/launch.json` en fonction du score obtenu lors de la résolution initiale.

**Pourquoi c'est nécessaire :** ces deux modes optimisent un critère secondaire (D+/D- ou distance à une référence) tout en maintenant la qualité des duos au-dessus d'un seuil. Un score trop élevé rend le problème infaisable ; un score trop bas donne une solution dégradée.

**Procédure :**

1. Lancer d'abord une **Résolution** et noter le score affiché en fin de solve (ex. `score duos: 52`).
2. Copier la solution obtenue dans `replanif/reference.json`.
3. Dans `.vscode/launch.json`, mettre à jour le `--min-score` des configurations D+ et Replanification avec une valeur légèrement inférieure au score obtenu (typiquement score − 2 à − 5 selon la tolérance souhaitée).
4. Lancer l'optimisation D+ ou Replanification.

Exemple : score de résolution = 52 → `--min-score 48` pour autoriser une légère dégradation des duos en échange d'un meilleur D+.
