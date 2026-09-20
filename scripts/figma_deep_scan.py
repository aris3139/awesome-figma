#!/usr/bin/env python3
"""
Figma Deep Scanner v5.2 — Blueprint Evidence Generator
======================================================
Scans raw Figma JSON node trees and produces structured context
for Root/component blueprint extraction.

Features:
  - Filters: off-screen, hidden, decorative, empty, SVG flatten
  - Computes: layout direction, padding, gap, alignment (from absolute coords)
  - Detects: scrollable areas, overlay/stack, active tabs
  - Keeps layer names exactly as Design wrote them (auto-rename removed 2026-09-17)
  - Outputs: structured blueprint evidence
  - v4.0: Split-screens mode for large scope
  - v5.1: icon export removed, portable paths (WebSocket export retired 2026-09 — clipboard source only)
  - v5.2: Improve & deep scanning
  - v5.4: Overlay/Scrim with content kept (scrim=), padded single-child wrappers kept, None-safe token pass

Usage:
    python3 figma_deep_scan.py <node_json_path>              # JSON output
    python3 figma_deep_scan.py --context <node_json_path>     # blueprint evidence text
    python3 figma_deep_scan.py --summary <node_json_path>     # tree outline
    python3 figma_deep_scan.py --context --split-screens <node_json_path>  # Split large scope

"""

import json, sys, os, argparse, re, math, copy
from collections import defaultdict, Counter

try:
    from .feature_layout import FeatureLayout
except ImportError:
    from feature_layout import FeatureLayout

# ─── Version ────────────────────────────────────────────────────────────────

SCRIPT_VERSION = "5.4"

# ─── Constants ────────────────────────────────────────────────────────────────

VIEWPORT_MARGIN = 5
OVERLAP_THRESHOLD = 0.20
CONTAINER_TYPES = {"FRAME", "INSTANCE", "COMPONENT", "COMPONENT_SET", "SECTION"}
VISUAL_TYPES = {"RECTANGLE", "ELLIPSE", "LINE", "STAR", "POLYGON", "BOOLEAN_OPERATION", "VECTOR"}
DECORATIVE_NAMES = {
    "glass effect", "blur", "gradient mask", "fill + shadow",
    "tint + shadow", "state-layer", "bounding box",
    "state layer", "scrim", "overlay",
}
INTERNAL_KEYWORDS = {"liquid glass", "chip material"}
# Names dropped at ANY depth (populated from --exclude). Unlike the old top-level-only
# filter, these are removed wherever they nest — e.g. a demo "Status Bar" / "Scroll Edge
# Effect" tucked inside a "Toolbar" wrapper. The wrapper then empties and is auto-pruned.
EXCLUDE_NAMES = set()

# ─── Stats ────────────────────────────────────────────────────────────────────

class Stats:
    def __init__(self):
        self.raw = 0; self.kept = 0
        self.off = 0; self.hid = 0; self.deco = 0; self.empty = 0; self.icons = 0

stats = Stats()

# ─── Color & Fill Parsing ─────────────────────────────────────────────────────

def color_hex(c, opacity=1.0):
    if not c: return None
    if isinstance(c, str):
        if opacity < 0.999: return f"{c} ({opacity:.0%})"
        return c
    r, g, b = int(c.get("r",0)*255), int(c.get("g",0)*255), int(c.get("b",0)*255)
    a = c.get("a", 1.0) * opacity
    if a < 0.999: return f"#{r:02X}{g:02X}{b:02X} ({a:.0%})"
    return f"#{r:02X}{g:02X}{b:02X}"

def parse_fill_short(fill):
    """Parse a single fill to a short string."""
    if not fill or fill.get("visible") is False: return None
    ft = fill.get("type", "SOLID")
    op = fill.get("opacity", 1.0)
    if ft == "SOLID":
        return color_hex(fill.get("color"), op)
    elif ft == "IMAGE":
        return "[IMAGE]"
    elif "GRADIENT" in ft:
        # v5.2: raw HAS full gradient data (type, handle positions, stop offsets)
        # — export angle + per-stop % instead of colors-only.
        stops = fill.get("gradientStops", [])
        parts = []
        for s in stops[:4]:
            c = color_hex(s.get("color"))
            if not c: continue
            pos = s.get("position")
            parts.append(f"{c} {round(pos * 100)}%" if pos is not None else c)
        kind = ft.replace("GRADIENT_", "")   # LINEAR / RADIAL / ANGULAR / DIAMOND
        handles = fill.get("gradientHandlePositions") or []
        angle = ""
        if kind == "LINEAR" and len(handles) >= 2:
            dx = handles[1].get("x", 0) - handles[0].get("x", 0)
            dy = handles[1].get("y", 0) - handles[0].get("y", 0)
            if dx or dy:
                # 0° = left→right, 90° = top→bottom (y grows downward)
                angle = f" {round(math.degrees(math.atan2(dy, dx))) % 360}°"
        return f"[GRADIENT_{kind}{angle} {' → '.join(parts)}]"
    return f"[{ft}]"

def first_fill(node):
    """Get first visible fill as a short string."""
    for f in node.get("fills", []):
        r = parse_fill_short(f)
        if r: return r
    return None

def text_color(node):
    """Get text color from fills."""
    for f in node.get("fills", []):
        if f.get("visible") is False: continue
        if f.get("type") == "SOLID":
            return color_hex(f.get("color"), f.get("opacity", 1.0))
    return None

# ─── Box Helpers ──────────────────────────────────────────────────────────────

def get_box(node):
    b = node.get("absoluteBoundingBox", {})
    return {
        "x": b.get("x", 0), "y": b.get("y", 0),
        "w": b.get("width", 0), "h": b.get("height", 0)
    }

def box_right(b): return b["x"] + b["w"]
def box_bottom(b): return b["y"] + b["h"]

# ─── Layout Computation (from absolute coordinates) ──────────────────────────

def compute_direction(child_boxes):
    """Detect layout direction from children positions."""
    if len(child_boxes) < 2: return "SINGLE"

    # Check if children flow horizontally or vertically
    b0, b1 = child_boxes[0], child_boxes[1]
    dx = abs(b1["x"] - b0["x"])
    dy = abs(b1["y"] - b0["y"])

    if dx > dy + 2:
        return "ROW"
    elif dy > dx + 2:
        return "COLUMN"
    else:
        # Check overlap — if children overlap significantly, it's STACK
        overlap_count = 0
        for i in range(len(child_boxes) - 1):
            a, b = child_boxes[i], child_boxes[i+1]
            h_overlap = max(0, min(box_right(a), box_right(b)) - max(a["x"], b["x"]))
            v_overlap = max(0, min(box_bottom(a), box_bottom(b)) - max(a["y"], b["y"]))
            min_w = min(a["w"], b["w"]) or 1
            min_h = min(a["h"], b["h"]) or 1
            if h_overlap/min_w > 0.5 and v_overlap/min_h > 0.5:
                overlap_count += 1
        if overlap_count > len(child_boxes) * 0.3:
            return "STACK"
        return "COLUMN"

def compute_gaps(child_boxes, direction, child_types=None):
    """Compute gaps between consecutive children."""
    if len(child_boxes) < 2: return []
    gaps = []
    for i in range(len(child_boxes) - 1):
        a, b = child_boxes[i], child_boxes[i+1]
        # Skip LINE nodes (height=0) for gap calculation
        if child_types and i < len(child_types) and child_types[i] == "LINE":
            continue
        if direction == "ROW":
            gaps.append(round(b["x"] - box_right(a)))
        else:
            gaps.append(round(b["y"] - box_bottom(a)))
    return gaps

def wrapper_padding(node, nbox, child_box, explicit_only=False):
    """Padding a container puts around its single child: explicit auto-layout values when present, else the
    offsets between the child's box and the container's (≥ 2 px, rounding noise ignored). {} = no padding."""
    lm = node.get("layoutMode")
    if lm in ("HORIZONTAL", "VERTICAL"):
        pad = {k: node.get(f, 0) or 0 for k, f in (("top", "paddingTop"), ("left", "paddingLeft"), ("right", "paddingRight"), ("bottom", "paddingBottom"))}
        return {k: (round(v) if float(v).is_integer() else round(v, 1)) for k, v in pad.items() if v > 0}
    if explicit_only or not child_box or not child_box.get("w"): return {}
    p = compute_padding(nbox, [child_box]) or {}
    return {k: v for k, v in p.items() if v >= 2}

def compute_padding(parent_box, child_boxes):
    """Compute padding from parent to children bounding rect."""
    if not child_boxes: return None
    min_x = min(b["x"] for b in child_boxes)
    min_y = min(b["y"] for b in child_boxes)
    max_x = max(box_right(b) for b in child_boxes)
    max_y = max(box_bottom(b) for b in child_boxes)
    p = {
        "top": round(min_y - parent_box["y"]),
        "left": round(min_x - parent_box["x"]),
        "right": round(box_right(parent_box) - max_x),
        "bottom": round(box_bottom(parent_box) - max_y)
    }
    # Clamp negatives from overlapping/overflowing children
    return {k: max(0, v) for k, v in p.items()}

def compute_alignment(child_boxes, parent_box, direction):
    """Detect alignment of children within parent."""
    if not child_boxes: return None
    pw, ph = parent_box["w"], parent_box["h"]
    if pw == 0 or ph == 0: return None

    if direction == "ROW":
        # Check vertical alignment of children
        centers = [(b["y"] + b["h"]/2 - parent_box["y"]) / ph for b in child_boxes]
        avg = sum(centers) / len(centers)
        if abs(avg - 0.5) < 0.1: return "center"
        elif avg < 0.3: return "top"
        elif avg > 0.7: return "bottom"
    else:
        # Check horizontal alignment
        centers = [(b["x"] + b["w"]/2 - parent_box["x"]) / pw for b in child_boxes]
        avg = sum(centers) / len(centers)
        if abs(avg - 0.5) < 0.1: return "center"
        elif avg < 0.3: return "start"
        elif avg > 0.7: return "end"
    return None

def detect_scrollable(parent_box, child_boxes, direction):
    """Detect if children extend beyond parent (scrollable)."""
    if not child_boxes: return None
    children_max_x = max(box_right(b) for b in child_boxes)
    children_max_y = max(box_bottom(b) for b in child_boxes)

    if direction == "ROW" and children_max_x > box_right(parent_box) + 5:
        return "HORIZONTAL"
    if direction == "COLUMN" and children_max_y > box_bottom(parent_box) + 5:
        return "VERTICAL"
    return None

def compute_overlay_position(child_box, parent_box):
    """Detect position of an overlay child relative to parent."""
    px, py, pw, ph = parent_box["x"], parent_box["y"], parent_box["w"], parent_box["h"]
    cx, cy, cw, ch = child_box["x"], child_box["y"], child_box["w"], child_box["h"]
    if pw == 0 or ph == 0: return None

    rel_x = (cx - px) / pw
    rel_y = (cy - py) / ph

    v = "top" if rel_y < 0.33 else ("bottom" if rel_y > 0.5 else "center")
    h = "left" if rel_x < 0.33 else ("right" if rel_x > 0.5 else "center")
    offset_x = round(cx - px) if h == "left" else round(box_right(parent_box) - box_right(child_box))
    offset_y = round(cy - py) if v == "top" else round(box_bottom(parent_box) - box_bottom(child_box))

    return {"position": f"{v}-{h}", "offsetX": offset_x, "offsetY": offset_y}

def estimate_max_lines(text_height, font_size):
    """Estimate max lines from text box height and font size."""
    if not font_size or font_size == 0: return 1
    line_height = font_size * 1.4
    return max(1, round(text_height / line_height))

# ─── Filtering ────────────────────────────────────────────────────────────────

def is_offscreen(box, viewport):
    if not box or not viewport: return False
    vx, vy, vw, vh = viewport
    m = VIEWPORT_MARGIN
    x, y = box.get("x",0), box.get("y",0)
    w, h = box.get("width", box.get("w",0)), box.get("height", box.get("h",0))
    return (y > vy+vh+m or y+h < vy-m or x > vx+vw+m or x+w < vx-m)

def has_text_content(node, depth=0):
    """True when any visible descendant is a non-empty TEXT. Measured 2026-09-18 on 70 real screens: layers named
    Overlay/Scrim wrap whole dialogs and bottom sheets (36 texts), and Material `State-layer` frames wrap button and
    list-item labels (256 texts) — dropping them by name lost all of that. INSTANCE descendants do NOT count: `BG`,
    `Chip Material` and `State-layer` routinely contain glass/material instances that are decoration."""
    if depth > 12 or not isinstance(node, dict): return False
    for c in node.get("children") or []:
        if not isinstance(c, dict) or c.get("visible") is False: continue
        if c.get("type") == "TEXT" and (c.get("characters") or "").strip(): return True
        if has_text_content(c, depth + 1): return True
    return False

def is_decorative(name, ntype, node=None):
    nl = name.lower()
    deco = (nl in DECORATIVE_NAMES
            or any(kw in nl for kw in INTERNAL_KEYWORDS)
            or (nl == "bg" and ntype in ("INSTANCE", "ICON")))
    if deco and node is not None and has_text_content(node):
        return False   # v5.4: a decorative NAME on a content-bearing subtree is a wrapper, keep it (fill → scrim=/stateLayer=)
    return deco

def layer_kind(name):
    """Which non-background role a kept decorative-named wrapper plays (its fill is a tint, not the surface colour)."""
    nl = name.lower()
    if nl in ("overlay", "scrim"): return "scrim"
    if nl in ("state-layer", "state layer"): return "stateLayer"
    return None

def absorbed_effects(node):
    """Material/effect signals from the decorative+internal child subtrees that get
    DROPPED. Figma represents glassmorphism (Glass Effect / Liquid glass / Chip
    Material), shadows and blurs as separate named layers, and the legacy plugin source returned
    NO `effects` array — so without hoisting these, a frosted chip/button collapses
    to a flat fill (the #1 cause of glass designs scanning "wrong"). We scan ONLY
    the to-be-dropped subtrees, so the hint attaches to the real node that owns
    them and never bleeds onto unrelated ancestors.
    Returns a list subset of ["glass","blur","shadow"]."""
    hints = []
    def collect(n, depth=0):
        if depth > 5: return
        nm = (n.get("name") or "").lower()
        if ("glass" in nm or "chip material" in nm) and "glass" not in hints: hints.append("glass")
        if "shadow" in nm and "shadow" not in hints: hints.append("shadow")
        if (nm == "blur" or nm.endswith(" blur")) and "blur" not in hints: hints.append("blur")
        for c in n.get("children") or []: collect(c, depth + 1)
    for c in node.get("children") or []:
        cn = c.get("name", "")
        if is_decorative(cn, c.get("type", ""), c) or (any(k in cn.lower() for k in INTERNAL_KEYWORDS) and not has_text_content(c)):
            collect(c)
    return hints

def is_vector_subtree(node, depth=0):
    ntype = node.get("type", "")
    children = node.get("children", [])
    if ntype == "TEXT": return False
    if ntype in VISUAL_TYPES and not children: return True
    if ntype in {"GROUP","FRAME","SLOT"} and not children: return True
    if ntype == "INSTANCE" and children:
        return should_flatten_icon(node)          # nested glyph instance counts as vector content; other instances do not
    if ntype in {"GROUP","FRAME","BOOLEAN_OPERATION","SLOT"} and children:
        if depth > 5: return True
        return all(is_vector_subtree(c, depth+1) for c in children)
    return False

def count_descendants(node):
    c = 0
    for ch in node.get("children",[]): c += 1 + count_descendants(ch)
    return c

def has_vector_descendant(node):
    for ch in node.get("children", []):
        if ch.get("type") in {"VECTOR", "BOOLEAN_OPERATION", "STAR", "POLYGON"} or has_vector_descendant(ch): return True
    return False

def should_flatten_icon(node):
    children = node.get("children",[])
    if not children: return False
    if node.get("type","") not in {"GROUP","FRAME","BOOLEAN_OPERATION","INSTANCE","SLOT"}: return False
    if node.get("type") == "INSTANCE":
        # a glyph component (Material/SF symbol: Bounding box + VECTOR) — not a shapes-only component such as a chip or card
        bb = node.get("absoluteBoundingBox", {})
        if not has_vector_descendant(node) or bb.get("width", 0) > 96 or bb.get("height", 0) > 96: return False
        return all(is_vector_subtree(c, 1) for c in children)   # children, not node — avoids recursing through the INSTANCE branch
    if len(children) == 1 and children[0].get("type") == "INSTANCE" and should_flatten_icon(children[0]):
        return False   # a wrapper around one glyph instance: let the glyph itself be the ICON (keeps its name and 24×24 box)
    if count_descendants(node) < 2: return False
    return is_vector_subtree(node)

# ─── Shared node properties (v5.3, clipboard source) ─────────────────────────

def attach_common(result, node):
    """Properties the mapper emits for any node kind: blend mode, rotation, mask, absolute positioning,
    constraints, min/max size, prototype interactions (navigation targets), variable modes."""
    bm = node.get("blendMode")
    if bm and bm not in ("NORMAL", "PASS_THROUGH"): result["blend"] = bm
    rot = node.get("rotation")
    if rot: result["rotation"] = rot
    if node.get("isMask"): result["mask"] = (node.get("maskType") or "ALPHA").lower()
    if node.get("layoutPositioning") == "ABSOLUTE": result["absolute"] = True
    cons = node.get("constraints") or {}
    h, v = cons.get("horizontal"), cons.get("vertical")
    if (h and h != "LEFT") or (v and v != "TOP"):
        result["constraints"] = f"h={h or 'LEFT'} v={v or 'TOP'}"
    for k, f in (("minW", "minWidth"), ("minH", "minHeight"), ("maxW", "maxWidth"), ("maxH", "maxHeight")):
        val = node.get(f)
        if val: result[k] = round(val)
    inter = []
    for it in node.get("interactions") or []:
        act = it.get("action") or ""
        trig = it.get("trigger") or ""
        if act == "SWAP_STATE" and trig in ("MOUSE_DOWN", "MOUSE_UP", "ON_PRESS", "ON_HOVER", "MOUSE_ENTER", "MOUSE_LEAVE"):
            continue   # press/hover feedback of a component, not a screen transition
        dest = it.get("destination") or {}
        if dest.get("name"): target = f'"{dest["name"]}"'
        elif dest.get("id"): target = f"node {dest['id']} (not in clipboard)"
        elif it.get("url"): target = it["url"]
        elif act in ("BACK", "CLOSE", "SCROLL_TO", "SET_VARIABLE"): target = ""
        else: target = "target not set in Figma"
        inter.append(f"{trig} {act} {target}".rstrip())
    if inter: result["interactions"] = inter
    modes = node.get("variableModes")
    if modes: result["modes"] = ", ".join(modes)
    return result

# ─── Main Scan ────────────────────────────────────────────────────────────────

def scan(node, viewport, parent_box=None, depth=0):
    """Recursively scan node tree, filter noise, compute layout context."""
    stats.raw += 1

    name = node.get("name", "")
    ntype = node.get("type", "")
    raw_box = node.get("absoluteBoundingBox", {})
    bx = raw_box.get("x", 0)
    by = raw_box.get("y", 0)
    bw = raw_box.get("width", 0)
    bh = raw_box.get("height", 0)
    nbox = {"x": bx, "y": by, "w": bw, "h": bh}

    # ── Filters ──
    if is_offscreen(raw_box, viewport) and depth > 0:
        stats.off += 1; return None

    if node.get("visible") is False or node.get("opacity", 1) == 0:
        stats.hid += 1; return None

    # Clipped/GONE detection: if child is mostly outside parent bounds, it's clipped
    # This catches nodes hidden by parent clipping (GONE state in Figma).
    # Check BOTH axes — vertical (list clip) and horizontal (e.g. toolbar slot
    # 40px wide with variant buttons spilling out → only 1 visible).
    if parent_box and depth > 1:
        if bh > 0 and parent_box.get("h", 0) > 0:
            visible_top = max(by, parent_box["y"])
            visible_bottom = min(by + bh, parent_box["y"] + parent_box["h"])
            visible_h = max(0, visible_bottom - visible_top)
            if visible_h / bh < 0.3:
                stats.hid += 1; return None
        if bw > 0 and parent_box.get("w", 0) > 0:
            visible_left = max(bx, parent_box["x"])
            visible_right = min(bx + bw, parent_box["x"] + parent_box["w"])
            visible_w = max(0, visible_right - visible_left)
            if visible_w / bw < 0.3:
                stats.hid += 1; return None

    # Zero-size nodes (width=0 AND height=0)
    if bw == 0 and bh == 0 and ntype != "LINE":
        stats.hid += 1; return None

    # Empty SLOT
    if ntype == "SLOT" and not node.get("children"):
        stats.hid += 1; return None

    # Decorative (by name; a subtree that carries TEXT is content wearing a decorative name and is kept — v5.4)
    if is_decorative(name, ntype, node):
        stats.deco += 1; return None

    # Excluded by name at ANY depth (--exclude): device chrome / demo-only layers that
    # nest inside wrappers (e.g. "Status Bar" / "Scroll Edge Effect" under a "Toolbar").
    if EXCLUDE_NAMES and name.lower() in EXCLUDE_NAMES:
        stats.deco += 1; return None

    # Lone VECTOR leaf (not wrapped in a glyph instance) drawn at icon size → ICON as well
    if ntype == "VECTOR" and not node.get("children") and bw >= 12 and bh >= 12:
        stats.icons += 1
        result = attach_common({"name": name, "type": "ICON", "size": f"{bw:.0f}×{bh:.0f}", "_id": node.get("id")}, node)
        fill = first_fill(node)
        if fill: result["fill"] = fill
        if parent_box: result["_box"] = nbox
        stats.kept += 1
        return result

    # Flatten SVG icons
    if should_flatten_icon(node):
        stats.icons += 1
        result = attach_common({
            "name": name, "type": "ICON", "_id": node.get("id"),
            "size": f"{bw:.0f}×{bh:.0f}",
        }, node)
        fill = first_fill(node)
        if fill: result["fill"] = fill
        cr = node.get("cornerRadius")
        if cr and cr > 0: result["radius"] = round(cr)
        op = node.get("opacity", 1)
        if op < 1: result["opacity"] = f"{op:.0%}"
        # Position relative to parent
        if parent_box:
            result["_box"] = nbox
            if node.get("layoutGrow"): result["_layoutGrow"] = node.get("layoutGrow")
            if node.get("layoutAlign"): result["_layoutAlign"] = node.get("layoutAlign")
        stats.kept += 1
        return result

    # Leaf INSTANCE with no children = icon/button component whose internals
    # aren't in the source JSON (legacy plugin case; clipboard gives a shell master) — e.g. a follow button, a bell icon.
    # Keep it as an ICON placeholder instead of pruning it as "empty" — it is a
    # meaningful interactive/visual element, not noise.
    # Exception: empty text-slot instances (subtitle/caption/placeholder) carry no
    # content and aren't visual — drop them as empty.
    EMPTY_SLOT_NAMES = ("subtitle", "caption", "placeholder", "supporting text")
    if ntype == "INSTANCE" and not node.get("children") \
            and not any(k in name.lower() for k in EMPTY_SLOT_NAMES):
        stats.icons += 1
        result = attach_common({"name": name, "type": "ICON", "size": f"{bw:.0f}×{bh:.0f}", "_id": node.get("id")}, node)
        fill = first_fill(node)
        if fill: result["fill"] = fill
        cr = node.get("cornerRadius")
        if cr and cr > 0: result["radius"] = round(cr)
        if parent_box: result["_box"] = nbox
        stats.kept += 1
        return result

    # ── Build result ──
    result = {"name": name, "type": ntype, "size": f"{bw:.0f}×{bh:.0f}"}

    # Visual properties
    fill = first_fill(node)
    if fill: result["fill"] = fill

    # cornerRadius: uniform first, then per-corner (non-uniform overrides)
    cr = node.get("cornerRadius")
    if cr and cr > 0:
        result["radius"] = round(cr)
    else:
        # Individual corners — only when at least one is non-zero AND they differ
        r_tl = node.get("topLeftRadius") or 0
        r_tr = node.get("topRightRadius") or 0
        r_br = node.get("bottomRightRadius") or 0
        r_bl = node.get("bottomLeftRadius") or 0
        corners = [r_tl, r_tr, r_br, r_bl]
        if any(c > 0 for c in corners) and len(set(corners)) > 1:
            result["radius"] = f"tl={r_tl:.0f} tr={r_tr:.0f} br={r_br:.0f} bl={r_bl:.0f}"
        elif any(c > 0 for c in corners):           # all equal but cornerRadius was 0/None
            result["radius"] = round(corners[0])

    op = node.get("opacity", 1)
    if op < 1: result["opacity"] = f"{op:.0%}"

    # stroke / border — the source JSON carries `strokes`
    # (color + opacity) but DROPS `strokeWeight`/`strokeAlign` (same gap as
    # effects[]). So gate only on a non-empty solid stroke; keep the exact
    # color+alpha (the golden that matters), default weight to 1px when unknown.
    strokes = node.get("strokes") or []
    if strokes:
        stroke_w = node.get("strokeWeight")
        for s in strokes:
            if s.get("visible") is not False and s.get("type") == "SOLID":
                sc = color_hex(s.get("color"), s.get("opacity", 1.0))
                if sc:
                    sa = (node.get("strokeAlign") or "INSIDE").lower()
                    sides = node.get("individualStrokeWeights")
                    if sides and len(set(round(v, 2) for v in sides.values())) > 1:
                        # one-side divider / underline: only the non-zero sides
                        w = " ".join(f"{k[0]}={v:g}" for k, v in (("top", sides.get("top", 0)), ("right", sides.get("right", 0)),
                                                                 ("bottom", sides.get("bottom", 0)), ("left", sides.get("left", 0))) if v)
                        w = f"sides({w})"
                    else:
                        w = f"{stroke_w:g}px" if stroke_w else "1px"
                    result["stroke"] = f"{sc} {w} {sa}"
                    dashes = node.get("strokeDashes")
                    if dashes: result["stroke"] += " dashed(" + ",".join(f"{d:g}" for d in dashes) + ")"
                break   # first visible solid stroke only

    # effects[] — only parse if the source returned the array (clipboard does)
    raw_effects = node.get("effects")   # None when absent
    if raw_effects:                      # truthy: non-empty list
        for eff in raw_effects:
            if not eff.get("visible", True): continue
            eff_type = eff.get("type", "")
            if eff_type == "DROP_SHADOW" and "shadow" not in result:
                ec = color_hex(eff.get("color"))
                offset = eff.get("offset") or {}
                ox = round(offset.get("x", 0))
                oy = round(offset.get("y", 0))
                bl = round(eff.get("radius", 0))
                sp = round(eff.get("spread", 0))
                spread_str = f" spread={sp}" if sp else ""
                if ec:
                    result["shadow"] = f"{ec} offset=({ox},{oy}) blur={bl}{spread_str}"
            elif eff_type == "INNER_SHADOW" and "innerShadow" not in result:
                ec = color_hex(eff.get("color"))
                offset = eff.get("offset") or {}
                ox = round(offset.get("x", 0)); oy = round(offset.get("y", 0))
                bl = round(eff.get("radius", 0)); sp = round(eff.get("spread", 0))
                if ec:
                    result["innerShadow"] = f"{ec} offset=({ox},{oy}) blur={bl}" + (f" spread={sp}" if sp else "")
            elif eff_type in ("LAYER_BLUR", "FOREGROUND_BLUR", "BACKGROUND_BLUR") and "blurRadius" not in result:
                bl_r = eff.get("radius")
                if bl_r:    # 0 radius = no-op, skip
                    kind = "bg" if eff_type == "BACKGROUND_BLUR" else ""
                    result["blurRadius"] = f"{round(bl_r)}{' bg' if kind else ''}"

    # clipsContent — only if True (False = default)
    if node.get("clipsContent") is True:
        result["overflow"] = "hidden"

    attach_common(result, node)

    # Hoist glass/shadow/blur from dropped decorative layers so frosted
    # chips/buttons/backgrounds keep their material signal for codegen.
    _fx = absorbed_effects(node)
    if "glass" in _fx: result["material"] = "glass"
    _eff = [h for h in ("blur", "shadow") if h in _fx]
    if _eff: result["effect"] = "+".join(_eff)

    # TEXT node
    if ntype == "TEXT":
        chars = node.get("characters", "")
        style = node.get("style", {})
        fs = style.get("fontSize")
        fw = style.get("fontWeight")
        tc = text_color(node)
        align_h = style.get("textAlignHorizontal", "LEFT")

        result["text"] = chars[:60] + ("…" if len(chars) > 60 else "")
        if fs: result["fontSize"] = round(fs, 1) if fs != int(fs) else int(fs)

        # Use text content as name when node name is generic
        if name in ("Title", "Label", "Description", "Tab Tittle", "Time"):
            result["name"] = chars[:30]
        if fw: result["fontWeight"] = fw
        ff = style.get("fontFamily")
        if ff: result["fontFamily"] = ff
        if tc: result["color"] = tc
        if align_h != "LEFT": result["textAlign"] = align_h

        # ── Extended typography — only when field exists AND differs from default ──

        # letterSpacing: 0 = default → skip
        ls = style.get("letterSpacing")
        if ls is not None and ls != 0:
            result["letterSpacing"] = round(ls, 2)

        # lineHeight: only output when unit is explicit px/percent-fixed, not AUTO
        lh_unit = style.get("lineHeightUnit")   # "PIXELS", "PERCENT", "AUTO"
        lh_px   = style.get("lineHeightPx")
        # Skip when AUTO (no override) or when PERCENT at 100% (pure default)
        if lh_unit == "PIXELS" and lh_px:
            result["lineHeightPx"] = round(lh_px, 1)
        elif lh_unit == "PERCENT":
            lh_pct = style.get("lineHeightPercentFontSize") or style.get("lineHeightPercent")
            if lh_pct is not None and abs(lh_pct - 100) > 1:   # 100% = default, skip
                result["lineHeightPct"] = round(lh_pct)

        # italic: False = default → skip
        if style.get("italic") is True:
            result["fontStyle"] = "italic"

        # textDecoration: NONE = default → skip
        td = style.get("textDecoration")
        if td and td != "NONE":
            result["textDecoration"] = td.lower()   # "underline" / "strikethrough"

        # textCase: ORIGINAL = default → skip
        tc_val = style.get("textCase")
        if tc_val and tc_val != "ORIGINAL":
            result["textCase"] = tc_val.lower()     # "upper" / "lower" / "title"

        # paragraphSpacing: 0 = default → skip
        ps = style.get("paragraphSpacing")
        if ps:
            result["paragraphSpacing"] = round(ps)

        # Max lines: the designer's value wins; else estimate from the box height
        if node.get("maxLines"):
            result["maxLines"] = int(node["maxLines"])
        elif fs and bh:
            ml = estimate_max_lines(bh, fs)
            if ml > 1: result["maxLines"] = ml
        if style.get("textTruncation") == "ENDING": result["ellipsis"] = True
        tav = style.get("textAlignVertical")
        if tav and tav != "TOP": result["vAlign"] = tav.lower()
        tar = style.get("textAutoResize")
        if tar and tar != "WIDTH_AND_HEIGHT":
            result["autoSize"] = "height" if tar == "HEIGHT" else ("truncate" if tar == "TRUNCATE" else "fixed")

        result["_box"] = nbox
        stats.kept += 1
        return result

    # ── Recurse children ──
    raw_children = node.get("children", [])
    parsed_children = []
    for child in raw_children:
        parsed = scan(child, viewport, nbox, depth + 1)
        if parsed:
            parsed_children.append(parsed)

    # ── Post-filter: prune empty containers ──
    if ntype in ("FRAME", "GROUP", "SLOT", "INSTANCE") and depth > 0:
        has_vis = fill or result.get("opacity") or cr
        if not parsed_children and not has_vis:
            stats.empty += 1; return None

    # ── Collapse single-child wrappers (v5.4: only when the wrapper adds no padding — measured 346 padded wrappers
    #    per 70 screens whose padding vanished with the collapse, e.g. a toolbar slot with paddingLeft/Right 16) ──
    if ntype in ("FRAME", "GROUP", "SLOT") and depth > 0:
        if len(parsed_children) == 1 and not fill and not cr and not result.get("opacity"):
            child = parsed_children[0]
            icon_box = child.get("type") == "ICON" and bw <= 96 and bh <= 96   # 24×24 frame around a 20×18 glyph: still the glyph (P1 sizes icons by their box)
            if icon_box or not wrapper_padding(node, nbox, child.get("_box")):
                if not child.get("_box"):
                    child["_box"] = nbox
                stats.empty += 1
                return child

    # ── Compute layout from children positions ──
    if parsed_children:
        child_boxes = [c.get("_box", {}) for c in parsed_children]
        valid_boxes = [b for c, b in zip(parsed_children, child_boxes) if b.get("w") and not c.get("absolute")]

        if valid_boxes and len(valid_boxes) >= 2:
            direction = compute_direction(valid_boxes)
            result["layout"] = direction

            if direction in ("ROW", "COLUMN"):
                child_types = [c.get("type","") for c in parsed_children]
                gaps = compute_gaps(valid_boxes, direction, child_types)
                positive_gaps = [g for g in gaps if g >= 0]

                # Space-between: one dominant gap + last child flush to the far edge
                # => a flexible spacer (use weight()/SpaceBetween, NOT the literal px,
                # which only holds for this sample text length).
                space_between = False
                if direction == "ROW" and len(positive_gaps) >= 1:
                    mx = max(positive_gaps)
                    others = [g for g in positive_gaps if g != mx] or [0]
                    last = valid_boxes[-1]
                    edge_slack = max(16, nbox["w"] * 0.05)
                    flush_end = (nbox["x"] + nbox["w"]) - (last["x"] + last["w"]) <= edge_slack
                    if mx >= 40 and mx >= 2 * (max(others) + 1) and flush_end:
                        space_between = True

                if space_between:
                    result["arrangement"] = "SPACE_BETWEEN"
                    small = [g for g in positive_gaps if g != max(positive_gaps)]
                    if small and any(g > 0 for g in small):
                        result["gap"] = small[0] if len(set(small)) == 1 else small
                elif positive_gaps:
                    if len(set(positive_gaps)) == 1:
                        result["gap"] = positive_gaps[0]
                    else:
                        result["gap"] = positive_gaps

                # Padding
                padding = compute_padding(nbox, valid_boxes)
                if padding and any(v > 0 for v in padding.values()):
                    # Simplify: if all same
                    vals = list(padding.values())
                    if len(set(vals)) == 1 and vals[0] > 0:
                        result["padding"] = vals[0]
                    else:
                        result["padding"] = {k:v for k,v in padding.items() if v > 0}

                # Alignment
                align = compute_alignment(valid_boxes, nbox, direction)
                if align: result["crossAlign"] = align

                # Scrollable
                scroll = detect_scrollable(nbox, valid_boxes, direction)
                if scroll: result["scrollable"] = scroll

        elif valid_boxes and len(valid_boxes) == 1:
            result["layout"] = "SINGLE"
            pad = wrapper_padding(node, nbox, valid_boxes[0], explicit_only=False)
            if pad:
                vals = list(pad.values())
                result["padding"] = vals[0] if len(pad) == 4 and len(set(vals)) == 1 else pad

        # v5.2: infer FILL sizing when the source has no layoutGrow/layoutAlign (explicit block above wins)
        # ── Explicit auto-layout (clipboard/REST source): designer values beat inference ──
        lm = node.get("layoutMode")
        if lm in ("HORIZONTAL", "VERTICAL"):
            direction = "ROW" if lm == "HORIZONTAL" else "COLUMN"
            result["layout"] = direction
            result["_layoutSource"] = "explicit"
            result.pop("arrangement", None)
            gap = node.get("itemSpacing")
            if node.get("primaryAxisAlignItems") == "SPACE_BETWEEN":
                result["arrangement"] = "SPACE_BETWEEN"; result.pop("gap", None)   # Figma ignores itemSpacing here
            elif gap is not None and gap > 0: result["gap"] = round(gap) if float(gap).is_integer() else round(gap, 1)
            else: result.pop("gap", None)
            pad = {k: node.get(f, 0) or 0 for k, f in (("top", "paddingTop"), ("left", "paddingLeft"), ("right", "paddingRight"), ("bottom", "paddingBottom"))}
            pad = {k: (round(v) if float(v).is_integer() else round(v, 1)) for k, v in pad.items() if v > 0}
            if pad:
                vals = list(pad.values())
                result["padding"] = vals[0] if len(pad) == 4 and len(set(vals)) == 1 else pad
            else: result.pop("padding", None)
            ca = node.get("counterAxisAlignItems")
            align_map = {"MIN": "start", "CENTER": "center", "MAX": "end", "BASELINE": "baseline"}
            if ca in align_map: result["crossAlign"] = align_map[ca]
            elif ca is None: result.pop("crossAlign", None)
            if node.get("layoutWrap") == "WRAP": result["wrap"] = True
            # child sizing: layoutGrow along primary axis, layoutAlign=STRETCH across
            for c in parsed_children:
                if not c.get("absolute"): c.pop("constraints", None)   # Figma ignores constraints for flow children
                if c.get("_layoutGrow"):
                    c["fillW" if direction == "ROW" else "fillH"] = True
                if c.get("_layoutAlign") == "STRETCH":
                    c["fillH" if direction == "ROW" else "fillW"] = True
        elif lm == "NONE" and len(parsed_children) >= 2 and result.get("layout") in ("ROW", "COLUMN"):
            result["_layoutSource"] = "inferred(no-autolayout)"
        mark_fill_sizing(parsed_children, nbox)

        result["children"] = parsed_children

    kind = layer_kind(name)
    if kind and result.get("children") and result.get("fill"):
        result[kind] = result.pop("fill")   # v5.4: Overlay/Scrim dim and State-layer tint are not backgrounds

    result["_box"] = nbox
    stats.kept += 1
    return result

def mark_fill_sizing(parsed_children, parent_box):
    """v5.2: FILL vs HUG sizing fallback when explicit sizing fields are absent — infer it.
    A child that spans the full union extent of its siblings, with ≤40px total
    slack against the parent box (the slack = parent padding), renders as
    fillMaxWidth()/fillMaxHeight() rather than a fixed px size. TEXT nodes are
    skipped (their width is glyph-driven, not a layout decision)."""
    boxes = [c.get("_box") or {} for c in parsed_children]
    valid = [b for b in boxes if b.get("w")]
    if not valid: return
    min_x = min(b["x"] for b in valid); max_r = max(b["x"] + b["w"] for b in valid)
    min_y = min(b["y"] for b in valid); max_b = max(b["y"] + b["h"] for b in valid)
    pw, ph = parent_box.get("w", 0), parent_box.get("h", 0)
    for c, b in zip(parsed_children, boxes):
        if not b.get("w") or c.get("type") == "TEXT": continue
        if abs(b["x"] - min_x) <= 1 and abs((b["x"] + b["w"]) - max_r) <= 1 and 0 <= pw - b["w"] <= 40:
            c["fillW"] = True
        if abs(b["y"] - min_y) <= 1 and abs((b["y"] + b["h"]) - max_b) <= 1 and 0 <= ph - b["h"] <= 40:
            c["fillH"] = True

# ─── Context Output Generator ────────────────────────────────────────────────

def format_layout_line(node):
    """Format layout info as a compact line."""
    parts = []
    layout = node.get("layout")
    if layout: parts.append(f"layout={layout}")
    arrangement = node.get("arrangement")
    if arrangement: parts.append(f"arrangement={arrangement}")
    gap = node.get("gap")
    if gap is not None: parts.append(f"gap={gap}")
    padding = node.get("padding")
    if padding:
        if isinstance(padding, dict):
            p_str = " ".join(f"{k}={v}" for k,v in padding.items())
            parts.append(f"padding=({p_str})")
        else:
            parts.append(f"padding={padding}")
    align = node.get("crossAlign")
    if align: parts.append(f"align={align}")
    scroll = node.get("scrollable")
    if scroll: parts.append(f"scroll={scroll}")
    cons = node.get("constraints")
    if cons: parts.append(f"constraints=({cons})")
    for k in ("minW", "minH", "maxW", "maxH"):
        if node.get(k) is not None: parts.append(f"{k}={node[k]}")
    return ", ".join(parts)

def generate_context(node, indent=0, parent_box=None):
    """Generate structured text evidence for blueprint extraction."""
    lines = []
    pre = "  " * indent
    ntype = node.get("type", "")
    name = node.get("name", "")
    size = node.get("size", "")
    fill = node.get("fill")
    radius = node.get("radius")
    opacity = node.get("opacity")
    children = node.get("children", [])
    nbox = node.get("_box", {})

    # ── Header line ──
    sizing = [t for t, k in (("w=fill", "fillW"), ("h=fill", "fillH")) if node.get(k)]
    size_str = f"{size}, {', '.join(sizing)}" if sizing else size
    header_parts = [f'{pre}{ntype} "{name}" ({size_str})']

    if fill: header_parts.append(f"fill={fill}")
    for k in ("scrim", "stateLayer"):
        if node.get(k): header_parts.append(f"{k}={node[k]}")
    if radius: header_parts.append(f"r={radius}")
    if opacity: header_parts.append(f"opacity={opacity}")
    material = node.get("material")
    if material: header_parts.append(f"material={material}")
    effect = node.get("effect")
    if effect: header_parts.append(f"effect={effect}")
    stroke = node.get("stroke")
    if stroke: header_parts.append(f"stroke={stroke}")
    shadow = node.get("shadow")
    if shadow: header_parts.append(f"shadow={shadow}")
    blur_r = node.get("blurRadius")
    if blur_r is not None: header_parts.append(f"blur={blur_r}")
    overflow = node.get("overflow")
    if overflow: header_parts.append(f"overflow={overflow}")
    inner = node.get("innerShadow")
    if inner: header_parts.append(f"innerShadow={inner}")
    blend = node.get("blend")
    if blend: header_parts.append(f"blend={blend}")
    rot = node.get("rotation")
    if rot: header_parts.append(f"rotation={rot}°")
    mask = node.get("mask")
    if mask: header_parts.append(f"mask={mask}")
    if node.get("absolute"): header_parts.append("absolute")
    modes = node.get("modes")
    if modes: header_parts.append(f"mode={modes}")

    lines.append(" | ".join(header_parts))

    # ── Layout line ──
    layout_str = format_layout_line(node)
    if layout_str:
        lines.append(f"{pre}  {layout_str}")

    # ── Prototype interactions (navigation evidence, not UI) ──
    for it in node.get("interactions") or []:
        lines.append(f"{pre}  → {it}")

    # ── TEXT content ──
    if ntype == "TEXT":
        text = node.get("text", "")
        fs = node.get("fontSize")
        fw = node.get("fontWeight")
        color = node.get("color")
        ta = node.get("textAlign")
        ml = node.get("maxLines")

        text_parts = [f'text="{text}"']
        if fs: text_parts.append(f"size={fs}")
        if fw: text_parts.append(f"weight={fw}")
        ff = node.get("fontFamily")
        if ff: text_parts.append(f"font={ff}")
        if color: text_parts.append(f"color={color}")
        if ta: text_parts.append(f"align={ta}")
        if ml and ml > 1: text_parts.append(f"maxLines={ml}")
        # Extended typography (only present when non-default)
        ls = node.get("letterSpacing")
        if ls is not None: text_parts.append(f"letterSpacing={ls}")
        lh_px = node.get("lineHeightPx")
        if lh_px is not None: text_parts.append(f"lineHeight={lh_px}")
        lh_pct = node.get("lineHeightPct")
        if lh_pct is not None: text_parts.append(f"lineHeight={lh_pct}%")
        fi = node.get("fontStyle")
        if fi: text_parts.append(f"fontStyle={fi}")
        td = node.get("textDecoration")
        if td: text_parts.append(f"textDecoration={td}")
        tc = node.get("textCase")
        if tc: text_parts.append(f"textCase={tc}")
        if node.get("ellipsis"): text_parts.append("overflow=ellipsis")
        va = node.get("vAlign")
        if va: text_parts.append(f"vAlign={va}")
        asz = node.get("autoSize")
        if asz: text_parts.append(f"autoSize={asz}")
        lines.append(f"{pre}  {', '.join(text_parts)}")
        return lines

    # ── IMAGE marker ──
    if fill == "[IMAGE]" and ntype == "RECTANGLE":
        ar = round(nbox.get("w",1) / max(nbox.get("h",1), 1), 2)
        lines.append(f"{pre}  [IMAGE placeholder] aspectRatio={ar}")

    # ── Overlay position for small children ──
    if parent_box and nbox and ntype not in ("TEXT",):
        pw, ph = parent_box.get("w",0), parent_box.get("h",0)
        cw, ch = nbox.get("w",0), nbox.get("h",0)
        if pw > 0 and ph > 0 and (node.get("absolute") or (cw < pw * 0.5 and ch < ph * 0.5)):
            pos = compute_overlay_position(nbox, parent_box)
            if pos and (pos["position"] != "top-left" or node.get("absolute")):
                lines.append(f'{pre}  position={pos["position"]} offset=({pos["offsetX"]}, {pos["offsetY"]})')

    # ── Recurse children ──
    for child in children:
        lines.extend(generate_context(child, indent + 1, nbox))

    return lines

# ─── Summary Tree ────────────────────────────────────────────────────────────

def generate_summary(node, indent=0, is_last=True, prefix=""):
    lines = []
    ntype = node.get("type", "")
    name = node.get("name", "")
    size = node.get("size", "")

    connector = "" if indent == 0 else ("└─ " if is_last else "├─ ")
    child_prefix = prefix + ("   " if is_last else "│  ") if indent > 0 else ""

    parts = [f'{ntype} "{name}" {size}']
    if node.get("fillW"): parts.append("w=fill")
    if node.get("fillH"): parts.append("h=fill")
    fill = node.get("fill")
    if fill: parts.append(f"fill={fill}")
    layout = node.get("layout")
    if layout: parts.append(f"layout={layout}")
    arrangement = node.get("arrangement")
    if arrangement: parts.append(f"arrangement={arrangement}")
    gap = node.get("gap")
    if gap is not None: parts.append(f"gap={gap}")
    scroll = node.get("scrollable")
    if scroll: parts.append(f"scroll={scroll}")
    radius = node.get("radius")
    if radius: parts.append(f"r={radius}")
    material = node.get("material")
    if material: parts.append(f"material={material}")
    effect = node.get("effect")
    if effect: parts.append(f"effect={effect}")
    if node.get("mask"): parts.append(f"mask={node['mask']}")
    if node.get("absolute"): parts.append("absolute")
    navs = [i for i in (node.get("interactions") or []) if "NAVIGATE" in i or "OVERLAY" in i or "BACK" in i or "URL" in i]
    if navs: parts.append("→ " + navs[0].split(" ", 1)[1])

    if ntype == "TEXT":
        text = node.get("text","")[:40]
        fs = node.get("fontSize")
        fw = node.get("fontWeight")
        color = node.get("color")
        parts = [f'TEXT "{text}" {fs}px w{fw} {color}']

    lines.append(f"{prefix}{connector}{' | '.join(parts)}")

    children = node.get("children", [])
    for i, child in enumerate(children):
        lines.extend(generate_summary(child, indent+1, i == len(children)-1, child_prefix))

    return lines

# ─── Split-Screens Detection (v4.0) ──────────────────────────────────────────

SCREEN_WIDTH_RANGE = (380, 480)   # mobile screen width tolerance
SCREEN_HEIGHT_RANGE = (700, 1000) # mobile screen height tolerance

def is_screen_like(node):
    """Check if a node looks like an individual phone screen."""
    bb = node.get("absoluteBoundingBox", {})
    w = bb.get("width", 0)
    h = bb.get("height", 0)
    if SCREEN_WIDTH_RANGE[0] <= w <= SCREEN_WIDTH_RANGE[1] and \
       SCREEN_HEIGHT_RANGE[0] <= h <= SCREEN_HEIGHT_RANGE[1]:
        return True
    return False

def detect_sub_screens(root_node):
    """Find children (depth 1-2) that look like individual phone screens.
    Returns list of (name, node) tuples."""
    screens = []
    for child in root_node.get("children", []):
        if is_screen_like(child):
            screens.append((child.get("name", "Screen"), child))
        else:
            # Check depth 2
            for grandchild in child.get("children", []):
                if is_screen_like(grandchild):
                    screens.append((grandchild.get("name", "Screen"), grandchild))
    return screens

def _slugify(name):
    """Convert screen name to folder-safe snake_case.
    Handles Vietnamese/Unicode by transliterating to ASCII."""
    import unicodedata
    # NFD decompose + strip combining marks → ASCII approximation
    nfkd = unicodedata.normalize('NFKD', name)
    ascii_str = nfkd.encode('ascii', 'ignore').decode('ascii')
    # Replace special chars with underscore
    s = re.sub(r'[^a-zA-Z0-9\s_-]', '', ascii_str)
    s = re.sub(r'[\s-]+', '_', s).lower().strip('_')
    return s or 'screen'

def generate_index_md(screens_info, feature_dir):
    """Generate index.md listing all sub-screens and their paths."""
    lines = [f"# Scan Index — {os.path.basename(feature_dir)}\n"]
    lines.append(f"> {len(screens_info)} sub-screens detected\n")
    lines.append("| Folder | Original Figma name | node-id | Case description | Status |")
    lines.append("|---|---|---|---|---|")
    for info in screens_info:
        lines.append(
            f"| `screens/{info['folder']}/` | {info['name']} | {info.get('nodeId', '')} "
            f"| pending semantic curation | active |"
        )
    lines.append("")
    return "\n".join(lines)


# ─── Design Token Aggregator (font-authority · spacing · border-alpha) ────────

def collect_tokens(node, acc=None):
    """Walk the parsed tree and aggregate design tokens into a consolidated
    golden reference. Accepts a shared `acc` so callers can accumulate across
    multiple screens (e.g. split-screens → one repo-wide token table)."""
    if acc is None:
        acc = {
            "fonts": Counter(), "text_styles": Counter(), "text_sample": {},
            "fills": Counter(), "borders": Counter(),
            "radii": Counter(), "gaps": Counter(), "paddings": Counter(),
        }
    if not isinstance(node, dict):   # v5.4: scan() may return None (root clip hidden/decorative) — never crash the token pass
        return acc
    ntype = node.get("type", "")

    if ntype == "TEXT":
        ff = node.get("fontFamily") or "?"
        fs = node.get("fontSize")
        fw = node.get("fontWeight")
        col = node.get("color") or "?"
        acc["fonts"][ff] += 1
        key = (fs, fw, ff, col)
        acc["text_styles"][key] += 1
        acc["text_sample"].setdefault(key, (node.get("text", "") or "")[:24])

    # Fill colors — only solid (skip images/gradients) → overlay/surface tokens
    fill = node.get("fill")
    if fill and fill != "[IMAGE]" and not str(fill).startswith("[GRADIENT"):
        acc["fills"][fill] += 1

    stroke = node.get("stroke")          # e.g. "#ffffff (12%) 1px inside"
    if stroke:
        acc["borders"][stroke] += 1

    radius = node.get("radius")
    if radius is not None and radius != 0:
        acc["radii"][str(radius)] += 1

    gap = node.get("gap")
    if gap is not None:
        acc["gaps"][str(gap)] += 1

    padding = node.get("padding")
    if padding:
        if isinstance(padding, dict):
            pstr = " ".join(f"{k}={v}" for k, v in padding.items())
        else:
            pstr = str(padding)
        acc["paddings"][pstr] += 1

    for c in node.get("children", []):
        collect_tokens(c, acc)
    return acc


def render_tokens(acc):
    """Format an aggregated token acc as a consolidated golden reference."""
    L = ["# DESIGN TOKENS — auto-aggregated golden (verify code ↔ figma)", ""]

    L.append("## FONTS (font-authority)")
    for ff, n in acc["fonts"].most_common():
        L.append(f"  {ff}  ×{n}")
    if len(acc["fonts"]) > 1:
        L.append("  ⚠️ nhiều font xuất hiện — chốt font canonical trước khi verify")
    L.append("")

    L.append("## TEXT STYLES  (size / weight / color / font)")
    for (fs, fw, ff, col), n in acc["text_styles"].most_common():
        sample = acc["text_sample"].get((fs, fw, ff, col), "")
        L.append(f'  {fs}sp / w{fw} / {col} / {ff}  ×{n}   e.g. "{sample}"')
    L.append("")

    L.append("## FILLS / OVERLAY colors")
    for c, n in acc["fills"].most_common():
        L.append(f"  {c}  ×{n}")
    L.append("")

    L.append("## BORDERS (border-alpha element)")
    if acc["borders"]:
        for b, n in acc["borders"].most_common():
            L.append(f"  {b}  ×{n}")
    else:
        L.append("  (none captured)")
    L.append("")

    L.append("## RADII")
    for r, n in acc["radii"].most_common():
        L.append(f"  r={r}  ×{n}")
    L.append("")

    L.append("## SPACING — gaps")
    for g, n in acc["gaps"].most_common():
        L.append(f"  gap={g}  ×{n}")
    L.append("")

    L.append("## SPACING — paddings")
    for p, n in acc["paddings"].most_common():
        L.append(f"  padding=({p})  ×{n}")

    return "\n".join(L)


def generate_tokens(node):
    """Convenience: aggregate + render tokens for a single parsed tree (None → empty golden, no crash)."""
    return render_tokens(collect_tokens(node if isinstance(node, dict) else {}))


# ─── Main ─────────────────────────────────────────────────────────────────────

def write_icons_json(tree, ctx_path):
    """icons.json next to context.txt — every node the context flattened to ICON (id · name · size).
    Single source of "icons the evidence needs" for `figclip icons` (SVGs are composed only for these ids)."""
    icons = []
    def collect(n):
        if n.get("type") == "ICON" and n.get("_id"):
            icons.append({"id": n["_id"], "name": n.get("name", ""), "size": n.get("size", "")})
        for c in n.get("children", []): collect(c)
    collect(tree)
    with open(os.path.join(os.path.dirname(ctx_path), "icons.json"), "w", encoding="utf-8") as f:
        json.dump(icons, f, ensure_ascii=False, indent=1)

def main():
    global VIEWPORT_MARGIN, stats

    parser = argparse.ArgumentParser(
        description="Figma Deep Scanner v5.2 — Blueprint Evidence Generator"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {SCRIPT_VERSION}")
    parser.add_argument("filepath", help="Path to raw Figma node JSON file")
    parser.add_argument("--context", action="store_true", help="Output structured AI context (recommended)")
    parser.add_argument("--tokens", action="store_true", help="Output aggregated design-token golden (fonts/spacing/borders/radii). Combinable with --context.")
    parser.add_argument("--summary", action="store_true", help="Output tree outline")
    parser.add_argument("--compact", action="store_true", help="Compact JSON mode")
    parser.add_argument("--keep-decorative", action="store_true", help="Keep glass/blur layers")
    parser.add_argument("--margin", type=int, default=VIEWPORT_MARGIN, help="Viewport margin px")
    parser.add_argument("--exclude", nargs="*", default=[], help="Node names to exclude (e.g. 'Status Bar' 'Bottom Bar')")
    parser.add_argument("--split-screens", action="store_true",
                        help="Auto-detect sub-screens in large scope and split output into subfolders")
    parser.add_argument("--out-dir", "-o", default=None,
                        help="Feature directory in split mode; screen directory in single mode "
                             "(default: same directory as input file)")
    args = parser.parse_args()

    if not os.path.exists(args.filepath):
        print(f"Error: {args.filepath} not found."); sys.exit(1)

    with open(args.filepath, 'r', encoding='utf-8') as f:
        source_data = json.load(f)
    data = copy.deepcopy(source_data)

    # Viewport
    rb = data.get("absoluteBoundingBox", {})
    vx, vy = rb.get("x", 0), rb.get("y", 0)
    vw, vh = rb.get("width", 430), rb.get("height", 925)
    viewport = (vx, vy, vw, vh)

    # Exclude nodes — recursive (drops matches at any depth via scan()); the top-level
    # pruning here stays as a cheap fast-path.
    if args.exclude:
        exclude_set = set(n.lower() for n in args.exclude)
        EXCLUDE_NAMES.update(exclude_set)
        orig_children = data.get("children", [])
        data["children"] = [c for c in orig_children if c.get("name","").lower() not in exclude_set]

    # Override decorative filter
    if args.keep_decorative:
        DECORATIVE_NAMES.clear()
        INTERNAL_KEYWORDS.clear()

    VIEWPORT_MARGIN = args.margin

    # Resolve output directory
    if args.out_dir:
        out_dir = args.out_dir
    else:
        out_dir = os.path.dirname(os.path.abspath(args.filepath))

    print(f"╔══════════════════════════════════════════════════╗")
    print(f"║  Figma Deep Scanner v5.2 — Blueprint Evidence    ║")
    print(f"╠══════════════════════════════════════════════════╣")
    print(f"║  Root: {data.get('name', 'Unknown'):42s}║")
    print(f"║  Size: {vw:.0f} × {vh:.0f}                               ║")
    print(f"╚══════════════════════════════════════════════════╝")

    # ── Split-screens mode ──
    if args.split_screens:
        sub_screens = detect_sub_screens(data)
        if len(sub_screens) < 2:
            print(f"  ⚠️  Only {len(sub_screens)} screen-like child found. Falling back to single scan.")
            args.split_screens = False
        else:
            print(f"  📱 Detected {len(sub_screens)} sub-screens:")
            for name, _ in sub_screens:
                print(f"     • {name}")
            print()

    if args.split_screens:
        # ── Multi-screen scan ──
        screens_info = []
        layout = FeatureLayout.from_feature(out_dir)
        layout.ensure()
        feature_dir = str(layout.feature_dir)
        scan_dir = str(layout.scan_dir)
        screens_dir = str(layout.screens_dir)
        global_tok = collect_tokens({})   # accumulate tokens across all sub-screens

        # Deduplicate folder slugs
        slug_counter = defaultdict(int)

        for screen_name, screen_node in sub_screens:
            slug = _slugify(screen_name)
            slug_counter[slug] += 1
            if slug_counter[slug] > 1:
                slug = f"{slug}_{slug_counter[slug]}"
            screen_dir = os.path.join(screens_dir, slug)
            os.makedirs(screen_dir, exist_ok=True)

            # Reset stats for each sub-screen
            stats = Stats()

            # Sub-screen viewport
            sbb = screen_node.get("absoluteBoundingBox", {})
            sv = (sbb.get("x",0), sbb.get("y",0), sbb.get("width",430), sbb.get("height",925))

            # Apply exclude to sub-screen (recursive via scan(); top-level fast-path here)
            if args.exclude:
                exclude_set = set(n.lower() for n in args.exclude)
                EXCLUDE_NAMES.update(exclude_set)
                orig = screen_node.get("children", [])
                screen_node["children"] = [c for c in orig if c.get("name","").lower() not in exclude_set]

            tree = scan(screen_node, sv)

            # Save raw.json for sub-screen
            raw_path = os.path.join(screen_dir, "raw.json")
            with open(raw_path, 'w', encoding='utf-8') as f:
                json.dump(screen_node, f, indent=2, ensure_ascii=False)

            if args.context or (not args.summary):
                lines = generate_context(tree)
                text = "\n".join(lines)
                ctx_path = os.path.join(screen_dir, "context.txt")
                with open(ctx_path, 'w', encoding='utf-8') as f:
                    f.write(text)
                write_icons_json(tree, ctx_path)

            # Summary is a canonical per-screen artifact in split mode.
            lines = generate_summary(tree)
            text = "\n".join(lines)
            sum_path = os.path.join(screen_dir, "summary.txt")
            with open(sum_path, 'w', encoding='utf-8') as f:
                f.write(text)

            # Design tokens: per-screen file + accumulate into global golden
            collect_tokens(tree, global_tok)
            with open(os.path.join(screen_dir, "tokens.txt"), 'w', encoding='utf-8') as f:
                f.write(generate_tokens(tree))

            node_id = screen_node.get("id", "")
            info = {
                "name": screen_name,
                "folder": slug,
                "nodes": f"{stats.raw} raw → {stats.kept} kept",
                "icons": stats.icons,
                "nodeId": node_id
            }
            screens_info.append(info)
            print(f"  ✅ {screen_name} → {slug}/  ({stats.kept} nodes, {stats.icons} icons)")

        # Root aggregate design-token golden (across all sub-screens)
        with open(os.path.join(scan_dir, "DESIGN_TOKENS.txt"), 'w', encoding='utf-8') as f:
            f.write(render_tokens(global_tok))
        print(f"  🎨 Design tokens: {os.path.join(scan_dir, 'DESIGN_TOKENS.txt')}")

        # Generate index.md
        index_content = generate_index_md(screens_info, feature_dir)
        index_path = os.path.join(scan_dir, "index.md")
        with open(index_path, 'w', encoding='utf-8') as f:
            f.write(index_content)

        print(f"\n{'─'*50}")
        print(f"  📁 Feature output: {feature_dir}/")
        print(f"  📋 Index: {index_path}")
        print(f"  📱 Screens: {len(screens_info)}")
        for info in screens_info:
            print(f"     screens/{info['folder']}/  ({info['nodes']})")
        return

    # ── Single scan (original behavior) ──
    tree = scan(data, viewport)

    # Clean _box from output (internal use only) for JSON mode
    def strip_internal(node):
        if not node: return
        node.pop("_box", None)
        for c in node.get("children", []):
            strip_internal(c)

    os.makedirs(out_dir, exist_ok=True)
    if args.out_dir:
        with open(os.path.join(out_dir, "raw.json"), "w", encoding="utf-8") as f:
            json.dump(source_data, f, indent=2, ensure_ascii=False)

    if args.context:
        # ── Blueprint evidence output ──
        lines = generate_context(tree)
        text = "\n".join(lines)

        outpath = (
            os.path.join(out_dir, "context.txt")
            if args.out_dir
            else args.filepath.rsplit(".", 1)[0] + "_context.txt"
        )
        with open(outpath, 'w', encoding='utf-8') as f:
            f.write(text)
        write_icons_json(tree, outpath)

        print(f"\n{text}")
        print(f"\n{'─'*50}")
        print(f"  Nodes: {stats.raw} raw → {stats.kept} kept")
        print(f"  Removed: {stats.off} off-screen, {stats.hid} hidden, {stats.deco} decorative, {stats.empty} empty/collapsed")
        print(f"  Icons: {stats.icons} flattened")
        print(f"  Context saved to: {outpath}")

        if args.tokens:
            tok = generate_tokens(tree)
            tok_path = (
                os.path.join(out_dir, "tokens.txt")
                if args.out_dir
                else args.filepath.rsplit(".", 1)[0] + "_tokens.txt"
            )
            with open(tok_path, 'w', encoding='utf-8') as f:
                f.write(tok)
            print(f"  Tokens saved to: {tok_path}")

    elif args.summary:
        lines = generate_summary(tree)
        text = "\n".join(lines)
        outpath = (
            os.path.join(out_dir, "summary.txt")
            if args.out_dir
            else args.filepath.rsplit(".", 1)[0] + "_summary.txt"
        )
        with open(outpath, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f"\n{text}")
        print(f"\n{'─'*50}")
        print(f"  Saved to: {outpath}")

    elif args.tokens:
        tok = generate_tokens(tree)
        outpath = (
            os.path.join(out_dir, "tokens.txt")
            if args.out_dir
            else args.filepath.rsplit(".", 1)[0] + "_tokens.txt"
        )
        with open(outpath, 'w', encoding='utf-8') as f:
            f.write(tok)
        print(f"\n{tok}")
        print(f"\n{'─'*50}")
        print(f"  Tokens saved to: {outpath}")

    else:
        # ── JSON output ──
        strip_internal(tree)
        output = {
            "_meta": {
                "source": os.path.basename(args.filepath),
                "rootName": data.get("name", ""),
                "viewport": {"w": vw, "h": vh},
                "stats": {
                    "raw": stats.raw, "kept": stats.kept,
                    "offscreen": stats.off, "hidden": stats.hid,
                    "decorative": stats.deco, "empty": stats.empty,
                    "icons": stats.icons
                }
            },
            "tree": tree
        }

        suffix = "_deep_scan_compact.json" if args.compact else "_deep_scan.json"
        base = args.filepath.rsplit(".",1)[0]
        for old in ["_deep_scan_compact", "_deep_scan"]:
            if base.endswith(old): base = base[:-len(old)]
        outpath = os.path.join(out_dir, suffix.lstrip("_")) if args.out_dir else base + suffix

        with open(outpath, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        outsize = os.path.getsize(outpath)
        insize = os.path.getsize(args.filepath)

        print(f"\n{'─'*50}")
        print(f"  Nodes: {stats.raw} raw → {stats.kept} kept")
        print(f"  Removed: {stats.off} off-screen, {stats.hid} hidden, {stats.deco} decorative, {stats.empty} empty/collapsed")
        print(f"  Icons: {stats.icons} flattened")
        print(f"  Size: {insize:,} → {outsize:,} bytes ({outsize/insize*100:.0f}%)")
        print(f"  Saved to: {outpath}")

if __name__ == "__main__":
    main()
