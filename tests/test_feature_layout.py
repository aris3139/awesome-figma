from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.feature_layout import FeatureLayout


class FeatureLayoutTest(unittest.TestCase):
    def test_new_layout_paths_and_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            feature = (Path(temp) / "demo").resolve()
            layout = FeatureLayout.from_feature(feature)

            layout.ensure()

            self.assertEqual(layout.scan_dir, feature / "_scan")
            self.assertEqual(layout.screens_dir, feature / "screens")
            self.assertEqual(layout.noise_dir, feature / "screens" / "noise")
            self.assertTrue(layout.scan_dir.is_dir())
            self.assertTrue(layout.noise_dir.is_dir())

    def test_existing_managed_file_falls_back_to_legacy_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            feature = (Path(temp) / "demo").resolve()
            feature.mkdir()
            legacy_manifest = feature / "manifest.json"
            legacy_manifest.write_text("{}", encoding="utf-8")

            layout = FeatureLayout.from_feature(feature)

            self.assertEqual(
                layout.managed_file("manifest.json", existing=True),
                legacy_manifest,
            )
            self.assertEqual(
                layout.managed_file("manifest.json"),
                feature / "_scan" / "manifest.json",
            )

    def test_migrate_moves_management_active_and_noise_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            feature = (Path(temp) / "demo").resolve()
            screen = feature / "favorite_empty"
            noise = feature / "_noise" / "favorite_copy"
            screen.mkdir(parents=True)
            noise.mkdir(parents=True)
            (feature / "manifest.json").write_text("{}", encoding="utf-8")
            (screen / "context.txt").write_text("screen", encoding="utf-8")
            (noise / "context.txt").write_text("noise", encoding="utf-8")

            layout = FeatureLayout.from_feature(feature)
            moves = layout.migrate()

            self.assertEqual(len(moves), 3)
            self.assertTrue((feature / "_scan" / "manifest.json").is_file())
            self.assertTrue((feature / "screens" / "favorite_empty" / "context.txt").is_file())
            self.assertTrue(
                (feature / "screens" / "noise" / "favorite_copy" / "context.txt").is_file()
            )
            self.assertEqual(
                layout.active_screen_dirs(),
                [feature / "screens" / "favorite_empty"],
            )

    def test_migrate_stops_before_overwriting_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            feature = (Path(temp) / "demo").resolve()
            feature.mkdir()
            (feature / "manifest.json").write_text("legacy", encoding="utf-8")
            (feature / "_scan").mkdir()
            (feature / "_scan" / "manifest.json").write_text("canonical", encoding="utf-8")

            layout = FeatureLayout.from_feature(feature)

            with self.assertRaises(FileExistsError):
                layout.migrate()
            self.assertEqual(
                (feature / "manifest.json").read_text(encoding="utf-8"),
                "legacy",
            )


if __name__ == "__main__":
    unittest.main()
