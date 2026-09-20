#!/usr/bin/env python3
"""UI map: one logical screen per cluster, its designed states, navigation edges and missing-state hints.

Runs at the end of `creator` / `update` (after screen_cluster.py) so a reader sees "this screen is really 6 states"
before planning anything. Everything here is INFERRED from
names, variant diffs and text cues — the BA confirms or denies it; nothing is a gate.

Usage:
    python3 ui_map.py <feature-dir> [--dry-run]

Outputs:
    _scan/UI_MAP.md      human/AI readable
    _scan/ui_map.json    the same data for scripts
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

STATE_TOKENS = {
    "empty": "empty", "loading": "loading", "skeleton": "loading", "error": "error", "err": "error",
    "failed": "error", "fail": "error", "invalid": "error", "offline": "network", "network": "network",
    "disabled": "disabled", "success": "success", "done": "success", "connected": "connected",
    "connecting": "connecting", "typing": "typing", "filled": "filled",
    "selected": "selected", "expanded": "expanded", "collapsed": "collapsed", "prompt": "prompt",
    "confirm": "confirm", "listening": "listening", "playing": "playing", "result": "result",
    "results": "result", "default": "default",
}
TEXT_CUES = [
    (re.compile(r"đang tải|loading", re.I), "loading"),
    (re.compile(r"không có |chưa có |trống|no result|nothing", re.I), "empty"),
    (re.compile(r"thử lại|không hợp lệ|thất bại|không thành công|lỗi|failed|error|retry", re.I), "error"),
    (re.compile(r"mất kết nối|không có kết nối|tín hiệu mạng|offline", re.I), "network"),
    (re.compile(r"thành công|đã kết nối|connected", re.I), "success"),
]
LIST_HINT = re.compile(r"_list|history|results|see_all", re.I)
NAV_RE = re.compile(r"→ (\w+) NAVIGATE (?:\"([^\"]+)\"|node (\S+))")
TEXT_RE = re.compile(r'text="([^"]*)"')
CLICK_RE = re.compile(r"→ ON_CLICK")
VERSION_RE = re.compile(r"^v\d+$")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def parse_index(feature: Path) -> dict[str, dict]:
    """`| Folder | Original Figma name | node-id | Cluster | Case description | Status |` rows → per folder."""
    rows: dict[str, dict] = {}
    for line in _read(feature / "_scan" / "index.md").splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or cells[0] in ("Folder", ""):
            continue
        rows[cells[0]] = {"figma_name": cells[1], "node_id": cells[2], "case": cells[4]}
    return rows


def states_from_name(folder: str) -> list[str]:
    states: list[str] = []
    for token in folder.lower().split("_"):
        if VERSION_RE.match(token):
            states.append(f"variant {token}")
        elif token in STATE_TOKENS and STATE_TOKENS[token] not in states:
            states.append(STATE_TOKENS[token])
    return states


def states_from_text(context: str) -> list[str]:
    texts = " | ".join(TEXT_RE.findall(context))
    return [state for cue, state in TEXT_CUES if cue.search(texts)]


def nav_edges(context: str) -> list[dict]:
    edges = []
    for trigger, name, node in NAV_RE.findall(context):
        edges.append({"trigger": trigger, "target": name or None, "node": node or None})
    return edges


def build_map(feature: Path) -> dict:
    clusters = json.loads(_read(feature / "_scan" / "clusters.json") or "{}").get("clusters", [])
    index = parse_index(feature)
    screens_dir = feature / "screens"
    contexts = {d.name: _read(d / "context.txt") for d in screens_dir.iterdir()
                if d.is_dir() and d.name != "noise" and (d / "context.txt").is_file()}
    name_to_folders: dict[str, list[str]] = {}
    for k, v in index.items():
        if v.get("figma_name"):
            name_to_folders.setdefault(v["figma_name"].strip().lower(), []).append(k)
    folder_to_cluster = {}
    for c in clusters:
        folder_to_cluster[c["base"]] = c["id"]
        for v in c["variants"]:
            folder_to_cluster[v] = c["id"]
    logical = []
    all_edges = []
    for c in clusters:
        members = [c["base"], *c["variants"]]
        states: list[str] = []
        per_screen = {}
        texts = clicks = 0
        for m in members:
            ctx = contexts.get(m, "")
            own = states_from_name(m) or []
            for s in states_from_text(ctx):
                if s not in own:
                    own.append(s)
            if m != c["base"] and not own:
                own = [f"variant ({c['variants'][m]})"]
            if m == c["base"] and not own:
                own = ["default"]
            per_screen[m] = own
            for s in own:
                if s not in states:
                    states.append(s)
            texts = max(texts, len(TEXT_RE.findall(ctx)))
            clicks = max(clicks, len(CLICK_RE.findall(ctx)))
            for e in nav_edges(ctx):
                folders = name_to_folders.get((e["target"] or "").strip().lower(), [])
                clusters_hit = sorted({folder_to_cluster[f] for f in folders if f in folder_to_cluster})
                all_edges.append({"from": m, "from_cluster": c["id"], "trigger": e["trigger"],
                                  "target_name": e["target"], "node": e["node"], "target_folders": folders,
                                  "target_cluster": "|".join(clusters_hit) if clusters_hit else None,
                                  "in_clipboard": bool(folders)})
        hints = []
        if "loading" in states and "error" not in states and "network" not in states:
            hints.append("có loading, chưa có error")
        if ("error" in states or "network" in states) and "loading" not in states:
            hints.append("có error, chưa có loading (nếu có gọi API)")
        if LIST_HINT.search(c["base"]) and "empty" not in states:
            hints.append("màn danh sách/kết quả, chưa có empty")
        logical.append({
            "id": c["id"], "base": c["base"], "figma_name": index.get(c["base"], {}).get("figma_name", ""),
            "case": index.get(c["base"], {}).get("case", ""), "screens": members, "states": states,
            "per_screen": per_screen, "texts": texts, "clicks": clicks, "hints": hints,
        })
    for l in logical:
        l["nav_out"] = sorted({(e["target_cluster"] or "⚠ ngoài clipboard") for e in all_edges if e["from_cluster"] == l["id"]})
        l["nav_in"] = sorted({e["from_cluster"] for e in all_edges if e["target_cluster"] and l["id"] in e["target_cluster"].split("|")})
    unresolved = [e for e in all_edges if not e["in_clipboard"]]
    return {"feature": feature.name, "screens": len(contexts), "logical_screens": len(logical),
            "screens_with_states": sum(1 for f in contexts if states_from_name(f)),
            "edges": len(all_edges), "edges_unresolved": len(unresolved),
            "logical": logical, "edges_list": all_edges}


def render_md(data: dict) -> str:
    out = [f"# UI MAP — {data['feature']}", "",
           "> Sinh tự động từ `_scan/clusters.json` + tên màn + text + cạnh `→ NAVIGATE`. Mọi state ở đây là **INFERRED** — BA xác nhận hoặc bác. "
           "Không phải gate. Mỗi cụm K = một màn logic; blueprint Root lấy `[STATE-MATRIX]` khởi điểm từ đây.", "",
           f"- Màn scan: {data['screens']} · màn logic (cụm): {data['logical_screens']} · màn có state trong tên: {data['screens_with_states']}",
           f"- Cạnh NAVIGATE trong Figma: {data['edges']} (không có đích trong clipboard: {data['edges_unresolved']})", ""]
    if data["edges"] < max(3, data["logical_screens"] // 4):
        out.append("⚠ Figma gần như không vẽ điều hướng — thứ tự Root và luồng phải lấy từ BA.")
        out.append("")
    out += ["## Màn logic", "", "| K | Base | Tên Figma | Màn (state) | States | NAVIGATE ra → | ← vào | Gợi ý thiếu (INFERRED) |",
            "|---|---|---|---|---|---|---|---|"]
    for l in data["logical"]:
        screens = " · ".join(f"`{m}` ({', '.join(l['per_screen'][m])})" for m in l["screens"])
        out.append(f"| {l['id']} | `{l['base']}` | {l['figma_name'] or '—'} | {screens} | {len(l['states'])}: {', '.join(l['states'])} | "
                   f"{', '.join(l['nav_out']) or '—'} | {', '.join(l['nav_in']) or '—'} | {'; '.join(l['hints']) or '—'} |")
    out += ["", "## Luồng NAVIGATE", ""]
    if not data["edges_list"]:
        out.append("(không có)")
    for e in data["edges_list"]:
        dest = (f"{e['target_cluster']} `{'` | `'.join(e['target_folders'])}`" + (" (tên trùng, nhiều màn)" if len(e['target_folders']) > 1 else "")
                if e["in_clipboard"] else f"⚠ \"{e['target_name'] or e.get('node') or '?'}\" không có trong clipboard")
        out.append(f"- {e['from_cluster']} `{e['from']}` → {e['trigger']} → {dest}")
    hints = [(l["id"], h) for l in data["logical"] for h in l["hints"]]
    out += ["", "## Gợi ý thiếu state (INFERRED — BA quyết)", ""]
    out += [f"- {k}: {h}" for k, h in hints] or ["(không có)"]
    return "\n".join(out) + "\n"


def run(feature_dir: str | Path, dry_run: bool = False) -> dict:
    feature = Path(feature_dir).expanduser().resolve()
    if not (feature / "screens").is_dir():
        raise FileNotFoundError(f"screens/ not found under {feature}")
    if not (feature / "_scan" / "clusters.json").is_file():
        raise FileNotFoundError(f"_scan/clusters.json not found — run screen_cluster.py first")
    data = build_map(feature)
    if not dry_run:
        (feature / "_scan" / "UI_MAP.md").write_text(render_md(data), encoding="utf-8")
        slim = {k: v for k, v in data.items() if k != "edges_list"}
        slim["edges_list"] = data["edges_list"]
        (feature / "_scan" / "ui_map.json").write_text(json.dumps(slim, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feature_dir")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        data = run(args.feature_dir, args.dry_run)
    except FileNotFoundError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"ui-map: {data['screens']} screens → {data['logical_screens']} logical · edges {data['edges']} "
          f"({data['edges_unresolved']} unresolved) · hints {sum(len(l['hints']) for l in data['logical'])}"
          + ("" if args.dry_run else " → _scan/UI_MAP.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
