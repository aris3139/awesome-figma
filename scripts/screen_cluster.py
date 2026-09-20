#!/usr/bin/env python3
"""Cluster screen evidence by context.txt similarity; emit variant diffs.

Designers copy a screen and tweak one detail to demo a case. Those variants
cluster around a base screen. The blueprint builder then reads the base
context in full and each variant as a small diff instead of reading every
context.txt.

Usage:
    python3 screen_cluster.py <feature-dir> [--threshold 0.8] [--dry-run]

Outputs:
    _scan/clusters.json                     cluster assignments + ratios
    screens/<variant>/diff_vs_<base>.txt    unified diff base -> variant
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

DEFAULT_THRESHOLD = 0.8


def screen_dirs(feature: Path) -> list[Path]:
    screens = feature / "screens"
    result = []
    for child in sorted(screens.iterdir()):
        if child.name == "noise" or not child.is_dir():
            continue
        if (child / "context.txt").is_file():
            result.append(child)
    return result


def _similarity(a: list[str], b: list[str], threshold: float) -> float:
    total = len(a) + len(b)
    if total == 0:
        return 1.0
    if (2.0 * min(len(a), len(b))) / total < threshold:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def build_clusters(
    screens: dict[str, list[str]], threshold: float = DEFAULT_THRESHOLD
) -> list[dict]:
    order = sorted(screens, key=lambda name: (-len(screens[name]), name))
    unassigned = set(order)
    clusters: list[dict] = []
    for name in order:
        if name not in unassigned:
            continue
        unassigned.discard(name)
        variants: dict[str, float] = {}
        for other in order:
            if other not in unassigned:
                continue
            ratio = _similarity(screens[name], screens[other], threshold)
            if ratio >= threshold:
                variants[other] = round(ratio, 3)
                unassigned.discard(other)
        clusters.append({"base": name, "variants": variants})
    for index, cluster in enumerate(clusters, 1):
        cluster["id"] = f"K{index:02d}"
    return clusters


def write_diffs(
    feature: Path, clusters: list[dict], screens: dict[str, list[str]]
) -> list[Path]:
    for directory in screen_dirs(feature):
        for stale in directory.glob("diff_vs_*.txt"):
            stale.unlink()
    written: list[Path] = []
    for cluster in clusters:
        base = cluster["base"]
        for variant in cluster["variants"]:
            diff_lines = difflib.unified_diff(
                screens[base],
                screens[variant],
                fromfile=f"base/{base}/context.txt",
                tofile=f"variant/{variant}/context.txt",
                lineterm="",
            )
            path = feature / "screens" / variant / f"diff_vs_{base}.txt"
            path.write_text("\n".join(diff_lines) + "\n", encoding="utf-8")
            written.append(path)
    return written


def run(
    feature_dir: str | Path,
    threshold: float = DEFAULT_THRESHOLD,
    dry_run: bool = False,
) -> dict:
    feature = Path(feature_dir).expanduser().resolve()
    if not (feature / "screens").is_dir():
        raise FileNotFoundError(f"screens/ not found under {feature}")
    screens = {
        d.name: (d / "context.txt").read_text(encoding="utf-8").splitlines()
        for d in screen_dirs(feature)
    }
    clusters = build_clusters(screens, threshold)
    payload = {"threshold": threshold, "clusters": clusters}
    if not dry_run:
        write_diffs(feature, clusters, screens)
        scan_dir = feature / "_scan"
        scan_dir.mkdir(exist_ok=True)
        (scan_dir / "clusters.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feature_dir")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = run(args.feature_dir, args.threshold, args.dry_run)
    except FileNotFoundError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    total_variants = sum(len(c["variants"]) for c in payload["clusters"])
    print(f"clusters: {len(payload['clusters'])} · variants: {total_variants}")
    for cluster in payload["clusters"]:
        variants = ", ".join(
            f"{name} ({ratio})" for name, ratio in cluster["variants"].items()
        ) or "-"
        print(f"  {cluster['id']}  base={cluster['base']}  variants: {variants}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
