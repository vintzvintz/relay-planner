"""
Formatage des solutions CP-SAT.

API publique :
  RelaySolution(relais_list, constraints, score=None)
    .to_text() -> str
    .to_csv(filename)
    .to_json(filename)
    .to_html(filename)
    .save(quiet=False)
    .stats() -> (n_binomes, n_solos, km_solos, n_flex, n_pinned, km_flex)
"""

import csv
import io
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime

import verifications as verif

DAY_NAMES = ["Mercredi", "Jeudi", "Vendredi"]
DAY_SHORT = ["Mer", "Jeu", "Ven"]

OUTDIR = "plannings"

# quantité d'infos affichées sur la console
QUIET  = 0
STATS  = 1
DETAIL = 2


# ------------------------------------------------------------------
# Structures de données intermédiaires
# ------------------------------------------------------------------

@dataclass
class ChronoRelay:
    """Une ligne de relais dans le planning chronologique."""
    kind: str = "relay"          # toujours "relay"
    day_s: str = ""
    hh: int = 0
    mm: int = 0
    hh_end: int = 0
    mm_end: int = 0
    seg_start: int = 0
    km_start: float = 0.0
    km_dist: float = 0.0
    coureurs: str = ""
    tags: list = field(default_factory=list)
    rel: dict = field(default_factory=dict)  # dict brut pour row_class HTML


@dataclass
class ChronoPause:
    """Une ligne de pause dans le planning chronologique."""
    kind: str = "pause"          # toujours "pause"
    dur_str: str = ""
    ds: str = ""
    hs: int = 0
    ms: int = 0
    de: str = ""
    he: int = 0
    me: int = 0


@dataclass
class RelaisLine:
    """Une ligne de relais dans le récap par coureur."""
    day_s: str = ""
    hh: int = 0
    mm: int = 0
    hh_e: int = 0
    mm_e: int = 0
    km_dist: float = 0.0
    partenaire: str = ""
    repos_str: str = ""
    tags: list = field(default_factory=list)
    rel: dict = field(default_factory=dict)  # dict brut pour row_class HTML


@dataclass
class RunnerRecap:
    """Le récap complet d'un coureur."""
    name: str = ""
    total_km: float = 0.0
    n_relais: int = 0
    n_solo: int = 0
    n_nuit: int = 0
    relais: list = field(default_factory=list)  # list[RelaisLine]


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
    # Helpers privés bas niveau
    # ------------------------------------------------------------------

    @staticmethod
    def _chrono_tags(rel):
        return [t for t, v in [("fixe", (rel["pinned"] is not None)), ("solo", rel["solo"]), ("nuit", rel["night"])] if v]

    @staticmethod
    def _recap_tags(rel):
        return [t for t, v in [("fixe", (rel["pinned"] is not None)), ("nuit", rel["night"]), ("flex", rel["flex"])] if v]

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

    def _fmt_short_end(self, seg):
        """Heure de fin d'un relais se terminant au segment seg (pause débutant en seg exclue)."""
        c = self.constraints
        h = c.segment_end_hour(seg)
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

    def _pause_info(self, ps: int) -> ChronoPause:
        """Calcule les champs de représentation d'une pause à la frontière du segment ps."""
        c = self.constraints
        ph_start = c.segment_end_hour(ps)
        ph_end = c.segment_start_hour(ps)
        d_start, d_end = int(ph_start // 24), int(ph_end // 24)
        hs, ms = int(ph_start) % 24, int((ph_start % 1) * 60)
        he, me = int(ph_end) % 24, int((ph_end % 1) * 60)
        ds = DAY_SHORT[min(d_start, 2)]
        de = DAY_SHORT[min(d_end, 2)]
        dur = ph_end - ph_start
        dur_h, dur_m = int(dur), int((dur % 1) * 60)
        dur_str = f"{dur_h}h{dur_m:02d}" if dur_h else f"{dur_m}min"
        return ChronoPause(dur_str=dur_str, ds=ds, hs=hs, ms=ms, de=de, he=he, me=me)

    # ------------------------------------------------------------------
    # Méthodes de données pures (partagées texte + HTML)
    # ------------------------------------------------------------------

    def _build_chrono_entries(self) -> list:
        """Retourne la liste plate (ChronoRelay | ChronoPause) du planning chronologique."""
        c = self.constraints
        entries = []
        seen = set()
        pause_inserted = set()
        for rel in self.relais_list:
            dedup = self._dedup_key(rel)
            if dedup in seen and rel["partner"]:
                continue
            seen.add(dedup)

            day_s, hh, mm = self._fmt_short(rel["start"])
            _, hh_end, mm_end = self._fmt_short_end(rel["end"])
            coureurs = f"{rel['runner']} + {rel['partner']}" if rel["partner"] else rel["runner"]
            entries.append(ChronoRelay(
                day_s=day_s, hh=hh, mm=mm, hh_end=hh_end, mm_end=mm_end,
                seg_start=rel["start"],
                km_start=rel["start"] * c.segment_km,
                km_dist=rel["km"],
                coureurs=coureurs,
                tags=self._chrono_tags(rel),
                rel=rel,
            ))

            for ps in c.pause_segments:
                if rel["end"] == ps and ps not in pause_inserted:
                    pause_inserted.add(ps)
                    entries.append(self._pause_info(ps))

        return entries

    def _build_runner_recaps(self) -> list:
        """Retourne la liste de RunnerRecap, un par coureur trié."""
        c = self.constraints
        recaps = []
        for r in sorted(c.runners):
            r_rels = sorted(
                [x for x in self.relais_list if x["runner"] == r], key=lambda x: x["start"]
            )
            total = sum(x["km"] for x in r_rels)
            n_solo = sum(1 for x in r_rels if x["solo"])
            n_nuit = sum(1 for x in r_rels if x["night"])

            relais_lines = []
            for rel in r_rels:
                day_s, hh, mm = self._fmt_short(rel["start"])
                _, hh_e, mm_e = self._fmt_short(rel["end"])
                p = f"avec {rel['partner']}" if rel["partner"] else "seul"
                rest_h = rel["rest_h"]
                if rest_h is not None:
                    rh, rm = int(rest_h), int((rest_h % 1) * 60)
                    repos_str = f"repos {rh:2d}h{rm:02d}"
                else:
                    repos_str = ""
                relais_lines.append(RelaisLine(
                    day_s=day_s, hh=hh, mm=mm, hh_e=hh_e, mm_e=mm_e,
                    km_dist=rel["km"],
                    partenaire=p,
                    repos_str=repos_str,
                    tags=self._recap_tags(rel),
                    rel=rel,
                ))

            recaps.append(RunnerRecap(
                name=r, total_km=total, n_relais=len(r_rels),
                n_solo=n_solo, n_nuit=n_nuit, relais=relais_lines,
            ))
        return recaps

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def stats(self):
        """Retourne (n_binomes, n_solos, km_solos, n_flex, n_pinned, km_flex)."""
        c = self.constraints
        rl = self.relais_list
        n_binomes = sum(1 for x in rl if x["partner"]) // 2
        solos = [x for x in rl if x["solo"]]
        n_flex = sum(1 for x in rl if x["flex"])
        n_pinned = sum(1 for x in rl if x["pinned"] is not None)
        km_flex = sum(
            (max(c.runners_data[x["runner"]].relais[x["k"]].size) - x["size"]) * c.segment_km
            for x in rl if x["flex"]
        )
        return n_binomes, len(solos), sum(x["km"] for x in solos), n_flex, n_pinned, km_flex

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
            "k": rel["k"],
            "solo": rel["solo"],
            "nuit": rel["night"],
            "flex": rel["flex"],
            "pinned": rel.get("pinned"),
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
            n_binomes, n_solo, km_solo, n_flex, n_pinned, km_flex = self.stats()
            km_flex_str = f" ({km_flex:.1f} km)" if km_flex else ""
            print( f"score:{self.score:.1f} binomes:{n_binomes} solos:{n_solo} ({km_solo:.1f} km) flex:{n_flex}{km_flex_str} pinned:{n_pinned}  --> planning_{ts}")
        else: # verbose==QUIET
            pass


    # ------------------------------------------------------------------
    # Rendu texte (privé)
    # ------------------------------------------------------------------

    def _planning_chrono_lines(self):
        c = self.constraints
        W = 74
        lines = []
        n_binomes, n_solos, km_solos, n_flex, n_pinned, km_flex = self.stats()
        score_str = f"  Score:{self.score:.1f}" if self.score is not None else "  Score:<valeur>"
        flex_str = f"   Flex : {n_flex}" + (f" ({km_flex:.1f} km)" if km_flex else "")
        pinned_str = f"   Pinned : {n_pinned}" if n_pinned else ""
        c._ensure_lp()
        lp_str = f" (LP ≤{c.lp_upper_bound})" if c.lp_upper_bound is not None else ""
        lines.append("=" * W)
        lines.append(f"  PLANNING  {c.total_km:.1f} km — {c.nb_segments} segments de {c.segment_km:.1f} km - Vitesse {c.speed_kmh:.1f} km/h")
        lines.append(
            f"  Binômes : {n_binomes}{lp_str}  Solos : {n_solos} ({km_solos:.1f} km){flex_str}{pinned_str}{score_str}"
        )
        lines.append("=" * W)

        cw = self._chrono_coureurs_width()
        current_day = -1
        for entry in self._build_chrono_entries():
            if isinstance(entry, ChronoRelay):
                day = int(c.segment_start_hour(entry.seg_start) // 24)
                if day != current_day:
                    current_day = day
                    lines.append(f"\n▶ {DAY_NAMES[min(day, 2)].upper()}")
                debut = f"{entry.day_s} {entry.hh:02d}h{entry.mm:02d}"
                fin = f"{entry.hh_end:02d}h{entry.mm_end:02d}"
                seg_dep = f"{entry.seg_start:>3}"
                km_dep = f"{entry.km_start:>6.1f} km"
                flags = f"  [{' '.join(entry.tags)}]" if entry.tags else ""
                lines.append(f"  {debut} → {fin}   {seg_dep}   {km_dep}   {entry.km_dist:>4.1f} km   {entry.coureurs:<{cw}}{flags}")
            else:  # ChronoPause
                p = entry
                lines.append(f"  {'─' * (W - 2)}")
                lines.append(f"  ⏸  PAUSE {p.dur_str}   {p.ds} {p.hs:02d}h{p.ms:02d} → {p.de} {p.he:02d}h{p.me:02d}")
                lines.append(f"  {'─' * (W - 2)}")

        return lines

    def _recap_coureurs_lines(self):
        W = 74
        lines = []
        lines.append(f"\n{'─' * W}")
        lines.append("  PAR COUREUR")
        lines.append(f"{'─' * W}")
        pw = self._recap_partenaire_width()
        for recap in self._build_runner_recaps():
            flags = []
            if recap.n_solo:
                flags.append(f"{recap.n_solo} seul")
            if recap.n_nuit:
                flags.append(f"{recap.n_nuit} nuit")
            lines.append(
                f"\n{recap.name:<12}  {recap.total_km:>5.1f} km  {recap.n_relais} relais"
                + (f"  ({', '.join(flags)})" if flags else "")
            )
            for rl in recap.relais:
                flags_rel = f"  [{' '.join(rl.tags)}]" if rl.tags else ""
                lines.append(
                    f"  {rl.day_s} {rl.hh:02d}h{rl.mm:02d} → {rl.hh_e:02d}h{rl.mm_e:02d}"
                    f"  {rl.km_dist:>4.1f} km  {rl.partenaire:<{pw}}  {rl.repos_str:<11}{flags_rel}"
                )

        return lines

    # ------------------------------------------------------------------
    # Rendu HTML (privé)
    # ------------------------------------------------------------------

    def _build_html_detail(self):
        def row_class(rel):
            if rel["pinned"] is not None:
                return ' class="row-fixe"'
            if rel["solo"]:
                return ' class="row-solo"'
            if rel["partner"]:
                return ' class="row-binome"'
            return ""

        # --- Planning chronologique ---
        chrono_rows = []
        for entry in self._build_chrono_entries():
            if isinstance(entry, ChronoRelay):
                e = entry
                flags = ", ".join(e.tags)
                chrono_rows.append(
                    f'<tr{row_class(e.rel)}>'
                    f'<td class="td-time td-nowrap">{e.day_s} {e.hh:02d}h{e.mm:02d} → {e.hh_end:02d}h{e.mm_end:02d}</td>'
                    f'<td class="td-time td-right">{e.seg_start}</td>'
                    f'<td class="td-time td-right">{e.km_start:.1f} km</td>'
                    f'<td class="td-time td-right">{e.km_dist:.1f} km</td>'
                    f'<td class="td-time td-bold">{e.coureurs}</td>'
                    f'<td class="td-time td-meta">{flags}</td>'
                    f'</tr>'
                )
            else:  # ChronoPause
                p = entry
                chrono_rows.append(
                    f'<tr class="row-pause">'
                    f'<td class="td-pause td-nowrap" colspan="6">⏸&nbsp; PAUSE {p.dur_str} &nbsp;&mdash;&nbsp; {p.ds} {p.hs:02d}h{p.ms:02d} → {p.de} {p.he:02d}h{p.me:02d}</td>'
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
        for recap in self._build_runner_recaps():
            flags = []
            if recap.n_solo:
                flags.append(f"{recap.n_solo} seul")
            if recap.n_nuit:
                flags.append(f"{recap.n_nuit} nuit")
            flags_str = f" &nbsp;({', '.join(flags)})" if flags else ""

            detail_rows = []
            for rl in recap.relais:
                tags_str = ", ".join(rl.tags)
                detail_rows.append(
                    f'<tr{row_class(rl.rel)}>'
                    f'<td class="td-recap td-nowrap">{rl.day_s} {rl.hh:02d}h{rl.mm:02d} → {rl.hh_e:02d}h{rl.mm_e:02d}</td>'
                    f'<td class="td-recap td-right">{rl.km_dist:.1f} km</td>'
                    f'<td class="td-recap">{rl.partenaire}</td>'
                    f'<td class="td-recap td-meta">{rl.repos_str}</td>'
                    f'<td class="td-recap td-meta">{tags_str}</td>'
                    f'</tr>'
                )

            recap_sections.append(
                f'<h4 class="runner-title">{recap.name}'
                f'<span class="runner-subtitle"> — {recap.total_km:.1f} km, {recap.n_relais} relais{flags_str}</span></h4>'
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

        # pause_segments[i] = frontière : la pause s'insère entre seg ps-1 et seg ps
        pause_set = set(c.pause_segments)
        # nombre de colonnes équivalentes par frontière de pause
        pause_colspan_by_seg = {ps: c.pause_seg_durations[i] for i, ps in enumerate(c.pause_segments)}
        # durée en heures par frontière (pour le label header)
        pause_dur_by_seg = {ps: c.pause_duration_hours[i] for i, ps in enumerate(c.pause_segments)}

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
                cuts = sorted(m for m in mark_segs | pause_set if s < m < e)
                boundaries = [s] + cuts + [e]
                for i in range(len(boundaries) - 1):
                    result.append((boundaries[i], boundaries[i + 1], typ, label if i == 0 else ""))
            return result

        def _typ_to_css(typ, mark_class):
            if typ == "free":
                return f"seg-free{mark_class}"
            elif typ == "rest":
                return f"seg-rest{mark_class}"
            elif typ == "relay_binome":
                return f"seg-binome{mark_class}"
            elif typ == "relay_flex":
                return f"seg-flex{mark_class}"
            elif typ == "relay_solo":
                return f"seg-solo{mark_class}"
            elif typ == "relay_fixe":
                return f"seg-fixe{mark_class}"
            elif typ == "unavail":
                return f"seg-unavail{mark_class}"
            else:
                return f"seg-free{mark_class}"

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
                    if (rel["pinned"] is not None):
                        relay_typ = "relay_fixe"
                    elif rel["solo"]:
                        relay_typ = "relay_solo"
                    elif rel["flex"] and rel["partner"]:
                        relay_typ = "relay_flex"
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

            # Intercaler les pauses : construire une liste ordonnée (pause_at, ...)
            # puis émettre chaque pause exactement une fois entre les spans qui l'entourent
            pauses_sorted = sorted(c.pause_segments)
            pause_idx = 0  # index dans pauses_sorted

            tds = []
            for s, e, typ, label in spans:
                colspan = e - s
                if colspan == 0:
                    continue
                # Émettre toutes les pauses dont la frontière est <= s et pas encore émises
                while pause_idx < len(pauses_sorted) and pauses_sorted[pause_idx] <= s:
                    ps = pauses_sorted[pause_idx]
                    cs = pause_colspan_by_seg[ps]
                    tds.append(f'<td colspan="{cs}" class="seg-pause"></td>')
                    pause_idx += 1
                mark_class = " seg-mark" if s in mark_segs else ""
                css_class = _typ_to_css(typ, mark_class)
                tds.append(f'<td colspan="{colspan}" class="{css_class}">{label}</td>')

            # Pauses restantes après le dernier span
            while pause_idx < len(pauses_sorted):
                ps = pauses_sorted[pause_idx]
                cs = pause_colspan_by_seg[ps]
                tds.append(f'<td colspan="{cs}" class="seg-pause"></td>')
                pause_idx += 1

            rows_html.append(f'<tr><th class="th-runner">{r}</th>\n{chr(10).join(tds)}\n</tr>')

        header_tds = ['<th class="th-seg-label"></th>']
        for seg in range(c.nb_segments):
            # Insérer colonne pause avant ce segment si applicable
            if seg in pause_set:
                cs = pause_colspan_by_seg[seg]
                dur = pause_dur_by_seg[seg]
                dur_h = int(dur)
                dur_m = int((dur % 1) * 60)
                dur_str = f"{dur_h}h{dur_m:02d}" if dur_h else f"{dur_m}min"
                header_tds.append(f'<th colspan="{cs}" class="th-pause">⏸ {dur_str}</th>')
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
        if c.nb_segments in pause_set:
            cs = pause_colspan_by_seg[c.nb_segments]
            dur = pause_dur_by_seg[c.nb_segments]
            dur_h = int(dur)
            dur_m = int((dur % 1) * 60)
            dur_str = f"{dur_h}h{dur_m:02d}" if dur_h else f"{dur_m}min"
            header_tds.append(f'<th colspan="{cs}" class="th-pause">⏸ {dur_str}</th>')
        header_row = f'<tr>\n{chr(10).join(header_tds)}\n</tr>'

        return header_row, rows_html

    def _build_html(self):
        c = self.constraints

        header_row, rows_html = self._build_gantt()

        h_end = c.segment_start_hour(c.nb_segments)
        day_end = DAY_NAMES[min(int(h_end // 24), 2)]
        hh_end, mm_end = int(h_end) % 24, int((h_end % 1) * 60)
        n_binomes, n_solos, km_solos, n_flex, n_pinned, km_flex = self.stats()
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
  .seg-flex    {{ background: #a5d6a7; color: #000; font-size: 10px; text-align: center; font-weight: bold; border: 1px solid #66bb6a; }}
  .seg-solo    {{ background: #f48fb1; color: #000; font-size: 10px; text-align: center; font-weight: bold; border: 1px solid #c2185b; }}
  .seg-fixe    {{ background: #2196f3; color: #fff; font-size: 10px; text-align: center; font-weight: bold; border: 1px solid #1565c0; }}
  .seg-unavail {{ background: #8b00ff; border: 1px solid #6a00cc; }}
  .seg-mark    {{ border-left: 2px solid #000; }}
  .seg-pause   {{ background: #ff9800; border: 1px solid #e65100; }}
  .th-pause    {{ background: #ff9800; color: #fff; font-size: 9px; text-align: center; padding: 1px; }}

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
  .row-pause  {{ background: #fff3e0; }}
  .td-pause   {{ color: #e65100; font-weight: bold; padding: 4px 8px; }}

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
<p>Binômes : <strong>{n_binomes}</strong>{lp_str_html} &nbsp;|&nbsp; Solos : <strong>{n_solos}</strong> ({km_solos:.1f} km) &nbsp;|&nbsp; Flex : <strong>{n_flex}</strong>{km_flex_str} &nbsp;|&nbsp; Pinned : <strong>{n_pinned}</strong> &nbsp;|&nbsp; Score : <strong>{f"{self.score:.1f}" if self.score is not None else "—"}</strong></p>
<p>
  <span style="background:#4caf50;padding:2px 8px;border:1px solid #2e7d32;">Relais binôme</span>&nbsp;
  <span style="background:#a5d6a7;padding:2px 8px;border:1px solid #66bb6a;">Relais flex (binôme)</span>&nbsp;
  <span style="background:#f48fb1;padding:2px 8px;border:1px solid #c2185b;">Relais solo</span>&nbsp;
  <span style="background:#2196f3;padding:2px 8px;border:1px solid #1565c0;color:#fff;">Relais pinned</span>&nbsp;
  <span style="background:#8b00ff;padding:2px 8px;border:1px solid #6a00cc;">&nbsp;&nbsp;&nbsp;</span> Indisponible&nbsp;
  <span style="background:#ff9800;padding:2px 8px;border:1px solid #e65100;color:#fff;">⏸</span> Pause
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
