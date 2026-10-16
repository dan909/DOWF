#!/usr/bin/env python3
"""
Horizon-style work-package chart with a true time axis.

* One big coloured box per work package, side by side.
* Vertical position of every deliverable / milestone = its due date
  (time runs down the page, one month = PX_PER_MONTH pixels).
* Items in the same WP whose dates are close share the box by moving into
  extra lanes (side by side) instead of overlapping.
* A thin bar beside each item shows start -> due.
* Dependency arrows are drawn between items.

Usage:  python Make.py [Overview.yaml] [output.svg] [LEAD] [--colours Colours.yaml]
        (LEAD, e.g. Compony LLC, shows only items involving that partner;
         colours/status colours come from Colours.yaml - see Palette.py)
Needs:  PyYAML only. Writes the SVG directly (no Graphviz).
"""

import argparse
import os
import random
import re
import sys
import textwrap
from collections import defaultdict
from datetime import date
from xml.sax.saxutils import escape

import yaml

from Palette import Palette, find_config, tint

# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

parser = argparse.ArgumentParser(description=__doc__.split("Usage:")[0].strip().splitlines()[0])
parser.add_argument("yaml", nargs="?", default="Overview.yaml", help="project YAML (default: Overview.yaml)")
parser.add_argument("output", nargs="?", default="project.svg", help="output SVG (default: project.svg)")
parser.add_argument("lead", nargs="?", default=None, help="show only items involving this partner")
parser.add_argument("--colours", metavar="FILE", help="colour file (default: Colours.yaml, see Palette.py)")
args = parser.parse_args()

YAML_FILE = args.yaml
OUT_FILE = args.output

# Show only the items involving ONE partner (e.g. "LLC"); None = show everything.
# Can also be given as the 3rd command-line argument.
FILTER_LEAD = args.lead          # e.g. "LLC"; None = show everything
FILTER_KEEP_MILESTONES = False   # True = keep every milestone even if the lead isn't involved

# Colours come from Colours.yaml (see Palette.py): partners, status borders, milestone colour.
palette = Palette(find_config(args.colours, [os.path.dirname(os.path.abspath(YAML_FILE))]))
MILESTONE_COLOUR = palette.milestone
STATUS_COLOURS = palette.statuses
JOINT_TINT = 0.60        # several leads -> this much white mixed into the FIRST lead's colour

PX_PER_MONTH = 80        # time scale
NODE_W = 200
LINE_H = 14              # text line height
WRAP = 27                # characters per label line
LANE_GAP = 34            # gap between lanes (holds the start->due bar and arrow channels)
VGAP = 30                # minimum vertical gap between boxes in one lane
WP_PAD = 34              # padding inside a WP box
WP_GAP = 30              # gap between WP boxes
AXIS_W = 90              # width of the time axis on the left
HEADER_H = 70            # WP title block height
FONT = "Helvetica, Arial, sans-serif"

HIDE_REDUNDANT_ARROWS = True   # drop A->C when A->B->C already exists
HIDE_BACKWARD_ARROWS = True    # drop arrows whose source is due AFTER the target
SHOW_DURATION_BARS = False
ARROW_JITTER = True            # vary which side arrows use and where they bend (False = tidy minimum)
ARROW_SEED = 1                 # change to get a different (but repeatable) arrangement
ARROW_RUN_MAX = 110            # furthest (px) an arrow may travel before/after its bend
SHOW_YEAR_LINES = True         # dashed line at every 1 January
SHOW_STATUS_BORDER = True      # thick border coloured by the `status:` field


ARROW_GAP = 8 if SHOW_STATUS_BORDER else 3            # space between an arrow head and the box it points at
SHOW_TODAY = True


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def leads(text):
    """'TV/LJMU; MT, Frendt' -> ['TV', 'LJMU', 'MT', 'Frendt']"""
    return [p.strip() for p in re.split(r"[;/,&]", str(text or "")) if p.strip()]


def first_colours(lead_list):
    return palette.colours_for(lead_list[0]) if lead_list else palette.fallback


def as_date(v):
    return date.fromisoformat(v) if isinstance(v, str) else v


def month_index(d):
    """Fractional months since year 0, so differences are in months."""
    # use real day fraction inside the month
    import calendar
    dim = calendar.monthrange(d.year, d.month)[1]
    return d.year * 12 + (d.month - 1) + (d.day - 1) / dim


def transitive_reduction(edges):
    succ = defaultdict(set)
    for a, b in edges:
        succ[a].add(b)

    def reachable(start, skip):
        seen, stack = set(), [start]
        while stack:
            n = stack.pop()
            for m in succ[n]:
                if (n, m) == skip or m in seen:
                    continue
                seen.add(m)
                stack.append(m)
        return seen

    return [(a, b) for a, b in edges if b not in reachable(a, (a, b))]


# --------------------------------------------------------------------------
# Load + validate
# --------------------------------------------------------------------------

with open(YAML_FILE, encoding="utf-8") as f:
    data = yaml.safe_load(f)

wps = data["work_packages"]
nodes = {}
for wp_id, wp in wps.items():
    for kind, key in (("deliverable", "deliverables"), ("milestone", "milestones")):
        for nid, n in (wp.get(key) or {}).items():
            node = {
                "id": nid, "kind": kind, "wp": wp_id, "title": n["title"],
                "leads": leads(n.get("lead", "")),
                "start": as_date(n.get("start")), "due": as_date(n["due"]),
                "status": n.get("status"),
            }
            st = palette.status_key(n.get("status"))
            if st is None and str(n.get("status") or "").strip():
                print(f"WARNING: {nid} has unknown status '{n.get('status')}' "
                      f"(use: {', '.join(STATUS_COLOURS)}); no border drawn")
            node["status"] = st
            if node["start"] and node["start"] > node["due"]:
                print(f"WARNING: {nid} starts ({node['start']}) after it is due "
                      f"({node['due']}); start bar not drawn")
                node["start"] = None
            nodes[nid] = node

edges = []
for dep in data.get("dependencies", []):
    a, b = dep["from"], dep["to"]
    if a in nodes and b in nodes:
        edges.append((a, b))
    else:
        print(f"WARNING: dependency {a} -> {b} refers to an unknown id, skipped")
edges = list(dict.fromkeys(edges))

# --------------------------------------------------------------------------
# Optional filter: keep only items involving FILTER_LEAD
# --------------------------------------------------------------------------
if FILTER_LEAD:
    want = FILTER_LEAD.strip().lower()
    if not palette.knows(FILTER_LEAD):
        print(f"WARNING: '{FILTER_LEAD}' is not in the colour file's partners ({', '.join(palette.names())})")

    def involves(n):
        return want in [l.lower() for l in n["leads"]] or \
               (n["kind"] == "milestone" and FILTER_KEEP_MILESTONES)

    keep_ids = [i for i, n in nodes.items() if involves(n)]       # keeps YAML order
    if not keep_ids:
        sys.exit(f"No deliverables or milestones involve '{FILTER_LEAD}' - nothing to draw.")
    keep_set = set(keep_ids)

    # Join up the logic across removed items: A -> (removed) -> C becomes A -> C
    succ = defaultdict(set)
    for a, b in edges:
        succ[a].add(b)
    bridged = []
    for a in keep_ids:
        seen, stack = set(), list(succ[a])
        while stack:
            m = stack.pop()
            if m in seen:
                continue
            seen.add(m)
            if m in keep_set:
                bridged.append((a, m))
            else:
                stack.extend(succ[m])
    order = {i: k for k, i in enumerate(nodes)}
    edges = sorted(set(bridged), key=lambda e: (order[e[0]], order[e[1]]))

    print(f"Filter '{FILTER_LEAD}': kept {len(keep_ids)} of {len(nodes)} items")
    nodes = {i: nodes[i] for i in keep_ids}
    wps = {w: wp for w, wp in wps.items() if any(n["wp"] == w for n in nodes.values())}

used_names = [l for n in nodes.values() for l in n["leads"]] + \
             [l for wp in wps.values() for l in leads(wp["lead"])]
legend_partners = palette.legend_partners(used_names)   # also auto-colours any new partner

if HIDE_REDUNDANT_ARROWS:
    kept = transitive_reduction(edges)
    print(f"Arrows: {len(edges)} in YAML, {len(kept)} drawn after removing redundant ones")
    edges = kept

backward = [(a, b) for a, b in edges if nodes[a]["due"] > nodes[b]["due"]]
for a, b in backward:
    print(f"NOTE: {a} (due {nodes[a]['due']}) -> {b} (due {nodes[b]['due']}) "
          f"points backwards in time" + ("; arrow hidden" if HIDE_BACKWARD_ARROWS else ""))
if HIDE_BACKWARD_ARROWS:
    edges = [e for e in edges if e not in backward]


# --------------------------------------------------------------------------
# Time axis
# --------------------------------------------------------------------------

all_dates = [n["due"] for n in nodes.values()] + \
            [n["start"] for n in nodes.values() if n["start"]]
t_min, t_max = min(all_dates), max(all_dates)
T0 = month_index(date(t_min.year, t_min.month, 1))


def y_of(d, base):
    return base + (month_index(d) - T0) * PX_PER_MONTH


# --------------------------------------------------------------------------
# Node sizes and lane assignment (needs a provisional y base; fixed up later)
# --------------------------------------------------------------------------

for n in nodes.values():
    n["lines"] = textwrap.wrap(n["title"], WRAP) or [n["title"]]
    n["h"] = (1 + len(n["lines"]) + 1) * LINE_H + 12  # id + title + (lead | date) line


BASE0 = 0  # provisional
col_lanes = {}
for wp_id in wps:
    members = sorted((n for n in nodes.values() if n["wp"] == wp_id),
                     key=lambda n: (n["due"], n["id"]))
    lane_bottom = []   # bottom y of the last box in each lane
    for n in members:
        cy = y_of(n["due"], BASE0)
        top, bottom = cy - n["h"] / 2, cy + n["h"] / 2
        for k, lb in enumerate(lane_bottom):
            if top >= lb + VGAP:
                n["lane"] = k
                lane_bottom[k] = bottom
                break
        else:
            n["lane"] = len(lane_bottom)
            lane_bottom.append(bottom)
    col_lanes[wp_id] = max(1, len(lane_bottom))


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

top_most = min([y_of(n["due"], 0) - n["h"] / 2 for n in nodes.values()] +
               [y_of(n["start"], 0) for n in nodes.values() if n["start"]])
bot_most = max(y_of(n["due"], 0) + n["h"] / 2 for n in nodes.values())
BASE = HEADER_H + 30 - top_most                    # shift so everything clears the header
CHART_BOTTOM = bot_most + BASE + 40

wp_x = {}
x = AXIS_W + 10
for wp_id in wps:
    width = 2 * WP_PAD + col_lanes[wp_id] * NODE_W + (col_lanes[wp_id] - 1) * LANE_GAP
    wp_x[wp_id] = (x, width)
    x += width + WP_GAP
CHART_RIGHT = x - WP_GAP

lane_xs, gutters = {}, {}
for wp_id in wps:
    wx, _ = wp_x[wp_id]
    xs = [wx + WP_PAD + k * (NODE_W + LANE_GAP) for k in range(col_lanes[wp_id])]
    lane_xs[wp_id] = xs
    gutters[wp_id] = [x0 - 12 for x0 in xs] + [xs[-1] + NODE_W + 12]

for n in nodes.values():
    wx, _ = wp_x[n["wp"]]
    n["x"] = wx + WP_PAD + n["lane"] * (NODE_W + LANE_GAP)
    n["cy"] = y_of(n["due"], BASE)
    n["y"] = n["cy"] - n["h"] / 2


# Classify each arrow, then spread arrows that share a box edge.
#   side   : boxes overlap in time -> short side-to-side arrow
#   direct : same lane, nothing in between -> straight line down
#   gutter : routed down a channel between lanes
def is_blocked(a, b):
    na, nb = nodes[a], nodes[b]
    lo, hi = na["y"] + na["h"], nb["y"]
    return any(m["wp"] == na["wp"] and m["lane"] == na["lane"] and m["id"] not in (a, b)
               and m["y"] < hi and m["y"] + m["h"] > lo for m in nodes.values())


def edge_kind(a, b):
    na, nb = nodes[a], nodes[b]
    if nb["y"] < na["y"] + na["h"]:
        return "side"
    if nb["wp"] == na["wp"] and nb["lane"] == na["lane"] and not is_blocked(a, b):
        return "direct"
    return "gutter"


kinds = {e: edge_kind(*e) for e in edges}
out_ports, in_ports = defaultdict(list), defaultdict(list)
has_direct = set()
for (a, b), k in kinds.items():
    if k == "gutter":
        out_ports[a].append(b)
        in_ports[b].append(a)
    elif k == "direct":
        has_direct.update((a, b))   # straight arrows use the box centre; others keep clear


def port_x(node, me, idx_list):
    order = sorted(idx_list, key=lambda o: nodes[o]["x"])
    k, m = order.index(me), len(order)
    if m == 1:
        # centre, unless a straight arrow already uses the centre of this box
        return node["x"] + NODE_W * (0.8 if node["id"] in has_direct else 0.5)
    usable = NODE_W - 40
    return node["x"] + 20 + usable * k / (m - 1)


# --------------------------------------------------------------------------
# SVG
# --------------------------------------------------------------------------

svg = []
add = svg.append
legend_h = (80 if SHOW_STATUS_BORDER else 50) + (28 if FILTER_LEAD else 0)
W = CHART_RIGHT + 50
H = CHART_BOTTOM + legend_h + 20

add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
    f'viewBox="0 0 {W:.0f} {H:.0f}" font-family="{FONT}">')
add('<defs>'
    '<marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
    'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#374151"/></marker>'
    '</defs>')
add(f'<rect width="{W:.0f}" height="{H:.0f}" fill="white"/>')

# WP boxes
for wp_id, wp in wps.items():
    wx, ww = wp_x[wp_id]
    c = first_colours(leads(wp["lead"]))
    add(f'<rect x="{wx}" y="10" width="{ww}" height="{CHART_BOTTOM - 10:.0f}" rx="16" '
        f'fill="{c["cluster"]}" stroke="{c["node"]}" stroke-width="3"/>')
    add(f'<text x="{wx + ww / 2}" y="38" text-anchor="middle" font-size="20" font-weight="bold" '
        f'fill="#111827">{escape(wp_id)}: {escape(wp["title"])}</text>')
    add(f'<text x="{wx + ww / 2}" y="58" text-anchor="middle" font-size="12" fill="#374151">'
        f'Lead: {escape(str(wp["lead"]))}</text>')

# Time grid + axis
first_month = date(t_min.year, t_min.month, 1)
y_cursor = first_month
while month_index(y_cursor) <= month_index(t_max) + 1:
    gy = y_of(y_cursor, BASE)
    jan = y_cursor.month == 1
    if SHOW_YEAR_LINES or not jan:
        add(f'<line x1="{AXIS_W - 10}" y1="{gy:.1f}" x2="{CHART_RIGHT}" y2="{gy:.1f}" '
            f'stroke="{"#9ca3af" if jan else "#d1d5db"}" stroke-width="{1 if jan else 0.6}" '
            f'stroke-dasharray="{"7,5" if jan else "2,5"}"/>')
    label = y_cursor.strftime("%b %Y") if (jan or y_cursor == first_month) else y_cursor.strftime("%b")
    add(f'<text x="{AXIS_W - 16}" y="{gy + 4:.1f}" text-anchor="end" font-size="11" '
        f'{"font-weight=\'bold\'" if jan else ""} fill="#374151">{label}</text>')
    y_cursor = date(y_cursor.year + (y_cursor.month == 12), y_cursor.month % 12 + 1, 1)

if SHOW_TODAY:
    today = date.today()
    if t_min <= today <= t_max:
        ty = y_of(today, BASE)
        add(f'<line x1="{AXIS_W - 10}" y1="{ty:.1f}" x2="{CHART_RIGHT}" y2="{ty:.1f}" '
            f'stroke="#dc2626" stroke-width="1.5" stroke-dasharray="6,4"/>')
        add(f'<text x="{CHART_RIGHT + 4}" y="{ty + 4:.1f}" font-size="11" fill="#dc2626">today</text>')

# Duration bars (start -> due)
if SHOW_DURATION_BARS:
    for n in nodes.values():
        if n["start"]:
            colour = (MILESTONE_COLOUR if n["kind"] == "milestone"
                      else first_colours(n["leads"])["node"])
            y1, y2 = y_of(n["start"], BASE), n["cy"]
            add(f'<rect x="{n["x"] - 31}" y="{y1:.1f}" width="5" height="{y2 - y1:.1f}" '
                f'rx="2.5" fill="{colour}" opacity="0.55"/>')

# Arrows (behind the boxes)
gcount = defaultdict(int)


def rank_of(lst, me):
    return sorted(lst, key=lambda o: nodes[o]["x"]).index(me)


def seg_hits_box(p, q, skip, pad=5):
    """Does the axis-aligned segment p-q pass through any box (other than `skip`)?"""
    x1, x2 = sorted((p[0], q[0]))
    y1, y2 = sorted((p[1], q[1]))
    for m in nodes.values():
        if m["id"] in skip:
            continue
        if (x2 > m["x"] - pad and x1 < m["x"] + NODE_W + pad and
                y2 > m["y"] - pad and y1 < m["y"] + m["h"] + pad):
            return True
    return False


def route_hits(pts, skip):
    return any(seg_hits_box(pts[i], pts[i + 1], skip) for i in range(len(pts) - 1))


def route_via_gutter(a, b, ax, bx, ka, kb, a_bot, b_top, end):
    na, nb = nodes[a], nodes[b]
    gl = gutters[nb["wp"]]

    def build(gx, y1, y2):
        c = gcount[(nb["wp"], round(gx))]
        off = ((c % 5) - 2) * 4                       # parallel arrows keep apart
        gx2 = gx + off
        return [(ax, a_bot), (ax, y1), (gx2, y1), (gx2, y2), (bx, y2), (bx, end)], (nb["wp"], round(gx))

    # Which gutters may be used?  Different lanes: only those lying BETWEEN the two ports, so the
    # arrow keeps moving the same way sideways (no overshoot-and-return).  Same lane (something
    # is in the way): the gutter on either side of the lane - a detour is unavoidable there.
    if nb["wp"] == na["wp"] and nb["lane"] == na["lane"]:
        cands = gl[na["lane"]:na["lane"] + 2]
    else:
        lo_x, hi_x = sorted((ax, bx))
        cands = [g for g in gl if lo_x < g < hi_x] or gl

    y1_min = a_bot + 8 + ka * 1.2
    y2_max = b_top - 15 - kb * 1.2                    # straight run-in before the head

    if ARROW_JITTER:
        rng = random.Random(f"{ARROW_SEED}:{a}->{b}")  # per-arrow, so edits elsewhere don't reshuffle
        for attempt in range(40):
            run = ARROW_RUN_MAX * (1 - attempt / 40)   # shrink the wander if it keeps failing
            gx = rng.choice(cands)
            y1 = y1_min + rng.uniform(0, run)
            y2 = y2_max - rng.uniform(0, run)
            if y2 < y1 + 12:
                continue
            pts, key = build(gx, y1, y2)
            if not route_hits(pts, {a, b}):
                gcount[key] += 1
                return pts

    # tidy fallback: nearest gutter, bend as close to the boxes as possible
    gx = min(cands, key=lambda g: abs(g - ax) + abs(g - bx))
    pts, key = build(gx, y1_min, y2_max)
    gcount[key] += 1
    return pts


for (a, b), kind in kinds.items():
    na, nb = nodes[a], nodes[b]
    a_bot, b_top = na["y"] + na["h"], nb["y"]

    if kind == "side":
        ay, by = na["cy"], nb["cy"]
        if nb["x"] >= na["x"] + NODE_W:
            p0, p1 = (na["x"] + NODE_W, ay), (nb["x"] - ARROW_GAP, by)
        else:
            p0, p1 = (na["x"], ay), (nb["x"] + NODE_W + ARROW_GAP, by)
        mid = (p0[0] + p1[0]) / 2
        pts = [p0, (mid, p0[1]), (mid, p1[1]), p1]
    else:
        end = b_top - ARROW_GAP
        if kind == "direct":
            cx = na["x"] + NODE_W / 2
            pts = [(cx, a_bot), (cx, end)]                    # straight down, centre to centre
        else:
            ax = port_x(na, b, out_ports[a])
            bx = port_x(nb, a, in_ports[b])
            ka, kb = rank_of(out_ports[a], b), rank_of(in_ports[b], a)
            pts = route_via_gutter(a, b, ax, bx, ka, kb, a_bot, b_top, end)
    d = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
    add(f'<polyline points="{d}" fill="none" stroke="#374151" stroke-width="1.4" '
        f'stroke-linejoin="round" opacity="0.85" marker-end="url(#arr)"/>')

# Nodes
for n in nodes.values():
    x0, y0, h = n["x"], n["y"], n["h"]
    if n["kind"] == "milestone":
        fill, text_col = MILESTONE_COLOUR, "white"
        ind = 16
        shape = ('polygon', 'points="' + " ".join(f"{px:.1f},{py:.1f}" for px, py in
                 [(x0 + ind, y0), (x0 + NODE_W - ind, y0), (x0 + NODE_W, y0 + h / 2),
                  (x0 + NODE_W - ind, y0 + h), (x0 + ind, y0 + h), (x0, y0 + h / 2)]) + '"')
        outline = 'stroke="#000" stroke-width="1.5"'
    else:
        base = first_colours(n["leads"])["node"]
        if len(n["leads"]) > 1:
            fill, text_col = tint(base, JOINT_TINT), "#111827"   # shared: light shade of first lead
        else:
            fill, text_col = base, "white"
        shape = ('rect', f'x="{x0}" y="{y0:.1f}" width="{NODE_W}" height="{h:.1f}" rx="10"')
        outline = f'stroke="{base}" stroke-width="1.5"' if len(n["leads"]) > 1 \
            else 'stroke="#000" stroke-opacity="0.4"'

    # status border: coloured ring + thin white gap, drawn under the box so it sits outside it
    ring = STATUS_COLOURS.get(n["status"]) if SHOW_STATUS_BORDER else None
    if ring:
        tag, geom = shape
        add(f'<{tag} {geom} fill="none" stroke="{ring}" stroke-width="9" stroke-linejoin="round"/>')
        add(f'<{tag} {geom} fill="none" stroke="white" stroke-width="3" stroke-linejoin="round"/>')

    tag, geom = shape
    add(f'<{tag} {geom} fill="{fill}" {outline}/>')

    cx = x0 + NODE_W / 2
    ty = y0 + 6 + LINE_H - 3
    add(f'<text x="{cx}" y="{ty:.1f}" text-anchor="middle" font-size="12" font-weight="bold" '
        f'fill="{text_col}">{escape(n["id"])}</text>')
    for line in n["lines"]:
        ty += LINE_H
        add(f'<text x="{cx}" y="{ty:.1f}" text-anchor="middle" font-size="11" '
            f'fill="{text_col}">{escape(line)}</text>')
    ty += LINE_H + 2
    margin = 28 if n["kind"] == "milestone" else 12
    lead_txt = ", ".join(n["leads"])
    add(f'<text x="{x0 + margin}" y="{ty:.1f}" text-anchor="start" font-size="10.5" '
        f'font-weight="bold" fill="{text_col}">{escape(lead_txt)}</text>')
    add(f'<text x="{x0 + NODE_W - margin}" y="{ty:.1f}" text-anchor="end" font-size="11" '
        f'fill="{text_col}">{n["due"].strftime("%b %Y")}</text>')

# Legend
lx, ly = AXIS_W + 10, CHART_BOTTOM + 25
for lead, c in legend_partners:
    add(f'<rect x="{lx}" y="{ly - 12}" width="18" height="14" rx="4" fill="{c["node"]}"/>')
    add(f'<text x="{lx + 24}" y="{ly}" font-size="12" fill="#111827">{lead}</text>')
    lx += 24 + 9 * len(lead) + 24
first = legend_partners[0][1]["node"] if legend_partners else palette.fallback["node"]
add(f'<rect x="{lx}" y="{ly - 12}" width="18" height="14" rx="4" fill="{tint(first, JOINT_TINT)}" '
    f'stroke="{first}" stroke-width="1.5"/>')
add(f'<text x="{lx + 24}" y="{ly}" font-size="12" fill="#111827">Several leads (shade of first)</text>')
lx += 24 + 7 * 30 + 24
add(f'<polygon points="{lx + 4},{ly - 12} {lx + 14},{ly - 12} {lx + 18},{ly - 5} {lx + 14},{ly + 2} '
    f'{lx + 4},{ly + 2} {lx},{ly - 5}" fill="{MILESTONE_COLOUR}"/>')
add(f'<text x="{lx + 24}" y="{ly}" font-size="12" fill="#111827">Milestone</text>')
lx += 110
if SHOW_DURATION_BARS:
    add(f'<rect x="{lx}" y="{ly - 12}" width="5" height="14" rx="2.5" fill="#6b7280" opacity="0.55"/>')
    add(f'<text x="{lx + 12}" y="{ly}" font-size="12" fill="#111827">start &#8594; due</text>')

if SHOW_STATUS_BORDER:
    lx, ly = AXIS_W + 10, ly + 28
    add(f'<text x="{lx}" y="{ly}" font-size="12" font-weight="bold" fill="#111827">Status:</text>')
    lx += 56
    for st, col in STATUS_COLOURS.items():
        if col:
            add(f'<rect x="{lx}" y="{ly - 12}" width="22" height="14" rx="4" fill="#fff" '
                f'stroke="{col}" stroke-width="3.5"/>')
        else:
            add(f'<rect x="{lx}" y="{ly - 12}" width="22" height="14" rx="4" fill="#fff" '
                f'stroke="#9ca3af" stroke-width="1" stroke-dasharray="3,2"/>')
        label = st + (" (no border)" if not col else "")
        add(f'<text x="{lx + 30}" y="{ly}" font-size="12" fill="#111827">{label}</text>')
        lx += 30 + 7 * len(label) + 22

if FILTER_LEAD:
    add(f'<text x="{AXIS_W + 10}" y="{ly + 28}" font-size="12" font-style="italic" fill="#374151">'
        f'Filtered: only items involving {escape(FILTER_LEAD)} are shown.</text>')

add("</svg>")

with open(OUT_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(svg))
print(f"Created {OUT_FILE}  ({W:.0f} x {H:.0f} px, {PX_PER_MONTH}px/month)")
