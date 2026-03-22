# CP-SAT Solver Callbacks (ortools Python)

## 1. `CpSolverSolutionCallback` — callback solution

Classe à sous-classer, passée à `solver.solve(model, solution_callback=cb)`.

**Méthode à implémenter :**
- `on_solution_callback()` — appelé à chaque nouvelle solution trouvée

**Méthodes disponibles dans le callback :**
- `value(expr)` / `float_value(expr)` / `boolean_value(lit)` — valeurs courantes des variables
- `objective_value()` — valeur de l'objectif courant
- `best_objective_bound()` — meilleure borne connue
- `num_conflicts()`, `num_branches()` — stats de recherche
- `stop_search()` — arrête la recherche de manière asynchrone
- `response_proto()` — proto complet du solver

**Exemple :**
```python
from ortools.sat.python import cp_model

class MyCallback(cp_model.CpSolverSolutionCallback):
    def __init__(self):
        cp_model.CpSolverSolutionCallback.__init__(self)
        self.count = 0

    def on_solution_callback(self):
        self.count += 1
        print(f"Solution {self.count}, objectif={self.objective_value()}")
        if self.count >= 10:
            self.stop_search()

solver = cp_model.CpSolver()
status = solver.solve(model, solution_callback=MyCallback())
```

---

## 2. `solver.log_callback` — callback de log

```python
solver.log_callback = lambda msg: print(msg)
```

Callable `str -> None`, appelé pour chaque ligne de log du solver.
Utile pour rediriger ou filtrer les logs (ex. dans un notebook Jupyter).

---

## 3. `solver.best_bound_callback` — callback de borne

```python
solver.best_bound_callback = lambda bound: print(f"Nouvelle borne: {bound}")
```

Callable `float -> None`, appelé à chaque amélioration de la meilleure borne.
Utile pour suivre la convergence de l'optimisation.

---

## Notes

- Pas de hook pre-solve / post-solve — uniquement pendant la recherche.
- `log_callback` et `best_bound_callback` sont appelés depuis les threads workers du solver : attention au thread-safety si état partagé.
- `stop_search()` est asynchrone : la recherche peut continuer brièvement avant de s'arrêter.
- Pour activer les logs internes du solver : `solver.parameters.log_search_progress = True`

---

Sources :
- [CpSolverSolutionCallback API](https://or-tools.github.io/docs/python/classortools_1_1sat_1_1python_1_1cp__model_1_1CpSolverSolutionCallback.html)
- [CpSolver API](https://or-tools.github.io/docs/python/classortools_1_1sat_1_1python_1_1cp__model_1_1CpSolver.html)
