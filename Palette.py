"""
Shared colour handling for FlowDiagram_yaml.py and GANTT_yaml.py.

Colours are in a small YAML file (default name: Colours.yaml).  Lookup order for the file:
    1. --colours FILE on the command line
    2. Colours.yaml next to the project YAML
    3. Colours.yaml in the current folder
    4. Colours.yaml next to the scripts
If no file is found, partners are given colours automatically from a built-in palette.
Partners found in the data but missing from the file are also auto-coloured (with a note),
so a new partner never breaks the chart.
"""

import os
import re
import sys

import yaml

CONFIG_NAME = "Colours.yaml"

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

AUTO_PALETTE = ["#d62728", "#1f77b4", "#2ca02c", "#ff7f0e", "#9467bd",
                "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f"]

DEFAULT_STATUSES = {
    "Ongoing": "#2563eb", "Done": "#16a34a", "Started": "#6FEB9D", "Not Started": None,
    "Delayed": "#f97316", "Cancelled": "#dc2626",
}
DEFAULT_MILESTONE = "#111827"
DEFAULT_FALLBACK = {"node": "#999999", "cluster": "#eeeeee"}
CLUSTER_TINT = 0.85      # cluster colour made from `node` when the file doesn't give one


def tint(hex_colour, amount):
    """Mix a colour with white. amount=0 -> unchanged, 1 -> white."""
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (round(v + (255 - v) * amount) for v in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _hex(value, what, path):
    """Validate a #rgb / #rrggbb colour and return it as #rrggbb."""
    v = str(value).strip()
    if not _HEX.match(v):
        sys.exit(f"{path}: {what} is '{value}' - colours must be hex, like #d62728")
    if len(v) == 4:
        v = "#" + "".join(ch * 2 for ch in v[1:])
    return v.lower()


def find_config(explicit=None, search_dirs=()):
    """Return the path of the colour file to use, or None."""
    if explicit:
        if not os.path.isfile(explicit):
            sys.exit(f"Colour file not found: {explicit}")
        return explicit
    dirs = [d for d in search_dirs if d] + [os.getcwd(), os.path.dirname(os.path.abspath(__file__))]
    for d in dirs:
        p = os.path.join(d, CONFIG_NAME)
        if os.path.isfile(p):
            return p
    return None


class Palette:
    def __init__(self, path=None):
        self.path = path
        self.partners = {}                 # name -> {"node": ..., "cluster": ...}
        self.statuses = dict(DEFAULT_STATUSES)
        self.milestone = DEFAULT_MILESTONE
        self.fallback = dict(DEFAULT_FALLBACK)
        self._noted = set()

        if path:
            self._load(path)
            print(f"Colours: {path}")
        else:
            print(f"NOTE: no {CONFIG_NAME} found - colours are being assigned automatically")
        self._rebuild_lookups()

    # ------------------------------------------------------------------
    def _load(self, path):
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        for name, spec in (cfg.get("partners") or {}).items():
            if isinstance(spec, str):                      # shorthand:  TV: "#d62728"
                spec = {"node": spec}
            if not isinstance(spec, dict) or "node" not in spec:
                sys.exit(f"{path}: partner '{name}' needs at least a `node:` colour")
            node = _hex(spec["node"], f"partner {name} node", path)
            cluster = (_hex(spec["cluster"], f"partner {name} cluster", path)
                       if spec.get("cluster") else tint(node, CLUSTER_TINT))
            self.partners[str(name)] = {"node": node, "cluster": cluster}

        if cfg.get("statuses"):
            self.statuses = {}
            for name, col in cfg["statuses"].items():
                none = col is None or str(col).strip().lower() in ("", "none", "na", "n/a", "null")
                self.statuses[str(name)] = None if none else _hex(col, f"status {name}", path)

        if cfg.get("milestone"):
            self.milestone = _hex(cfg["milestone"], "milestone", path)

        fb = cfg.get("fallback")
        if fb:
            node = _hex(fb["node"] if isinstance(fb, dict) else fb, "fallback node", path)
            cluster = (_hex(fb["cluster"], "fallback cluster", path)
                       if isinstance(fb, dict) and fb.get("cluster") else tint(node, CLUSTER_TINT))
            self.fallback = {"node": node, "cluster": cluster}

    def _rebuild_lookups(self):
        self._partner_ci = {k.lower(): k for k in self.partners}
        self._status_ci = {k.lower(): k for k in self.statuses}

    # ------------------------------------------------------------------
    # Partners
    def knows(self, name):
        return str(name).strip().lower() in self._partner_ci

    def names(self):
        return list(self.partners)

    def colours_for(self, name):
        """{"node", "cluster"} for a partner (case-insensitive). Unknown -> auto-assigned."""
        key = str(name).strip()
        if not key:
            return self.fallback
        canon = self._partner_ci.get(key.lower())
        if canon is None:
            used = {c["node"] for c in self.partners.values()}
            node = next((c for c in AUTO_PALETTE if c not in used), None)
            if node is None:
                return self.fallback
            self.partners[key] = {"node": node, "cluster": tint(node, CLUSTER_TINT)}
            self._partner_ci[key.lower()] = key
            if self.path and key not in self._noted:
                print(f"NOTE: partner '{key}' is not in {os.path.basename(self.path)}; "
                      f"auto-coloured {node} (add it to the file to choose your own)")
            self._noted.add(key)
            canon = key
        return self.partners[canon]

    def legend_partners(self, used_names):
        """(name, colours) for the partners actually used, in colour-file order."""
        used = {str(n).strip().lower() for n in used_names}
        for n in used_names:
            self.colours_for(n)                           # make sure everything has a colour
        return [(k, v) for k, v in self.partners.items() if k.lower() in used]

    # ------------------------------------------------------------------
    # Statuses
    def status_key(self, raw):
        """Canonical status name for a YAML `status:` value.

        None/empty -> 'Not Started' if the file defines it, else None.
        Unknown text -> None (callers warn).
        """
        if raw is None or str(raw).strip() == "":
            return self._status_ci.get("not started")
        return self._status_ci.get(str(raw).strip().lower())
