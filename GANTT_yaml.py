#!/usr/bin/env python3
"""
Basic Gantt chart from Overview.yaml.

* Items whose id ends in a letter after a number (D1.2a, D1.2b ...) are grouped under a small
  header row (D1.2), inset in the name column.
* One row per deliverable (bar from `start` to `due`) or milestone (diamond at `due`),
  grouped under a coloured band per work package.
* Bar colour = first lead; several leads = lighter shade of the first lead.
* Optional: status border, progress fill (`progress: 0-100`), today line, year lines.
* Writes an SVG (opens in any browser, imports into Word/PowerPoint/Inkscape).

Usage:  python GANTT_yaml.py [Overview.yaml] [output.svg] [LEAD] [--colours Colours.yaml]
Needs:  PyYAML only.
"""

import calendar
import argparse
import os
import re
import sys
import textwrap
from datetime import date
from xml.sax.saxutils import escape

import yaml

from Palette import Palette, find_config, tint

# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

parser = argparse.ArgumentParser(description=__doc__.split("Usage:")[0].strip().splitlines()[0])
parser.add_argument("yaml", nargs="?", default="Overview.yaml", help="project YAML (default: Overview.yaml)")
parser.add_argument("output", nargs="?", default="gantt.svg", help="output SVG (default: gantt.svg)")
parser.add_argument("lead", nargs="?", default=None, help="show only items involving this partner")
parser.add_argument("--colours", metavar="FILE", help="colour file (default: Colours.yaml, see Palette.py)")
args = parser.parse_args()

YAML_FILE = args.yaml
OUT_FILE = args.output
FILTER_LEAD = args.lead          # e.g. "LLC"; None = show everything
FILTER_KEEP_MILESTONES = False

# Colours come from Colours.yaml (see Palette.py): partners, status borders, milestone colour.
palette = Palette(find_config(args.colours, [os.path.dirname(os.path.abspath(YAML_FILE))]))
MILESTONE_COLOUR = palette.milestone
STATUS_COLOURS = palette.statuses
JOINT_TINT = 0.60


PX_PER_MONTH = 38
LABEL_W = 310            # width of the task-name column
ID_W = 46                # room for the bold id before the description
INDENT = 18              # inset for grouped items (D1.2a under D1.2)
MAX_LINES = 3            # descriptions wrap over up to this many lines ("..." if longer)
LINE_H = 13
CHAR_W = 5.6             # estimated px per character at 11px, used for wrapping
GROUP_ROW_H = 22
SHOW_GROUP_SPAN = True   # thin bracket on a group header from earliest start to latest due
ROW_H = 28
BAR_H = 14
WP_ROW_H = 32
HEADER_H = 58
FONT = "Helvetica, Arial, sans-serif"

SHOW_STATUS_BORDER = True
SHOW_PROGRESS = True     # darker fill up to `progress:` percent, if the YAML has it
SHOW_LEAD_TEXT = True    # small partner names to the right of each bar
SHOW_YEAR_LINES = True
SHOW_TODAY = True


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def leads(text):
    return [p.strip() for p in re.split(r"[;/,&]", str(text or "")) if p.strip()]


def first_colours(lead_list):
    return palette.colours_for(lead_list[0]) if lead_list else palette.fallback


def as_date(v):
    return date.fromisoformat(v) if isinstance(v, str) else v


def month_index(d):
    dim = calendar.monthrange(d.year, d.month)[1]
    return d.year * 12 + (d.month - 1) + (d.day - 1) / dim


# --------------------------------------------------------------------------
# Load
# --------------------------------------------------------------------------

with open(YAML_FILE, encoding="utf-8") as f:
    data = yaml.safe_load(f)

group_titles = {str(k): str(v) for k, v in (data.get("groups") or {}).items()}
wps = {}
for wp_id, wp in data["work_packages"].items():
    items = []
    for kind, key in (("deliverable", "deliverables"), ("milestone", "milestones")):
        for nid, n in (wp.get(key) or {}).items():
            due = as_date(n["due"])
            start = as_date(n.get("start"))
            if kind == "deliverable" and (start is None or start > due):
                why = "has no start" if start is None else f"starts ({start}) after it is due ({due})"
                print(f"WARNING: {nid} {why}; drawn as the month of its due date")
                start = date(due.year, due.month, 1)
            st = palette.status_key(n.get("status"))
            if st is None and str(n.get("status") or "").strip():
                print(f"WARNING: {nid} has unknown status '{n.get('status')}' "
                      f"(use: {', '.join(STATUS_COLOURS)}); no border drawn")
            prog = n.get("progress")
            items.append({
                "id": nid, "kind": kind, "title": str(n["title"]).strip(),
                "leads": leads(n.get("lead", "")),
                "start": start if kind == "deliverable" else due, "due": due,
                "status": st,
                "progress": float(prog) if isinstance(prog, (int, float)) else None,
            })
    wps[wp_id] = {"title": wp["title"], "lead": wp["lead"], "items": items}

if FILTER_LEAD:
    want = FILTER_LEAD.strip().lower()
    for wp in wps.values():
        wp["items"] = [i for i in wp["items"]
                       if want in [l.lower() for l in i["leads"]]
                       or (i["kind"] == "milestone" and FILTER_KEEP_MILESTONES)]
    wps = {k: v for k, v in wps.items() if v["items"]}
    if not wps:
        sys.exit(f"No items involve '{FILTER_LEAD}' - nothing to draw.")

used_names = [l for wp in wps.values() for i in wp["items"] for l in i["leads"]] + \
             [l for wp in wps.values() for l in leads(wp["lead"])]
legend_partners = palette.legend_partners(used_names)   # also auto-colours any new partner

for wp in wps.values():
    wp["items"].sort(key=lambda i: (i["start"], i["due"], i["id"]))


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

all_dates = [d for wp in wps.values() for i in wp["items"] for d in (i["start"], i["due"])]
d_min, d_max = min(all_dates), max(all_dates)
T0 = month_index(date(d_min.year, d_min.month, 1))
n_months = int(month_index(date(d_max.year, d_max.month, 1)) - T0) + 2   # whole months, + 1 spare


def x_of(d):
    return LABEL_W + (month_index(d) - T0) * PX_PER_MONTH


GROUP_RE = re.compile(r"^(.*\d)([a-z])$", re.I)


def common_prefix(titles):
    """Longest run of leading words shared by all titles (None if < 2 words or it eats a title)."""
    split = [t.split() for t in titles]
    n = 0
    for words in zip(*split):
        if len(set(words)) != 1:
            break
        n += 1
    if n < 2 or any(len(w) <= n for w in split):
        return None
    return " ".join(split[0][:n])


def clean(t):
    return t.strip(" -\u2013:.,;")


def wrap_desc(text, indent):
    chars = max(10, int((LABEL_W - indent - ID_W - 12) / CHAR_W))
    lines = textwrap.wrap(text, chars) or [""]
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES]
        lines[-1] = textwrap.shorten(lines[-1] + " ...", chars, placeholder="...") if len(lines[-1]) >= chars - 3 \
            else lines[-1] + " ..."
    return lines


# Build the row list: WP band -> (group header ->) items
rows = []
for wp_id, wp in wps.items():
    rows.append({"kind": "wp", "wp_id": wp_id, "wp": wp, "h": WP_ROW_H})

    units, buckets = [], {}
    for it in wp["items"]:
        m = GROUP_RE.match(it["id"]) if it["kind"] == "deliverable" else None
        if m:
            buckets.setdefault(m.group(1), []).append(it)
        else:
            units.append({"base": None, "items": [it]})
    for base, its in buckets.items():
        if len(its) >= 2:
            units.append({"base": base, "items": sorted(its, key=lambda i: i["id"])})
        else:
            units.extend({"base": None, "items": [i]} for i in its)
    units.sort(key=lambda u: (min(i["start"] for i in u["items"]),
                              min(i["due"] for i in u["items"]), u["items"][0]["id"]))

    for u in units:
        indent = 0
        if u["base"]:
            titles = [i["title"] for i in u["items"]]
            gt = group_titles.get(u["base"])
            if gt is None:
                pre = common_prefix(titles)
                if pre:
                    gt = clean(pre)
                    for i in u["items"]:
                        rest = clean(i["title"][len(pre):])
                        i["title"] = rest[:1].upper() + rest[1:]
            rows.append({"kind": "group", "id": u["base"], "title": gt or "", "h": GROUP_ROW_H,
                         "start": min(i["start"] for i in u["items"]),
                         "due": max(i["due"] for i in u["items"])})
            indent = INDENT
        for it in u["items"]:
            lines = wrap_desc(it["title"], indent)
            rows.append({"kind": "item", "it": it, "indent": indent, "lines": lines,
                         "h": max(ROW_H, len(lines) * LINE_H + 12)})

n_rows = len(rows)
CHART_W = LABEL_W + n_months * PX_PER_MONTH
body_h = sum(r["h"] for r in rows)
LEGEND_H = 70
W = CHART_W + 110
H = HEADER_H + body_h + LEGEND_H + 10


# --------------------------------------------------------------------------
# SVG
# --------------------------------------------------------------------------

svg = []
add = svg.append
add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
    f'viewBox="0 0 {W:.0f} {H:.0f}" font-family="{FONT}">')
add(f'<rect width="{W:.0f}" height="{H:.0f}" fill="white"/>')
body_top, body_bot = HEADER_H, HEADER_H + body_h

# Time header + vertical grid
m = date(d_min.year, d_min.month, 1)
for k in range(n_months):
    x = LABEL_W + k * PX_PER_MONTH
    jan = m.month == 1
    if SHOW_YEAR_LINES or not jan:
        add(f'<line x1="{x:.1f}" y1="{HEADER_H - 16}" x2="{x:.1f}" y2="{body_bot}" '
            f'stroke="{"#9ca3af" if jan else "#e5e7eb"}" stroke-width="{1 if jan else 0.6}" '
            f'stroke-dasharray="{"6,4" if jan else ""}"/>')
    add(f'<text x="{x + PX_PER_MONTH / 2:.1f}" y="{HEADER_H - 4}" text-anchor="middle" '
        f'font-size="9.5" fill="#374151">{m.strftime("%b")}</text>')
    if jan or k == 0:
        add(f'<text x="{x + 4:.1f}" y="{HEADER_H - 24}" font-size="12" font-weight="bold" '
            f'fill="#111827">{m.year}</text>')
    m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)

# Rows
y = HEADER_H
zebra = 0
for r in rows:
    h = r["h"]
    cy = y + h / 2

    if r["kind"] == "wp":
        wp, wp_id = r["wp"], r["wp_id"]
        c = first_colours(leads(wp["lead"]))
        add(f'<rect x="0" y="{y}" width="{CHART_W}" height="{h}" fill="{c["cluster"]}"/>')
        add(f'<rect x="0" y="{y}" width="6" height="{h}" fill="{c["node"]}"/>')
        add(f'<text x="14" y="{cy + 5}" font-size="13" font-weight="bold" fill="#111827">'
            f'{escape(wp_id)}: {escape(str(wp["title"]))}'
            f'<tspan font-weight="normal" font-size="11" fill="#374151">   Lead: {escape(str(wp["lead"]))}</tspan></text>')
        zebra = 0

    elif r["kind"] == "group":
        add(f'<rect x="0" y="{y}" width="{CHART_W}" height="{h}" fill="#f3f4f6"/>')
        add(f'<line x1="0" y1="{y + h}" x2="{CHART_W}" y2="{y + h}" stroke="#e5e7eb" stroke-width="0.8"/>')
        room = max(10, int((LABEL_W - 14 - ID_W) / CHAR_W))
        title = r["title"] if len(r["title"]) <= room else r["title"][:room - 3] + "..."
        add(f'<text x="14" y="{cy + 4}" font-size="11" fill="#111827"><tspan font-weight="bold">{escape(r["id"])}</tspan>'
            f'<tspan dx="8" fill="#374151">{escape(title)}</tspan></text>')
        if SHOW_GROUP_SPAN:
            x1, x2 = x_of(r["start"]), max(x_of(r["due"]), x_of(r["start"]) + 6)
            add(f'<rect x="{x1:.1f}" y="{cy - 3:.1f}" width="{x2 - x1:.1f}" height="6" rx="2" fill="#9ca3af"/>')
            for xx in (x1, x2 - 2):
                add(f'<rect x="{xx:.1f}" y="{cy - 6:.1f}" width="2" height="12" fill="#6b7280"/>')
        zebra = 0

    else:
        it, indent, lines = r["it"], r["indent"], r["lines"]
        if zebra % 2:
            add(f'<rect x="0" y="{y}" width="{CHART_W}" height="{h}" fill="#f9fafb"/>')
        zebra += 1

        tx = 14 + indent
        top = y + (h - len(lines) * LINE_H) / 2 + LINE_H - 3
        add(f'<text x="{tx}" y="{top:.1f}" font-size="11" font-weight="bold" fill="#111827">{escape(it["id"])}</text>')
        for k, line in enumerate(lines):
            add(f'<text x="{tx + ID_W}" y="{top + k * LINE_H:.1f}" font-size="11" fill="#111827">{escape(line)}</text>')

        ring = STATUS_COLOURS.get(it["status"]) if SHOW_STATUS_BORDER else None
        if it["kind"] == "milestone":
            x = x_of(it["due"])
            rr = 9
            pts = f"{x:.1f},{cy - rr:.1f} {x + rr:.1f},{cy:.1f} {x:.1f},{cy + rr:.1f} {x - rr:.1f},{cy:.1f}"
            if ring:
                add(f'<polygon points="{pts}" fill="none" stroke="{ring}" stroke-width="7" stroke-linejoin="round"/>')
                add(f'<polygon points="{pts}" fill="none" stroke="white" stroke-width="2.5" stroke-linejoin="round"/>')
            add(f'<polygon points="{pts}" fill="{MILESTONE_COLOUR}"/>')
            end_x = x + rr
        else:
            x1, x2 = x_of(it["start"]), x_of(it["due"])
            w = max(x2 - x1, 6)
            by = cy - BAR_H / 2
            base = first_colours(it["leads"])["node"]
            shared = len(it["leads"]) > 1
            full = tint(base, JOINT_TINT) if shared else base
            track = tint(base, 0.85 if shared else 0.65)
            geom_ = f'x="{x1:.1f}" y="{by:.1f}" width="{w:.1f}" height="{BAR_H}" rx="4"'
            if ring:
                add(f'<rect {geom_} fill="none" stroke="{ring}" stroke-width="7"/>')
                add(f'<rect {geom_} fill="none" stroke="white" stroke-width="2.5"/>')
            if SHOW_PROGRESS and it["progress"] is not None:
                pr = max(0, min(100, it["progress"])) / 100
                add(f'<rect {geom_} fill="{track}"/>')
                if pr > 0:
                    add(f'<rect x="{x1:.1f}" y="{by:.1f}" width="{w * pr:.1f}" height="{BAR_H}" rx="4" fill="{full}"/>')
                add(f'<rect {geom_} fill="none" stroke="{base}" stroke-width="1"/>')
            else:
                add(f'<rect {geom_} fill="{full}" stroke="{base}" stroke-width="1"/>')
            end_x = x1 + w

        if SHOW_LEAD_TEXT:
            add(f'<text x="{end_x + 10:.1f}" y="{cy + 4:.1f}" font-size="10" fill="#6b7280">'
                f'{escape(", ".join(it["leads"]))}</text>')
    y += h

# Frame, today line
add(f'<line x1="{LABEL_W}" y1="{HEADER_H - 16}" x2="{LABEL_W}" y2="{body_bot}" stroke="#6b7280" stroke-width="1.2"/>')
add(f'<line x1="0" y1="{HEADER_H - 16}" x2="{CHART_W}" y2="{HEADER_H - 16}" stroke="#6b7280" stroke-width="1"/>')
if SHOW_TODAY:
    today = date.today()
    if d_min <= today <= d_max:
        tx = x_of(today)
        add(f'<line x1="{tx:.1f}" y1="{HEADER_H - 16}" x2="{tx:.1f}" y2="{body_bot}" '
            f'stroke="#dc2626" stroke-width="1.5" stroke-dasharray="6,4"/>')
        add(f'<text x="{tx + 4:.1f}" y="{HEADER_H - 20}" font-size="10" fill="#dc2626">today</text>')

# Legend
lx, ly = 14, body_bot + 28
for lead, c in legend_partners:
    add(f'<rect x="{lx}" y="{ly - 11}" width="18" height="12" rx="3" fill="{c["node"]}"/>')
    add(f'<text x="{lx + 24}" y="{ly}" font-size="11" fill="#111827">{lead}</text>')
    lx += 24 + 8 * len(lead) + 20
first = legend_partners[0][1]["node"] if legend_partners else palette.fallback["node"]
add(f'<rect x="{lx}" y="{ly - 11}" width="18" height="12" rx="3" fill="{tint(first, JOINT_TINT)}" stroke="{first}"/>')
add(f'<text x="{lx + 24}" y="{ly}" font-size="11" fill="#111827">Several leads (shade of first)</text>')
lx += 24 + 7 * 30 + 20
add(f'<polygon points="{lx + 8},{ly - 12} {lx + 16},{ly - 5} {lx + 8},{ly + 2} {lx},{ly - 5}" fill="{MILESTONE_COLOUR}"/>')
add(f'<text x="{lx + 24}" y="{ly}" font-size="11" fill="#111827">Milestone</text>')

if SHOW_STATUS_BORDER:
    lx, ly = 14, ly + 24
    add(f'<text x="{lx}" y="{ly}" font-size="11" font-weight="bold" fill="#111827">Status:</text>')
    lx += 50
    for st, col in STATUS_COLOURS.items():
        add(f'<rect x="{lx}" y="{ly - 11}" width="22" height="12" rx="3" fill="#fff" '
            f'stroke="{col or "#9ca3af"}" stroke-width="{3 if col else 1}" '
            f'{"" if col else "stroke-dasharray=\'3,2\'"}/>')
        label = st if col else "Not Started (none)"
        add(f'<text x="{lx + 30}" y="{ly}" font-size="11" fill="#111827">{label}</text>')
        lx += 30 + 7 * len(label) + 20

if FILTER_LEAD:
    add(f'<text x="{CHART_W - 8}" y="{ly}" text-anchor="end" font-size="11" font-style="italic" '
        f'fill="#374151">Filtered: only items involving {escape(FILTER_LEAD)}</text>')

add("</svg>")

with open(OUT_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(svg))
print(f"Created {OUT_FILE}  ({W:.0f} x {H:.0f} px, {n_rows} rows, {PX_PER_MONTH}px/month)")
