import json
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import screen_cluster


BASE_TEXT = "\n".join(f"FRAME \"Row{i}\" (398x60) | fill=#111111" for i in range(50))
VARIANT_TEXT = BASE_TEXT.replace('FRAME "Row10"', 'FRAME "Row10Badge"') + "\nTEXT \"badge\" (40x14)"
DISTINCT_TEXT = "\n".join(f"TEXT \"Other{i}\" (200x18) | size=14" for i in range(50))


def make_feature(tmp: Path, screens: dict[str, str]) -> Path:
    feature = tmp / "demo"
    (feature / "_scan").mkdir(parents=True)
    (feature / "screens" / "noise" / "junk").mkdir(parents=True)
    (feature / "screens" / "noise" / "junk" / "context.txt").write_text(
        BASE_TEXT, encoding="utf-8"
    )
    for name, text in screens.items():
        d = feature / "screens" / name
        d.mkdir(parents=True)
        (d / "context.txt").write_text(text, encoding="utf-8")
    return feature


class ClusterTests(unittest.TestCase):
    def test_similar_screens_cluster_with_largest_base(self):
        clusters = screen_cluster.build_clusters(
            {
                "doi_all_starred": BASE_TEXT.splitlines(),
                "doi_unstar": VARIANT_TEXT.splitlines(),
                "de_xuat": DISTINCT_TEXT.splitlines(),
            },
            threshold=0.8,
        )
        by_base = {c["base"]: c for c in clusters}
        self.assertIn("doi_unstar", by_base)
        self.assertIn("doi_all_starred", by_base["doi_unstar"]["variants"])
        self.assertGreaterEqual(by_base["doi_unstar"]["variants"]["doi_all_starred"], 0.8)
        self.assertEqual(by_base["de_xuat"]["variants"], {})

    def test_distinct_screens_are_singletons(self):
        clusters = screen_cluster.build_clusters(
            {"a": BASE_TEXT.splitlines(), "b": DISTINCT_TEXT.splitlines()},
            threshold=0.8,
        )
        self.assertEqual(len(clusters), 2)
        for c in clusters:
            self.assertEqual(c["variants"], {})

    def test_cluster_ids_stable_and_sequential(self):
        clusters = screen_cluster.build_clusters(
            {"a": BASE_TEXT.splitlines(), "b": DISTINCT_TEXT.splitlines()},
            threshold=0.8,
        )
        self.assertEqual([c["id"] for c in clusters], ["K01", "K02"])

    def test_screen_dirs_skip_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            feature = make_feature(Path(tmp), {"a": BASE_TEXT})
            names = [d.name for d in screen_cluster.screen_dirs(feature)]
            self.assertEqual(names, ["a"])


class DiffTests(unittest.TestCase):
    def _run(self, tmp: Path):
        feature = make_feature(
            Path(tmp),
            {"doi_all_starred": BASE_TEXT, "doi_unstar": VARIANT_TEXT},
        )
        screens = {
            d.name: (d / "context.txt").read_text(encoding="utf-8").splitlines()
            for d in screen_cluster.screen_dirs(feature)
        }
        clusters = screen_cluster.build_clusters(screens, threshold=0.8)
        written = screen_cluster.write_diffs(feature, clusters, screens)
        return feature, written

    def test_diff_written_for_variant_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            feature, written = self._run(tmp)
            self.assertEqual(len(written), 1)
            diff_path = feature / "screens" / "doi_all_starred" / "diff_vs_doi_unstar.txt"
            self.assertEqual(written[0], diff_path)
            body = diff_path.read_text(encoding="utf-8")
            self.assertIn("Row10Badge", body)
            self.assertIn("base/doi_unstar/context.txt", body)

    def test_rerun_removes_stale_diffs(self):
        with tempfile.TemporaryDirectory() as tmp:
            feature, _ = self._run(tmp)
            stale = feature / "screens" / "doi_unstar" / "diff_vs_ghost.txt"
            stale.write_text("stale", encoding="utf-8")
            screens = {
                d.name: (d / "context.txt").read_text(encoding="utf-8").splitlines()
                for d in screen_cluster.screen_dirs(feature)
            }
            clusters = screen_cluster.build_clusters(screens, threshold=0.8)
            screen_cluster.write_diffs(feature, clusters, screens)
            self.assertFalse(stale.exists())


class RunTests(unittest.TestCase):
    def test_run_writes_clusters_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            feature = make_feature(
                Path(tmp),
                {"doi_all_starred": BASE_TEXT, "doi_unstar": VARIANT_TEXT, "de_xuat": DISTINCT_TEXT},
            )
            payload = screen_cluster.run(feature)
            on_disk = json.loads(
                (feature / "_scan" / "clusters.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload, on_disk)
            self.assertEqual(on_disk["threshold"], 0.8)
            self.assertEqual(len(on_disk["clusters"]), 2)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            feature = make_feature(
                Path(tmp), {"doi_all_starred": BASE_TEXT, "doi_unstar": VARIANT_TEXT}
            )
            screen_cluster.run(feature, dry_run=True)
            self.assertFalse((feature / "_scan" / "clusters.json").exists())
            diffs = list((feature / "screens").rglob("diff_vs_*.txt"))
            self.assertEqual(diffs, [])

    def test_run_missing_screens_dir_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                screen_cluster.run(Path(tmp) / "nope")


if __name__ == "__main__":
    unittest.main()
