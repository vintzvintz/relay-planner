"""
Formatage des solutions CP-SAT.

API publique :
  RelaySolution(relais_list, constraints, score=None)
    .to_text() -> str
    .to_csv(filename)
    .to_json(filename)
    .to_html(filename)
    .save(quiet=False)
    .stats() -> (n_binomes, n_solos, km_solos, n_flex, n_fixes, km_flex)
"""

import csv
import io
import json
import os
import sys
from datetime import datetime

import verifications as verif

DAY_NAMES = ["Mercredi", "Jeudi", "Vendredi"]
DAY_SHORT = ["Mer", "Jeu", "Ven"]

OUTDIR = "plannings"

# quantité d'infos affichées sur la console
QUIET  = 0
STATS  = 1
DETAIL = 2


class RelaySolution:
    """Encapsule une solution CP-SAT avec vérification et formatage."""

    def __init__(self, relais_list, constraints, score=None):
        self.relais_list = relais_list
        self.constraints = constraints
        self.score = score
        buf = io.StringIO()
        self.valid = verif.check(relais_list, constraints, out=buf)
        if not self.valid:
            print(buf.getvalue(), file=sys.stderr)

    # ------------------------------------------------------------------
    # Helpers privés
    # ------------------------------------------------------------------

    @staticmethod
    def _chrono_tags(rel):
        return [t for t, v in [("fixe", rel["fixe"]), ("solo", rel["solo"]), ("nuit", rel["night"])] if v]

    @staticmethod
    def _recap_tags(rel):
        return [t for t, v in [("fixe", rel["fixe"]), ("nuit", rel["night"]), ("flex", rel["flex"])] if v]

    @staticmethod
    def _dedup_key(rel):
        return (
            min(rel["runner"], rel["partner"] or "zzz"),
            max(rel["runner"], rel["partner"] or "zzz"),
            rel["start"],
        )

    def _fmt(self, seg):
        c = self.constraints
        h = c.segment_start_hour(seg)
        day, hh, mm = int(h // 24), int(h) % 24, int((h % 1) * 60)
        return DAY_NAMES[min(day, 2)], hh, mm

    def _fmt_short(self, seg):
        c = self.constraints
        h = c.segment_start_hour(seg)
        day, hh, mm = int(h // 24), int(h) % 24, int((h % 1) * 60)
        return DAY_SHORT[min(day, 2)], hh, mm

    def _chrono_coureurs_width(self):
        seen = set()
        w = 0
        for rel in self.relais_list:
            dedup = self._dedup_key(rel)
            if dedup in seen and rel["partner"]:
                continue
            seen.add(dedup)
            label = f"{rel['runner']} + {rel['partner']}" if rel["partner"] else rel["runner"]
            w = max(w, len(label))
        return w

    def _recap_partenaire_width(self):
        w = 0
        for rel in self.relais_list:
            label = f"avec {rel['partner']}" if rel["partner"] else "seul"
            w = max(w, len(label))
        return w

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def stats(self):
        """Retourne (n_binomes, n_solos, km_solos, n_flex, n_fixes, km_flex)."""
        c = self.constraints
        rl = self.relais_list
        n_binomes = sum(1 for x in rl if x["partner"]) // 2
        solos = [x for x in rl if x["solo"]]
        n_flex = sum(1 for x in rl if x["flex"])
        n_fixes = sum(1 for x in rl if x["fixe"])
        km_flex = sum(
            (max(c.runners_data[x["runner"]].relais[x["k"]].size) - x["size"]) * c.segment_km
            for x in rl if x["flex"]
        )
        return n_binomes, len(solos), sum(x["km"] for x in solos), n_flex, n_fixes, km_flex

    def to_text(self) -> str:
        """Retourne le planning complet en texte (planning chrono + récap)."""
        lines = self._planning_chrono_lines() + self._recap_coureurs_lines()
        return "\n".join(lines) + "\n"

    def _export_row(self, rel):
        """Retourne un dict commun aux exports CSV et JSON."""
        c = self.constraints
        day_s, hh, mm = self._fmt_short(rel["start"])
        _, hh_e, mm_e = self._fmt_short(rel["end"])
        return {
            "coureur": rel["runner"],
            "partenaire": rel["partner"],
            "debut_txt": f"{day_s} {hh:02d}h{mm:02d}",
            "fin_txt": f"{day_s} {hh_e:02d}h{mm_e:02d}",
            "debut_seg": rel["start"],
            "fin_seg": rel["end"],
            "debut_heure": round(c.segment_start_hour(rel["start"]), 4),
            "fin_heure": round(c.segment_start_hour(rel["end"]), 4),
            "debut_km": float(rel["start"] * c.segment_km),
            "fin_km": float(rel["end"] * c.segment_km),
            "distance_km": rel["km"],
            "solo": rel["solo"],
            "nuit": rel["night"],
            "flex": rel["flex"],
            "fixe": rel["fixe"],
            "rest_h": rel["rest_h"],
        }

    def to_csv(self, filename):
        """Sauvegarde la solution en CSV."""
        rows = [self._export_row(rel) for rel in self.relais_list]
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    def to_json(self, filename):
        """Sauvegarde la solution en JSON."""
        data = [self._export_row(rel) for rel in self.relais_list]
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def to_html(self, filename):
        """Sauvegarde le planning en HTML (Gantt + planning détaillé)."""
        with open(filename, "w", encoding="utf-8") as f:
            f.write(self._build_html())

    def save(self, verbose=STATS):
        """Affiche la solution et la sauvegarde dans des fichiers horodatés."""
        outdir = OUTDIR
        os.makedirs(outdir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        text = self.to_text()

        txt_fname = os.path.join(outdir, f"planning_{ts}.txt")
        with open(txt_fname, "w", encoding="utf-8") as f:
            f.write(text)

        csv_fname = os.path.join(outdir, f"planning_{ts}.csv")
        self.to_csv(csv_fname)

        json_fname = os.path.join(outdir, f"planning_{ts}.json")
        self.to_json(json_fname)

        html_fname = os.path.join(outdir, f"planning_{ts}.html")
        self.to_html(html_fname)

        if verbose==DETAIL:
            print(text)
            print(f"Solution sauvegardée     : {txt_fname}/csv/html")
        elif verbose==STATS:
            n_binomes, n_solo, km_solo, n_flex, n_fixes, km_flex = self.stats()
            km_flex_str = f" ({km_flex:.1f} km)" if km_flex else ""
            print( f"score:{self.score:.1f} binomes:{n_binomes} solos:{n_solo} ({km_solo:.1f} km) flex:{n_flex}{km_flex_str} fixes:{n_fixes}  --> planning_{ts}")
        else: # verbose==QUIET
            pass


    # ------------------------------------------------------------------
    # Rendu texte (privé)
    # ------------------------------------------------------------------

    def _planning_chrono_lines(self):
        c = self.constraints
        W = 74
        lines = []
        n_binomes, n_solos, km_solos, n_flex, n_fixes, km_flex = self.stats()
        score_str = f"  Score:{self.score:.1f}" if self.score is not None else "  Score:<valeur>"
        flex_str = f"   Flex : {n_flex}" + (f" ({km_flex:.1f} km)" if km_flex else "")
        fixes_str = f"   Fixes : {n_fixes}" if n_fixes else ""
        c._ensure_lp()
        lp_str = f" (LP ≤{c.lp_upper_bound})" if c.lp_upper_bound is not None else ""
        lines.append("=" * W)
        lines.append(f"  PLANNING  {c.total_km:.1f} km — {c.nb_segments} segments de {c.segment_km:.1f} km - Vitesse {c.speed_kmh:.1f} km/h")
        lines.append(
            f"  Binômes : {n_binomes}{lp_str}  Solos : {n_solos} ({km_solos:.1f} km){flex_str}{fixes_str}{score_str}"
        )
        lines.append("=" * W)

        cw = self._chrono_coureurs_width()
        current_day = -1
        seen = set()
        for rel in self.relais_list:
            day_s, hh, mm = self._fmt_short(rel["start"])
            day = int(c.segment_start_hour(rel["start"]) // 24)

            if day != current_day:
                current_day = day
                lines.append(f"\n▶ {DAY_NAMES[min(day, 2)].upper()}")

            dedup = self._dedup_key(rel)
            if dedup in seen and rel["partner"]:
                continue
            seen.add(dedup)

            _, hh_end, mm_end = self._fmt_short(rel["end"])
            debut = f"{day_s} {hh:02d}h{mm:02d}"
            fin = f"{hh_end:02d}h{mm_end:02d}"
            seg_dep = f"{rel['start']:>3}"
            km_dep = f"{rel['start'] * c.segment_km:>6.1f} km"
            coureurs = f"{rel['runner']} + {rel['partner']}" if rel["partner"] else rel["runner"]
            tags = self._chrono_tags(rel)
            flags = f"  [{' '.join(tags)}]" if tags else ""
            lines.append(f"  {debut} → {fin}   {seg_dep}   {km_dep}   {rel['km']:>4.1f} km   {coureurs:<{cw}}{flags}")

        return lines

    def _recap_coureurs_lines(self):
        c = self.constraints
        W = 74
        lines = []
        lines.append(f"\n{'─' * W}")
        lines.append("  PAR COUREUR")
        lines.append(f"{'─' * W}")
        pw = self._recap_partenaire_width()
        for r in sorted(c.runners):
            r_rels = sorted(
                [x for x in self.relais_list if x["runner"] == r], key=lambda x: x["start"]
            )
            total = sum(x["km"] for x in r_rels)
            n_solo = sum(1 for x in r_rels if x["solo"])
            n_nuit = sum(1 for x in r_rels if x["night"])
            flags = []
            if n_solo:
                flags.append(f"{n_solo} seul")
            if n_nuit:
                flags.append(f"{n_nuit} nuit")
            lines.append(
                f"\n{r:<12}  {total:>5.1f} km  {len(r_rels)} relais"
                + (f"  ({', '.join(flags)})" if flags else "")
            )
            for rel in r_rels:
                day_s, hh, mm = self._fmt_short(rel["start"])
                _, hh_e, mm_e = self._fmt_short(rel["end"])
                p = f"avec {rel['partner']}" if rel["partner"] else "seul"
                rest_h = rel["rest_h"]
                if rest_h is not None:
                    rh, rm = int(rest_h), int((rest_h % 1) * 60)
                    repos = f"repos {rh:2d}h{rm:02d}"
                else:
                    repos = ""
                tags = self._recap_tags(rel)
                flags = f"  [{' '.join(tags)}]" if tags else ""
                lines.append(
                    f"  {day_s} {hh:02d}h{mm:02d} → {hh_e:02d}h{mm_e:02d}"
                    f"  {rel['km']:>4.1f} km  {p:<{pw}}  {repos:<11}{flags}"
                )

        return lines

    # ------------------------------------------------------------------
    # Rendu HTML (privé)
    # ------------------------------------------------------------------

    def _build_html_detail(self):
        c = self.constraints
        rl = self.relais_list

        def row_class(rel):
            if rel["fixe"]:
                return ' class="row-fixe"'
            if rel["solo"]:
                return ' class="row-solo"'
            if rel["partner"]:
                return ' class="row-binome"'
            return ""

        # --- Planning chronologique ---
        chrono_rows = []
        seen = set()
        for rel in rl:
            day_s, hh, mm = self._fmt_short(rel["start"])
            dedup = self._dedup_key(rel)
            if dedup in seen and rel["partner"]:
                continue
            seen.add(dedup)

            _, hh_end, mm_end = self._fmt_short(rel["end"])
            coureurs = f"{rel['runner']} + {rel['partner']}" if rel["partner"] else rel["runner"]
            tags = self._chrono_tags(rel)
            flags = ", ".join(tags)
            chrono_rows.append(
                f'<tr{row_class(rel)}>'
                f'<td class="td-time td-nowrap">{day_s} {hh:02d}h{mm:02d} → {hh_end:02d}h{mm_end:02d}</td>'
                f'<td class="td-time td-right">{rel["start"]}</td>'
                f'<td class="td-time td-right">{rel["start"] * c.segment_km:.1f} km</td>'
                f'<td class="td-time td-right">{rel["km"]:.1f} km</td>'
                f'<td class="td-time td-bold">{coureurs}</td>'
                f'<td class="td-time td-meta">{flags}</td>'
                f'</tr>'
            )

        chrono_html = (
            '<h3 class="section-title">Planning chronologique</h3>'
            '<table class="detail-table">'
            '<thead><tr class="thead-row">'
            '<th class="th-detail">Horaire</th>'
            '<th class="th-detail th-right">Seg.</th>'
            '<th class="th-detail th-right">Km</th>'
            '<th class="th-detail th-right">Dist.</th>'
            '<th class="th-detail">Coureur(s)</th>'
            '<th class="th-detail">Tags</th>'
            '</tr></thead>'
            '<tbody>' + "\n".join(chrono_rows) + '</tbody>'
            '</table>'
        )

        # --- Récap par coureur ---
        recap_sections = []
        for r in sorted(c.runners):
            r_rels = sorted(
                [x for x in rl if x["runner"] == r], key=lambda x: x["start"]
            )
            total = sum(x["km"] for x in r_rels)
            n_solo = sum(1 for x in r_rels if x["solo"])
            n_nuit = sum(1 for x in r_rels if x["night"])
            flags = []
            if n_solo:
                flags.append(f"{n_solo} seul")
            if n_nuit:
                flags.append(f"{n_nuit} nuit")
            flags_str = f" &nbsp;({', '.join(flags)})" if flags else ""

            detail_rows = []
            for rel in r_rels:
                day_s, hh, mm = self._fmt_short(rel["start"])
                _, hh_e, mm_e = self._fmt_short(rel["end"])
                p = f"avec {rel['partner']}" if rel["partner"] else "seul"
                rest_h = rel["rest_h"]
                if rest_h is not None:
                    rh, rm = int(rest_h), int((rest_h % 1) * 60)
                    repos = f"repos {rh}h{rm:02d}"
                else:
                    repos = ""
                tags = self._recap_tags(rel)
                tags_str = ", ".join(tags)
                detail_rows.append(
                    f'<tr{row_class(rel)}>'
                    f'<td class="td-recap td-nowrap">{day_s} {hh:02d}h{mm:02d} → {hh_e:02d}h{mm_e:02d}</td>'
                    f'<td class="td-recap td-right">{rel["km"]:.1f} km</td>'
                    f'<td class="td-recap">{p}</td>'
                    f'<td class="td-recap td-meta">{repos}</td>'
                    f'<td class="td-recap td-meta">{tags_str}</td>'
                    f'</tr>'
                )

            recap_sections.append(
                f'<h4 class="runner-title">{r}'
                f'<span class="runner-subtitle"> — {total:.1f} km, {len(r_rels)} relais{flags_str}</span></h4>'
                '<table class="detail-table">'
                '<tbody>' + "\n".join(detail_rows) + '</tbody>'
                '</table>'
            )

        recap_html = (
            '<h3 class="section-title">Par coureur</h3>'
            + "\n".join(recap_sections)
        )

        return chrono_html + "\n" + recap_html

    def _build_gantt(self):
        """Retourne (header_row, rows_html) pour le tableau Gantt."""
        c = self.constraints

        by_runner = {r: {} for r in c.runners}
        for rel in self.relais_list:
            by_runner[rel["runner"]][rel["start"]] = rel

        def unavail_segs(runner):
            specs = c.runners_data[runner].relais
            # Si au moins un relais n'a pas de window, le coureur est disponible partout
            if any(spec.window is None for spec in specs):
                return set()
            windows = [w for spec in specs for w in spec.window]
            avail = set()
            for s, e in windows:
                avail.update(range(s, e + 1))
            return set(range(c.nb_segments)) - avail

        mark_segs = set()
        for day in range(4):
            for hh_mark in (0, 6, 12, 18):
                target_h = day * 24 + hh_mark
                best = min(range(c.nb_segments + 1), key=lambda s: abs(c.segment_start_hour(s) - target_h))
                if 0 < best <= c.nb_segments:
                    mark_segs.add(best)

        def split_spans(spans):
            result = []
            for s, e, typ, label in spans:
                cuts = sorted(m for m in mark_segs if s < m < e)
                boundaries = [s] + cuts + [e]
                for i in range(len(boundaries) - 1):
                    result.append((boundaries[i], boundaries[i + 1], typ, label if i == 0 else ""))
            return result

        rows_html = []
        for r in sorted(c.runners):
            unavail = unavail_segs(r)
            relais_by_start = by_runner[r]
            sorted_relais = sorted(relais_by_start.values(), key=lambda x: x["start"])
            rd = c.runners_data[r]

            spans = []
            seg = 0
            last_repos_end = None  # seg index jusqu'où le repos minimal court
            while seg < c.nb_segments:
                if seg in relais_by_start:
                    rel = relais_by_start[seg]
                    if rel["fixe"]:
                        relay_typ = "relay_fixe"
                    elif rel["solo"]:
                        relay_typ = "relay_solo"
                    else:
                        relay_typ = "relay_binome" if rel["partner"] else "relay_solo"
                    spans.append((seg, rel["end"], relay_typ, ""))
                    repos_segs = c._resolved_repos_nuit(rd) if rel["night"] else c._resolved_repos_jour(rd)
                    last_repos_end = min(rel["end"] + repos_segs, c.nb_segments)
                    seg = rel["end"]
                elif seg in unavail:
                    end = seg + 1
                    while end < c.nb_segments and end in unavail and end not in relais_by_start:
                        end += 1
                    spans.append((seg, end, "unavail", ""))
                    seg = end
                else:
                    next_event = c.nb_segments
                    for rs in sorted_relais:
                        if rs["start"] > seg:
                            next_event = min(next_event, rs["start"])
                            break
                    for us in sorted(unavail):
                        if us > seg:
                            next_event = min(next_event, us)
                            break
                    end = next_event
                    # Découpe la zone libre en repos minimal (gris) + libre (blanc)
                    if last_repos_end is not None and seg < last_repos_end:
                        repos_end = min(last_repos_end, end)
                        spans.append((seg, repos_end, "rest", ""))
                        if repos_end < end:
                            spans.append((repos_end, end, "free", ""))
                    else:
                        spans.append((seg, end, "free", ""))
                    seg = end

            spans = split_spans(spans)

            tds = []
            for s, e, typ, label in spans:
                colspan = e - s
                if colspan == 0:
                    continue
                mark_class = " seg-mark" if s in mark_segs else ""
                if typ == "free":
                    css_class = f"seg-free{mark_class}"
                elif typ == "rest":
                    css_class = f"seg-rest{mark_class}"
                elif typ == "relay_binome":
                    css_class = f"seg-binome{mark_class}"
                elif typ == "relay_solo":
                    css_class = f"seg-solo{mark_class}"
                elif typ == "relay_fixe":
                    css_class = f"seg-fixe{mark_class}"
                elif typ == "unavail":
                    css_class = f"seg-unavail{mark_class}"
                else:
                    css_class = f"seg-free{mark_class}"
                tds.append(f'<td colspan="{colspan}" class="{css_class}">{label}</td>')

            rows_html.append(f'<tr><th class="th-runner">{r}</th>\n{chr(10).join(tds)}\n</tr>')

        header_tds = ['<th class="th-seg-label"></th>']
        for seg in range(c.nb_segments):
            h = c.segment_start_hour(seg)
            is_mark = seg in mark_segs
            if is_mark:
                h_mod = h % 24
                closest_hh = min((0, 6, 12, 18), key=lambda hm: min(abs(h_mod - hm), 24 - abs(h_mod - hm)))
                label = f"{closest_hh:02d}h"
            else:
                label = ""
            night_class = " seg-header-night" if seg in c.night_segments else ""
            mark_class = " seg-mark-header" if is_mark else ""
            header_tds.append(f'<th class="th-seg{night_class}{mark_class}">{label}</th>')
        header_row = f'<tr>\n{chr(10).join(header_tds)}\n</tr>'

        return header_row, rows_html

    def _build_html(self):
        c = self.constraints

        header_row, rows_html = self._build_gantt()

        h_end = c.segment_start_hour(c.nb_segments)
        day_end = DAY_NAMES[min(int(h_end // 24), 2)]
        hh_end, mm_end = int(h_end) % 24, int((h_end % 1) * 60)
        n_binomes, n_solos, km_solos, n_flex, n_fixes, km_flex = self.stats()
        km_flex_str = f" ({km_flex:.1f} km)" if km_flex else ""
        c._ensure_lp()
        lp_str_html = f" (LP ≤{c.lp_upper_bound})" if c.lp_upper_bound is not None else ""

        text_section = self._build_html_detail()

        return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Planning {c.total_km} km</title>
<style>
  body {{ font-family: sans-serif; font-size: 12px; margin: 16px; }}
  table {{ border-collapse: collapse; table-layout: fixed; }}
  .gantt-table {{ width: 100%; }}
  th, td {{ padding: 2px; }}

  /* Gantt — header */
  .th-seg-label {{ padding: 2px 6px; white-space: nowrap; font-size: 12px; width: 120px; min-width: 120px; }}
  .th-seg {{ background: #90caf9; color: #000; font-size: 8px; padding: 1px; text-align: center; }}
  .th-seg.seg-header-night {{ background: #1565c0; color: #fff; }}
  .th-seg.seg-mark-header {{ border-left: 2px solid #fff; }}
  .th-runner {{ text-align: left; padding: 2px 6px; white-space: nowrap; font-size: 12px; width: 120px; min-width: 120px; }}

  /* Gantt — cellules segments */
  .seg-free    {{ color: #555; font-size: 10px; text-align: center; border: 1px solid #ccc; background: #ffffff; }}
  .seg-rest    {{ color: #555; font-size: 10px; text-align: center; border: 1px solid #ccc; background: #d0d0d0; }}
  .seg-binome  {{ background: #4caf50; color: #000; font-size: 10px; text-align: center; font-weight: bold; border: 1px solid #2e7d32; }}
  .seg-solo    {{ background: #f48fb1; color: #000; font-size: 10px; text-align: center; font-weight: bold; border: 1px solid #c2185b; }}
  .seg-fixe    {{ background: #2196f3; color: #fff; font-size: 10px; text-align: center; font-weight: bold; border: 1px solid #1565c0; }}
  .seg-unavail {{ background: #8b00ff; border: 1px solid #6a00cc; }}
  .seg-mark    {{ border-left: 2px solid #000; }}

  /* Tables de détail */
  .detail-table {{ border-collapse: collapse; font-size: 12px; table-layout: auto; }}
  .section-title {{ margin-top: 2em; }}
  .thead-row {{ background: #eee; font-weight: bold; }}
  .th-detail {{ padding: 4px 8px; text-align: left; }}
  .th-detail.th-right {{ text-align: right; }}
  .runner-title {{ margin: 1.2em 0 0.3em; }}
  .runner-subtitle {{ font-weight: normal; font-size: 12px; }}

  /* Lignes colorées */
  .row-solo   {{ background: #fff0f5; }}
  .row-binome {{ background: #f0fff4; }}
  .row-fixe   {{ background: #e3f2fd; }}

  /* Cellules de détail */
  .td-time   {{ padding: 3px 8px; }}
  .td-recap  {{ padding: 2px 8px; }}
  .td-nowrap {{ white-space: nowrap; }}
  .td-right  {{ text-align: right; }}
  .td-bold   {{ font-weight: bold; }}
  .td-meta   {{ color: #888; font-size: 11px; }}
</style>
</head>
<body>
<h2>Planning {c.total_km:.1f} km — {c.nb_segments} segments de {c.segment_km:.1f} km — Vitesse {c.speed_kmh:.1f} km/h</h2>
<p>Départ : {DAY_NAMES[0]} {int(c.start_hour):02d}h{int((c.start_hour % 1) * 60):02d} &nbsp;|&nbsp; Arrivée : {day_end} ~{hh_end:02d}h{mm_end:02d}</p>
<p>Binômes : <strong>{n_binomes}</strong>{lp_str_html} &nbsp;|&nbsp; Solos : <strong>{n_solos}</strong> ({km_solos:.1f} km) &nbsp;|&nbsp; Flex : <strong>{n_flex}</strong>{km_flex_str} &nbsp;|&nbsp; Fixes : <strong>{n_fixes}</strong> &nbsp;|&nbsp; Score : <strong>{f"{self.score:.1f}" if self.score is not None else "—"}</strong></p>
<p>
  <span style="background:#4caf50;padding:2px 8px;border:1px solid #2e7d32;">Relais binôme</span>&nbsp;
  <span style="background:#f48fb1;padding:2px 8px;border:1px solid #c2185b;">Relais solo</span>&nbsp;
  <span style="background:#2196f3;padding:2px 8px;border:1px solid #1565c0;color:#fff;">Relais fixe</span>&nbsp;
  <span style="background:#8b00ff;padding:2px 8px;border:1px solid #6a00cc;">&nbsp;&nbsp;&nbsp;</span> Indisponible
</p>
<div style="overflow-x:auto;">
<table class="gantt-table">
{header_row}
{"".join(rows_html)}
</table>
</div>
{text_section}
</body>
</html>"""
