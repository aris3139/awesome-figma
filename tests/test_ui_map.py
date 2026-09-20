"""ui_map.py: logical screens, states from names/text, NAVIGATE edges, missing-state hints — on a synthetic scan."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import screen_cluster, ui_map


def screen(feature: Path, name: str, lines: list[str]) -> None:
    d = feature / "screens" / name; d.mkdir(parents=True)
    (d / "context.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


class UiMapTest(unittest.TestCase):
    def make(self, root: Path) -> Path:
        f = root / "feat"; (f / "_scan").mkdir(parents=True)
        base = [f"FRAME \"Devices\" (430×933)"] + [f"  TEXT \"row {i}\" | fill=#fff" for i in range(30)]
        screen(f, "device_list", base + ["  → ON_CLICK NAVIGATE \"Enter passcode\""])
        screen(f, "device_list_loading", base[:28] + ["  TEXT \"Đang tải\"", "    text=\"Đang tải thiết bị\""])
        screen(f, "device_list_error", base[:28] + ["  TEXT \"err\"", "    text=\"Không tìm thấy, thử lại\""])
        screen(f, "passcode", ["FRAME \"Enter passcode\" (430×933)", "  TEXT \"_ _ _ _\"", "  → ON_CLICK NAVIGATE node 1:99 (not in clipboard)"])
        (f / "_scan" / "index.md").write_text(
            "| Folder | Original Figma name | node-id | Cluster | Case description | Status |\n|---|---|---|---|---|---|\n"
            "| device_list | Devices | 1:1 | K01 | list | ok |\n| device_list_loading | Devices | 1:2 | K01 | loading | ok |\n"
            "| device_list_error | Devices | 1:3 | K01 | error | ok |\n| passcode | Enter passcode | 1:4 | K02 | code | ok |\n", encoding="utf-8")
        screen_cluster.run(f)
        return f

    def test_map_states_edges_hints(self):
        with tempfile.TemporaryDirectory() as temp:
            f = self.make(Path(temp))
            data = ui_map.run(f)
            self.assertEqual(data["logical_screens"], 2)
            k01 = next(l for l in data["logical"] if l["base"] == "device_list")
            self.assertIn("loading", k01["states"]); self.assertIn("error", k01["states"])
            self.assertIn("empty", " ".join(k01["hints"]))                       # list without an empty state
            k02 = next(l for l in data["logical"] if l["base"] == "passcode")
            self.assertEqual(k01["nav_out"], [k02["id"]])                          # "Enter passcode" resolved by Figma name
            self.assertEqual(k02["nav_out"], ["⚠ ngoài clipboard"])
            self.assertEqual(data["edges_unresolved"], 1)
            md = (f / "_scan" / "UI_MAP.md").read_text(encoding="utf-8")
            self.assertIn("| K01 |", md); self.assertIn("không có trong clipboard", md); self.assertIn("INFERRED", md)
            self.assertTrue((f / "_scan" / "ui_map.json").is_file())

    def test_dry_run_writes_nothing_and_needs_clusters(self):
        with tempfile.TemporaryDirectory() as temp:
            f = self.make(Path(temp))
            ui_map.run(f, dry_run=True)
            self.assertFalse((f / "_scan" / "UI_MAP.md").exists())
            (f / "_scan" / "clusters.json").unlink()
            with self.assertRaises(FileNotFoundError):
                ui_map.run(f)
