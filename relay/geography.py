"""
relay/geography.py

Ajustement des bornes de relais sur les points d'accès réels (routes, chemins).

Charge un CSV access_points (colonnes : jalon, km_cross, lat_cross, lon_cross,
road_type, road_name, delta_km) et, pour chaque solution, choisit par optimisation
gloutonne le meilleur access point à chaque borne de relais, minimisant l'écart
entre longueurs réelles et longueurs théoriques.

API publique :
  load_access_points(path)               → AccessPoints
  AccessPoints.enrich(relays, segment_km, profil=None)  → list[dict]  (modifie km)
"""

import csv


class AccessPoints:
    """Index des points d'accès chargé depuis un CSV."""

    def __init__(self, rows: list[dict]):
        index: dict[int, list[dict]] = {}
        for row in rows:
            index.setdefault(row["jalon"], []).append(row)
        self._jalon_index = index

    # ------------------------------------------------------------------
    # Optimisation
    # ------------------------------------------------------------------

    def _choose(
        self,
        jalons_used: set[int],
        segment_km: float,
    ) -> dict[int, dict | None]:
        """
        Choisit pour chaque jalon utilisé le meilleur access point.

        jalons_used : ensemble des indices de segments actifs constituant les
          bornes de relais de la solution (start et end de chaque relais,
          dédoublonnés). Correspond à la colonne 'jalon' du CSV.

        Retourne un dict jalon → access point (ou None si le jalon n'a pas
        d'access point dans le CSV).

        Stratégie gloutonne : minimise l'écart entre la longueur réelle
        (km_cross[j] - km_cross[j_prev]) et la longueur théorique
        (nb_segs * segment_km) pour chaque paire de jalons consécutifs.
        """
        sorted_jalons = sorted(jalons_used)
        chosen: dict[int, dict | None] = {}

        for i, j in enumerate(sorted_jalons):
            if j not in self._jalon_index:
                chosen[j] = None
                continue

            grp = self._jalon_index[j]
            if i == 0:
                chosen[j] = min(grp, key=lambda r: abs(r["delta_km"]))
            else:
                j_prev = sorted_jalons[i - 1]
                km_prev = chosen[j_prev]["km_cross"] if chosen[j_prev] is not None else j_prev * segment_km
                km_theo = (j - j_prev) * segment_km
                chosen[j] = min(grp, key=lambda r: (r["km_cross"] - km_prev - km_theo) ** 2)

        return chosen

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def enrich(
        self,
        relays: list[dict],
        segment_km: float,
        profil=None,
        time_seg_to_active=None,
    ) -> list[dict]:
        """
        Enrichit la liste de relais avec les access points réels et
        recalcule km depuis les positions réelles des access points.

        Champs ajoutés/mis à jour par relais :
          km                    : longueur réelle du relais (km_cross[end] - km_cross[start])
          start_acces           : dict {km_cross, lat, lon, acces, road_type, road_name}
                                  ou None si le jalon n'a pas d'access point réel
          end_acces             : idem pour la borne de fin
          d_plus, d_moins       (recalculés depuis profil si fourni)

        time_seg_to_active : callable optionnel pour convertir les indices time-space
          (stockés dans start/end) en indices de segments actifs ; nécessaire quand
          le planning contient des pauses (segments inactifs intercalés).
        """
        def to_active(seg):
            return time_seg_to_active(seg) if time_seg_to_active is not None else seg

        jalons_used = set()
        for r in relays:
            jalons_used.add(to_active(r["start"]))
            jalons_used.add(to_active(r["end"]))

        chosen = self._choose(jalons_used, segment_km)

        enriched = []
        for r in relays:
            relay = r.copy()
            s_idx = to_active(r["start"])
            e_idx = to_active(r["end"])
            ap_start = chosen[s_idx]
            ap_end = chosen[e_idx]

            relay["start_acces"] = ap_start
            relay["end_acces"] = ap_end

            km_start = ap_start["km_cross"] if ap_start is not None else s_idx * segment_km
            km_end = ap_end["km_cross"] if ap_end is not None else e_idx * segment_km
            relay["km"] = round(km_end - km_start, 4)

            if profil is not None:
                dp, dm = profil.denivele(km_start, km_end)
                relay["d_plus"] = round(dp, 2)
                relay["d_moins"] = round(dm, 2)

            enriched.append(relay)
        return enriched


# ------------------------------------------------------------------
# Chargement
# ------------------------------------------------------------------

def load_access_points(path: str) -> AccessPoints:
    """Charge un fichier CSV access_points et retourne un AccessPoints."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = [
            {
                "jalon": int(r["jalon"]),
                "km_cross": float(r["km_cross"]),
                "lat": float(r["lat_cross"]),
                "lon": float(r["lon_cross"]),
                "delta_km": float(r["delta_km"]),
                "acces": r["acces"] or None,
                "road_type": r["road_type"] or None,
                "road_name": r["road_name"] or None,
            }
            for r in csv.DictReader(f)
        ]
    return AccessPoints(rows)
