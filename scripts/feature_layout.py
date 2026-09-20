#!/usr/bin/env python3
"""Resolve and migrate Awesome feature folders to the canonical layout."""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path


SCAN_DIRNAME = "_scan"
SCREENS_DIRNAME = "screens"
NOISE_DIRNAME = "noise"
LEGACY_NOISE_DIRNAME = "_noise"
MANAGED_FILENAMES = ("raw.json", "manifest.json", "index.md", "DESIGN_TOKENS.txt")
SCREEN_EVIDENCE_FILENAMES = (
    "context.txt",
    "summary.txt",
    "screenshot.png",
    "raw.json",
)


@dataclass(frozen=True)
class FeatureLayout:
    feature_dir: Path
    scan_dir: Path
    screens_dir: Path
    noise_dir: Path

    @classmethod
    def from_feature(cls, feature_dir: str | Path) -> "FeatureLayout":
        feature = Path(feature_dir).expanduser().resolve()
        screens = feature / SCREENS_DIRNAME
        return cls(
            feature_dir=feature,
            scan_dir=feature / SCAN_DIRNAME,
            screens_dir=screens,
            noise_dir=screens / NOISE_DIRNAME,
        )

    def ensure(self) -> None:
        self.scan_dir.mkdir(parents=True, exist_ok=True)
        self.noise_dir.mkdir(parents=True, exist_ok=True)

    def managed_file(self, filename: str, *, existing: bool = False) -> Path:
        if filename not in MANAGED_FILENAMES:
            raise ValueError(f"Unsupported managed file: {filename}")
        canonical = self.scan_dir / filename
        legacy = self.feature_dir / filename
        if existing and not canonical.exists() and legacy.exists():
            return legacy
        return canonical

    def active_screen_dirs(self) -> list[Path]:
        """Return canonical screens plus readable legacy screens during migration."""
        found: dict[str, Path] = {}
        if self.screens_dir.is_dir():
            for child in self.screens_dir.iterdir():
                if child.is_dir() and child.name != NOISE_DIRNAME:
                    found[child.name] = child
        for child in self._legacy_screen_dirs():
            found.setdefault(child.name, child)
        return [found[name] for name in sorted(found)]

    def existing_noise_dir(self) -> Path:
        if self.noise_dir.is_dir():
            return self.noise_dir
        legacy = self.feature_dir / LEGACY_NOISE_DIRNAME
        return legacy if legacy.is_dir() else self.noise_dir

    def is_legacy(self) -> bool:
        return any((self.feature_dir / name).exists() for name in MANAGED_FILENAMES) or bool(
            self._legacy_screen_dirs()
        ) or (self.feature_dir / LEGACY_NOISE_DIRNAME).is_dir()

    def migration_moves(self) -> list[tuple[Path, Path]]:
        moves: list[tuple[Path, Path]] = []
        for filename in MANAGED_FILENAMES:
            source = self.feature_dir / filename
            if source.exists():
                moves.append((source, self.scan_dir / filename))
        for source in self._legacy_screen_dirs():
            moves.append((source, self.screens_dir / source.name))
        legacy_noise = self.feature_dir / LEGACY_NOISE_DIRNAME
        if legacy_noise.is_dir():
            for source in sorted(legacy_noise.iterdir()):
                if not source.name.startswith("."):
                    moves.append((source, self.noise_dir / source.name))
        return moves

    def migrate(self, *, dry_run: bool = False) -> list[tuple[Path, Path]]:
        moves = self.migration_moves()
        collisions = [(source, target) for source, target in moves if target.exists()]
        if collisions:
            details = "\n".join(f"  {source} -> {target}" for source, target in collisions)
            raise FileExistsError(f"Migration target already exists:\n{details}")
        if not dry_run:
            self.ensure()
            for source, target in moves:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
        return moves

    def _legacy_screen_dirs(self) -> list[Path]:
        if not self.feature_dir.is_dir():
            return []
        reserved = {
            SCAN_DIRNAME,
            SCREENS_DIRNAME,
            LEGACY_NOISE_DIRNAME,
            "_inputs",
            "_review",
            "blueprints",
            "contracts",
            "_handoff",
        }
        return sorted(
            child
            for child in self.feature_dir.iterdir()
            if child.is_dir()
            and child.name not in reserved
            and not child.name.startswith(".")
            and any((child / filename).exists() for filename in SCREEN_EVIDENCE_FILENAMES)
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve or migrate a Awesome feature to _scan/ + screens/ layout."
    )
    parser.add_argument("feature_dir", help="Awesome feature directory")
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Move legacy root metadata/screens into the canonical layout.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print migration moves without changing files.",
    )
    args = parser.parse_args()

    layout = FeatureLayout.from_feature(args.feature_dir)
    if not args.migrate:
        print(f"feature={layout.feature_dir}")
        print(f"scan={layout.scan_dir}")
        print(f"screens={layout.screens_dir}")
        print(f"noise={layout.noise_dir}")
        return

    moves = layout.migrate(dry_run=args.dry_run)
    if not moves:
        print("No legacy layout entries found.")
        return
    prefix = "WOULD MOVE" if args.dry_run else "MOVED"
    for source, target in moves:
        print(f"{prefix} {source} -> {target}")


if __name__ == "__main__":
    main()
