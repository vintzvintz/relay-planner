"""
Formatage des solutions CP-SAT.

API publique :
  RelaySolution(relais_list, constraints, score=None)
    .to_text() -> str
    .to_csv(filename)
    .to_json(filename)
    .to_html(filename)
    .save(quiet=False)
    .stats() -> (n_binomes, n_solos, km_solos, n_flex)
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
        return [t for t, v in [("solo", rel["solo"]), ("nuit", rel["night"])] if v]

    @staticmethod
    def _recap_tags(rel):
        return [t for t, v in [("nuit", rel["night"]), ("flex", rel["flex"])] if v]

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
        """Retourne (n_binomes, n_solos, km_solos, n_flex)."""
        rl = self.relais_list
        n_binomes = sum(1 for x in rl if x["partner"]) // 2
        solos = [x for x in rl if x["solo"]]
        n_flex = sum(1 for x in rl if x["flex"])
        return n_binomes, len(solos), sum(x["km"] for x in solos), n_flex

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
            n_binomes, n_solo, km_solo, n_flex = self.stats()
            print( f"score:{self.score:.1f} binomes:{n_binomes} solos:{n_solo} ({km_solo:.1f} km) flex:{n_flex}  --> planning_{ts}")
        else: # verbose==QUIET
            pass


    # ------------------------------------------------------------------
    # Rendu texte (privé)
    # ------------------------------------------------------------------

    def _planning_chrono_lines(self):
        c = self.constraints
        W = 74
        lines = []
        n_binomes, n_solos, km_solos, n_flex = self.stats()
        score_str = f"  Score:{self.score:.1f}" if self.score is not None else "  Score:<valeur>"
        flex_str = f"   Flex : {n_flex}"
        lines.append("=" * W)
        lines.append(f"  PLANNING  {c.total_km:.1f} km — {c.nb_segments} segments de {c.segment_km:.1f} km - Vitesse {c.speed_kmh:.1f} km/h")
        lines.append(
            f"  Binômes : {n_binomes}   Solos : {n_solos} ({km_solos:.1f} km){flex_str}{score_str}"
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
            dist = f"{rel['start'] * c.segment_km:.1f}–{rel['end'] * c.segment_km:.1f} km"
            coureurs = f"{rel['runner']} + {rel['partner']}" if rel["partner"] else rel["runner"]
            tags = self._chrono_tags(rel)
            flags = f"  [{' '.join(tags)}]" if tags else ""
            lines.append(f"  {debut} → {fin}   {dist:<16} {rel['km']:>4.1f} km   {coureurs:<{cw}}{flags}")

        return lines

    def _recap_coureurs_lines(self):
        c = self.constraints
        W = 74
        lines = []
        lines.append(f"\n{'─' * W}")
        lines.append("  PAR COUREUR")
        lines.append(f"{'─' * W}")
        pw = self._recap_partenaire_width()
        for r in c.runners:
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
            dist = f"{rel['start'] * c.segment_km:.1f}–{rel['end'] * c.segment_km:.1f} km"
            coureurs = f"{rel['runner']} + {rel['partner']}" if rel["partner"] else rel["runner"]
            tags = self._chrono_tags(rel)
            flags = ", ".join(tags)
            bg = "#fff0f5" if rel["solo"] else ("#f0fff4" if rel["partner"] else "#fff")
            chrono_rows.append(
                f'<tr style="background:{bg};">'
                f'<td style="padding:3px 8px;white-space:nowrap;">{day_s} {hh:02d}h{mm:02d} → {hh_end:02d}h{mm_end:02d}</td>'
                f'<td style="padding:3px 8px;white-space:nowrap;">{dist}</td>'
                f'<td style="padding:3px 8px;text-align:right;">{rel["km"]:.1f} km</td>'
                f'<td style="padding:3px 8px;font-weight:bold;">{coureurs}</td>'
                f'<td style="padding:3px 8px;color:#888;font-size:11px;">{flags}</td>'
                f'</tr>'
            )

        chrono_html = (
            '<h3 style="margin-top:2em;">Planning chronologique</h3>'
            '<table style="border-collapse:collapse;font-size:12px;">'
            '<thead><tr style="background:#eee;font-weight:bold;">'
            '<th style="padding:4px 8px;text-align:left;">Horaire</th>'
            '<th style="padding:4px 8px;text-align:left;">Distance</th>'
            '<th style="padding:4px 8px;text-align:right;">Dist.</th>'
            '<th style="padding:4px 8px;text-align:left;">Coureur(s)</th>'
            '<th style="padding:4px 8px;text-align:left;">Tags</th>'
            '</tr></thead>'
            '<tbody>' + "\n".join(chrono_rows) + '</tbody>'
            '</table>'
        )

        # --- Récap par coureur ---
        recap_sections = []
        for r in c.runners:
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
                bg = "#fff0f5" if rel["solo"] else ("#f0fff4" if rel["partner"] else "#fff")
                detail_rows.append(
                    f'<tr style="background:{bg};">'
                    f'<td style="padding:2px 8px;white-space:nowrap;">{day_s} {hh:02d}h{mm:02d} → {hh_e:02d}h{mm_e:02d}</td>'
                    f'<td style="padding:2px 8px;text-align:right;">{rel["km"]:.1f} km</td>'
                    f'<td style="padding:2px 8px;">{p}</td>'
                    f'<td style="padding:2px 8px;color:#888;font-size:11px;">{repos}</td>'
                    f'<td style="padding:2px 8px;color:#888;font-size:11px;">{tags_str}</td>'
                    f'</tr>'
                )

            recap_sections.append(
                f'<h4 style="margin:1.2em 0 0.3em;">{r}'
                f'<span style="font-weight:normal;font-size:12px;"> — {total:.1f} km, {len(r_rels)} relais{flags_str}</span></h4>'
                '<table style="border-collapse:collapse;font-size:12px;">'
                # '<thead><tr style="background:#eee;">'
                # '<th style="padding:3px 8px;text-align:left;">Horaire</th>'
                # '<th style="padding:3px 8px;text-align:right;">Dist.</th>'
                # '<th style="padding:3px 8px;text-align:left;">Partenaire</th>'
                # '<th style="padding:3px 8px;text-align:left;">Repos suivant</th>'
                # '<th style="padding:3px 8px;text-align:left;">Tags</th>'
                # '</tr></thead>'
                '<tbody>' + "\n".join(detail_rows) + '</tbody>'
                '</table>'
            )

        recap_html = (
            '<h3 style="margin-top:2em;">Par coureur</h3>'
            + "\n".join(recap_sections)
        )

        return chrono_html + "\n" + recap_html

    def _build_html(self):
        c = self.constraints
        rl = self.relais_list

        by_runner = {r: {} for r in c.runners}
        for rel in rl:
            by_runner[rel["runner"]][rel["start"]] = rel

        def unavail_segs(runner):
            if not c.runners_data[runner].dispo:
                return set()
            avail = set()
            for s, e in c.runners_data[runner].dispo:
                avail.update(range(s, e))
            return set(range(c.nb_segments)) - avail

        night_segments = c.night_segments

        SEG_WIDTH_PX = 10
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

            spans = []
            seg = 0
            while seg < c.nb_segments:
                if seg in relais_by_start:
                    rel = relais_by_start[seg]
                    relay_typ = "relay_solo" if rel["solo"] else ("relay_binome" if rel["partner"] else "relay_solo")
                    spans.append((seg, rel["end"], relay_typ, ""))
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
                    spans.append((seg, end, "free", ""))
                    seg = end

            spans = split_spans(spans)

            tds = []
            for s, e, typ, label in spans:
                colspan = e - s
                if colspan == 0:
                    continue
                bl = "border-left:2px solid #000;" if s in mark_segs else ""
                if typ == "free":
                    is_night_span = all(seg_i in night_segments for seg_i in range(s, e))
                    bg = "#d0d0d0" if is_night_span else "#ffffff"
                    style = f"background:{bg};color:#555;font-size:10px;text-align:center;border:1px solid #ccc;{bl}"
                elif typ == "relay_binome":
                    style = f"background:#4caf50;color:#000;font-size:10px;text-align:center;font-weight:bold;border:1px solid #2e7d32;{bl}"
                elif typ == "relay_solo":
                    style = f"background:#f48fb1;color:#000;font-size:10px;text-align:center;font-weight:bold;border:1px solid #c2185b;{bl}"
                elif typ == "unavail":
                    style = f"background:#8b00ff;border:1px solid #6a00cc;{bl}"
                else:
                    style = f"background:#fff;border:1px solid #ccc;{bl}"
                tds.append(f'<td colspan="{colspan}" style="{style}">{label}</td>')

            row = (
                f'<tr><th style="text-align:left;padding:2px 6px;white-space:nowrap;'
                f'font-size:12px;">{r}</th>{"".join(tds)}</tr>'
            )
            rows_html.append(row)

        header_tds = ['<th style="padding:1px;font-size:9px;width:20px;min-width:20px;"></th>']
        for seg in range(c.nb_segments):
            h = c.segment_start_hour(seg)
            is_mark = seg in mark_segs
            if is_mark:
                h_mod = h % 24
                closest_hh = min((0, 6, 12, 18), key=lambda hm: min(abs(h_mod - hm), 24 - abs(h_mod - hm)))
                label = f"{closest_hh:02d}h"
            else:
                label = ""
            bl = "border-left:2px solid #fff;" if is_mark else ""
            header_tds.append(
                f'<th style="background:#555;color:#fff;font-size:8px;padding:1px;'
                f'text-align:center;width:{SEG_WIDTH_PX}px;min-width:{SEG_WIDTH_PX}px;{bl}">{label}</th>'
            )
        header_row = f'<tr>{"".join(header_tds)}</tr>'

        h_end = c.segment_start_hour(c.nb_segments)
        day_end = DAY_NAMES[min(int(h_end // 24), 2)]
        hh_end, mm_end = int(h_end) % 24, int((h_end % 1) * 60)
        n_binomes, n_solos, km_solos, n_flex = self.stats()

        text_section = self._build_html_detail()

        return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Planning {c.total_km} km</title>
<style>
  body {{ font-family: sans-serif; font-size: 12px; margin: 16px; }}
  table {{ border-collapse: collapse; table-layout: fixed; }}
  th, td {{ padding: 2px; }}
</style>
</head>
<body>
<h2>Planning {c.total_km:.1f} km — {c.nb_segments} segments de {c.segment_km:.1f} km — Vitesse {c.speed_kmh:.1f} km/h</h2>
<p>Départ : {DAY_NAMES[0]} {c.start_hour:02d}h00 &nbsp;|&nbsp; Arrivée : {day_end} ~{hh_end:02d}h{mm_end:02d}</p>
<p>Binômes : <strong>{n_binomes}</strong> &nbsp;|&nbsp; Solos : <strong>{n_solos}</strong> ({km_solos:.1f} km) &nbsp;|&nbsp; Flex : <strong>{n_flex}</strong> &nbsp;|&nbsp; Score : <strong>{f"{self.score:.1f}" if self.score is not None else "—"}</strong></p>
<p>
  <span style="background:#4caf50;padding:2px 8px;border:1px solid #2e7d32;">Relais binôme</span>&nbsp;
  <span style="background:#f48fb1;padding:2px 8px;border:1px solid #c2185b;">Relais solo</span>&nbsp;
  <span style="background:#8b00ff;padding:2px 8px;border:1px solid #6a00cc;">&nbsp;&nbsp;&nbsp;</span> Indisponible
</p>
<div style="overflow-x:auto;">
<table>
{header_row}
{"".join(rows_html)}
</table>
</div>
{text_section}
</body>
</html>"""
