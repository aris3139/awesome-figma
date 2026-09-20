#!/usr/bin/env python3
"""regress.py — rescan every screen of a feature from its saved clipboard payload and compare with the context.txt on
disk. Read-only for the feature: everything is written under --out. Prints one row per screen plus the metrics the
scanner tracks:

  overlay_text_missing  TEXT under an Overlay/Scrim node in raw.json that the new context.txt does not contain
  icon_over_96          ICON lines wider or taller than 96 px (over-flattened containers / shell instances)
  lines_added/removed   line diff new vs on-disk context.txt (0/0 = byte-identical evidence)

usage: regress.py [--feature DIR] [--clip FILE] [--out DIR] [--only name,name] [--json]
defaults: feature = ~/.config/awesome-figma/last_dir, clip = manifest.clip, out = <tmp>/awesome-figma-regress
"""
from __future__ import annotations

import argparse, json, os, re, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCANNER = HERE / "figma_deep_scan.py"
MAPPER = HERE / "figclip" / "kiwi_to_rest.mjs"
EXCLUDE = ["Status Bar", "Bottom Bar", "Scroll Edge Effect"]
ICON_RE = re.compile(r'ICON "[^"]*" \((\d+)×(\d+)')


def overlay_texts(raw) -> list[str]:
    """Characters of every TEXT under a node named overlay/scrim (what II.3 used to drop)."""
    out: list[str] = []

    def texts(n):
        if not isinstance(n, dict): return
        if n.get("type") == "TEXT" and (n.get("characters") or "").strip():
            out.append(n["characters"].strip()[:40])
        for c in n.get("children") or []: texts(c)

    def walk(n):
        if not isinstance(n, dict): return
        if (n.get("name") or "").lower() in ("overlay", "scrim"): texts(n)
        else:
            for c in n.get("children") or []: walk(c)

    walk(raw if isinstance(raw, dict) else next((x for x in raw if isinstance(x, dict)), {}))
    return out


def rescan(clip: Path, node_id: str, out: Path) -> str:
    out.mkdir(parents=True, exist_ok=True)
    raw = out / "raw.json"
    subprocess.run(["node", str(MAPPER), str(clip), node_id, str(raw)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run([sys.executable, str(SCANNER), "--context", "--tokens", "--exclude", *EXCLUDE, "-o", str(out), "--", str(raw)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return (out / "context.txt").read_text(encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--feature"); ap.add_argument("--clip"); ap.add_argument("--out")
    ap.add_argument("--only", help="comma-separated screen folder names"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    last = Path.home() / ".config" / "awesome-figma" / "last_dir"
    if not a.feature and not last.is_file(): sys.exit("regress: pass --feature <dir> (no last scan recorded)")
    feature = Path(a.feature) if a.feature else Path(last.read_text(encoding="utf-8").strip())
    manifest = json.loads((feature / "_scan" / "manifest.json").read_text(encoding="utf-8"))
    clip = Path(a.clip) if a.clip else feature / manifest["clip"]
    out = Path(a.out) if a.out else Path(tempfile.gettempdir()) / "awesome-figma-regress" / feature.name
    only = set(a.only.split(",")) if a.only else None
    rows = []
    for name, s in manifest["screens"].items():
        if only and name not in only: continue
        try:
            new = rescan(clip, s["node_id"], out / name)
        except subprocess.CalledProcessError as e:
            rows.append({"screen": name, "error": f"exit {e.returncode}"}); continue
        old_path = feature / "screens" / name / "context.txt"
        old = old_path.read_text(encoding="utf-8").splitlines() if old_path.exists() else []
        new_lines = new.splitlines()
        raw = json.loads((out / name / "raw.json").read_text(encoding="utf-8"))
        ov = overlay_texts(raw)
        rows.append({
            "screen": name,
            "lines_added": sum(1 for l in new_lines if l not in old),
            "lines_removed": sum(1 for l in old if l not in new_lines),
            "overlay_text_missing": sum(1 for t in ov if t not in new),
            "overlay_text_total": len(ov),
            "icon_over_96": sum(1 for w, h in ICON_RE.findall(new) if int(w) > 96 or int(h) > 96),
        })
    tot = {k: sum(r.get(k, 0) for r in rows) for k in ("lines_added", "lines_removed", "overlay_text_missing", "overlay_text_total", "icon_over_96")}
    tot["screens"] = len(rows); tot["changed"] = sum(1 for r in rows if r.get("lines_added") or r.get("lines_removed"))
    tot["errors"] = sum(1 for r in rows if "error" in r); tot["out"] = str(out)
    if a.json:
        print(json.dumps({"rows": rows, "totals": tot}, ensure_ascii=False, indent=1))
    else:
        print(f"{'screen':42s} {'+':>4s} {'-':>4s} {'ovl_miss':>8s} {'icon>96':>7s}")
        for r in rows:
            if "error" in r: print(f"{r['screen']:42s} ERROR {r['error']}"); continue
            print(f"{r['screen']:42s} {r['lines_added']:4d} {r['lines_removed']:4d} {r['overlay_text_missing']:5d}/{r['overlay_text_total']:<2d} {r['icon_over_96']:7d}")
        print(json.dumps(tot, ensure_ascii=False))
    return 1 if tot["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
