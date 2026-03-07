"""
Calcule un majorant de la fonction objectif (nombre de relais en binômes).

Pour chaque taille de relais, on résout un problème de matching biparti :
- noeuds = coureurs ayant des relais de cette taille
- arête (r1, r2) si r1 et r2 sont compatibles, avec capacité = min(count_r1, count_r2)
- on cherche le matching maximum (chaque relais d'un coureur peut être en binôme avec
  au plus un autre coureur)

Le majorant global = somme des matchings optimaux sur toutes les tailles.
"""

from collections import defaultdict
from data import RUNNER_RELAYS, COMPATIBLE


def count_by_size(relays: list[int]) -> dict[int, int]:
    counts = defaultdict(int)
    for s in relays:
        counts[s] += 1
    return dict(counts)


def max_matching_for_size(size: int) -> int:
    """
    Matching maximum pour les relais de `size` segments.
    Modèle : graphe de flot
      source -> chaque coureur r : capacité = nb relais de taille `size` de r
      r1 -> r2 (si compatibles) : capacité = min(count[r1], count[r2])
      chaque coureur r -> puits : capacité = count[r]

    On utilise l'algorithme de Ford-Fulkerson (BFS = Edmonds-Karp).
    """
    # Coureurs ayant au moins 1 relais de cette taille
    runners = [r for r, relays in RUNNER_RELAYS.items()
               if size in count_by_size(relays)]
    if len(runners) < 2:
        return 0

    counts = {r: count_by_size(RUNNER_RELAYS[r]).get(size, 0) for r in runners}

    # Noeuds : 0=source, 1..n=coureurs, n+1..2n=coureurs côté puits, 2n+1=puits
    # En fait on modélise : source -> r (cap=count[r]), paire (r1,r2) compatible ->
    # on ajoute un noeud par paire pour éviter de dépasser les capacités.
    # Plus simple : graphe biparti orienté avec capacités sur les noeuds coureurs.
    #
    # Modèle avec node-splitting :
    #   source (S) -> r_in (cap = count[r])
    #   r_in -> r_out (cap = count[r])   [capacité du noeud]
    #   r_out -> r2_in pour chaque paire compatible (cap = inf)
    #   r_out -> puits (cap = 0, les binômes comptent sur les deux coureurs)
    #
    # En réalité : un binôme consomme 1 relais de r1 ET 1 relais de r2.
    # On compte le nombre de PAIRES formées, donc chaque paire consomme
    # 1 unité chez r1 et 1 unité chez r2.
    #
    # Modèle de flot correct :
    #   S -> r (cap = count[r]) pour chaque r
    #   r1 -> r2 (arête non orientée = 2 arêtes orientées, cap = +inf)
    #     mais on veut un matching, donc on oriente :
    #   Pour chaque paire compatible (r1, r2) avec r1 < r2 :
    #     noeud_paire p
    #     r1 -> p (cap = inf), r2 -> p (cap = inf), p -> T (cap = min(count[r1], count[r2]))
    #   Mais ça ne respecte pas que chaque relais de r1 est utilisé au plus une fois.
    #
    # Le modèle le plus direct :
    #   S -> r_in  cap = count[r]
    #   r_in -> r_out  cap = count[r]  (node capacity)
    #   Pour chaque paire compatible (r1, r2) :
    #     r1_out -> r2_in  cap = inf  (flot représente des binômes)
    #   r_out -> T  cap = 0  (les unités sortent via les paires, pas directement)
    #
    # En fait : le flot de S vers T passe par S->r1_in->r1_out->r2_in->r2_out->T ?
    # Non : on veut que chaque unité de flot représente UN binôme (1 relais de r1 + 1 de r2).
    #
    # Modèle correct (flot de valeur = nb binômes) :
    #   S -> r_in  cap = count[r]        (offre de relais)
    #   r_in -> r_out  cap = count[r]    (passage noeud)
    #   r1_out -> r2_in  cap = inf       pour chaque paire compatible
    #   r2_in -> r2_out est déjà compté par la capacité du noeud r2
    #   r_out -> T  cap = count[r]       (chaque unité qui sort = 1 demi-binôme)
    # Mais ici le flot total = 2 * nb_binômes (chaque binôme envoie 1 unité de r1 vers T via r2,
    # et r2 envoie aussi 1 unité vers T).
    #
    # Le modèle le plus simple : graphe biparti, on fixe un ordre et on oriente les arêtes.
    # Pour chaque paire compatible (r1, r2) avec r1 < r2 :
    #   S -> r1  cap = count[r1]
    #   r1 -> r2  cap = min(count[r1], count[r2])
    #   r2 -> T  cap = count[r2]
    # Problème : r1 peut envoyer du flot à plusieurs r2, mais r2 reçoit de plusieurs r1.
    # La capacité sur r2->T = count[r2] limite bien le total. OK !
    # La capacité sur S->r1 = count[r1] limite le total de r1. OK !
    # => flot max = nb de binômes maximum.

    # Construction du graphe de flot
    # Noeuds : S=0, r_i=1..n, T=n+1
    n = len(runners)
    idx = {r: i + 1 for i, r in enumerate(runners)}
    S, T = 0, n + 1
    size_graph = n + 2

    # Matrice de capacité résiduelle
    cap = [[0] * size_graph for _ in range(size_graph)]

    for r in runners:
        cap[S][idx[r]] += counts[r]
        cap[idx[r]][T] += counts[r]

    compatible_pairs = set()
    for r1 in runners:
        for r2 in COMPATIBLE.get(r1, set()):
            if r2 in idx and r1 < r2:
                compatible_pairs.add((r1, r2))

    for r1, r2 in compatible_pairs:
        c = min(counts[r1], counts[r2])
        cap[idx[r1]][idx[r2]] += c
        cap[idx[r2]][idx[r1]] += c

    # Edmonds-Karp (BFS)
    from collections import deque

    def bfs(source, sink, parent):
        visited = set([source])
        queue = deque([source])
        while queue:
            u = queue.popleft()
            for v in range(size_graph):
                if v not in visited and cap[u][v] > 0:
                    visited.add(v)
                    parent[v] = u
                    if v == sink:
                        return True
                    queue.append(v)
        return False

    max_flow = 0
    while True:
        parent = [-1] * size_graph
        if not bfs(S, T, parent):
            break
        # Trouver le flot du chemin
        path_flow = float('inf')
        v = T
        while v != S:
            u = parent[v]
            path_flow = min(path_flow, cap[u][v])
            v = u
        # Mettre à jour les capacités résiduelles
        v = T
        while v != S:
            u = parent[v]
            cap[u][v] -= path_flow
            cap[v][u] += path_flow
            v = u
        max_flow += path_flow

    # Le flot compte chaque binôme deux fois (S->r1->r2->T et S->r2->r1->T sont tous les deux possibles)
    # Non : dans ce modèle orienté, chaque paire (r1,r2) avec r1<r2 a des arêtes dans les deux sens,
    # mais le flot de S->r1->r2->T et S->r2->r1->T sont indépendants.
    # En réalité chaque unité de flot passant par r1->r2 représente UN binôme,
    # et consomme 1 unité de capacité de r1 (via S->r1) et 1 unité de r2 (via r2->T).
    # => max_flow = nb de binômes. Correct.

    return max_flow


def compute_upper_bound():
    from data import N_SEGMENTS

    all_sizes = set()
    for relays in RUNNER_RELAYS.values():
        all_sizes.update(relays)
    all_sizes = sorted(all_sizes)

    # Majorant par matching (sans contrainte de couverture)
    matching = {}
    for size in all_sizes:
        matching[size] = max_matching_for_size(size)

    total_matching = sum(matching.values())

    # Surplus de segments disponibles pour les binômes
    total_segs_engaged = sum(sum(r) for r in RUNNER_RELAYS.values())
    surplus = total_segs_engaged - N_SEGMENTS

    # Majorant par surplus : sum(b_s * s) <= surplus, b_s <= matching[s]
    # On maximise sum(b_s) sous cette contrainte (knapsack fractionnaire suffisant
    # pour un majorant : trier par "efficacité" = 1/s, prendre les plus petits d'abord)
    sizes_by_efficiency = sorted(all_sizes, key=lambda s: s)  # plus petit s = plus efficace
    remaining = surplus
    bound_surplus = 0
    for size in sizes_by_efficiency:
        can_take = min(matching[size], remaining // size)
        bound_surplus += can_take
        remaining -= can_take * size
        if remaining <= 0:
            break
    # Ajout fractionnaire pour la borne (relaxation continue)
    if remaining > 0:
        for size in sizes_by_efficiency:
            already = min(matching[size], surplus // size)
            leftover = matching[size] - already
            if leftover > 0 and remaining > 0:
                frac = min(leftover, remaining / size)
                bound_surplus += frac
                remaining -= frac * size

    print("Majorant du nombre de binômes par taille de relais :")
    print(f"  {'Taille':>6}  {'km':>4}  {'Matching max':>12}")
    print(f"  {'-'*6}  {'-'*4}  {'-'*12}")
    for size in all_sizes:
        km = size * 5
        print(f"  {size:>6}  {km:>4}  {matching[size]:>12}")

    print(f"\n  Total segments engagés : {total_segs_engaged}  ({total_segs_engaged*5} km)")
    print(f"  Segments à couvrir     : {N_SEGMENTS}  ({N_SEGMENTS*5} km)")
    print(f"  Surplus                : {surplus} segments")
    print(f"\n  Majorant (matching seul)         : {total_matching} binômes")
    print(f"  Majorant (contrainte couverture) : {int(bound_surplus)} binômes")
    print(f"\n  => Majorant retenu : {min(total_matching, int(bound_surplus))} binômes")
    return min(total_matching, int(bound_surplus))


if __name__ == "__main__":
    compute_upper_bound()
