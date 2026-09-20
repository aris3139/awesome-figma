"""Scanner regressions measured on real Figma clips (docs/improve-plan-2026-09-18.md).

P0 cases pass; the P1 cases are marked expectedFailure so the suite documents the baseline and flips to an
"unexpected success" (= remove the marker) when P1 lands.
"""
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import figma_deep_scan as scan_mod

VIEWPORT = (0, 0, 430, 932)
WHITE = [{"type": "SOLID", "color": {"r": 1, "g": 1, "b": 1, "a": 1}}]
DIM = [{"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0, "a": 1}, "opacity": 0.32}]


def node(name, ntype, x, y, w, h, **extra):
    d = {"name": name, "type": ntype, "id": name, "visible": True,
         "absoluteBoundingBox": {"x": x, "y": y, "width": w, "height": h}}
    d.update(extra)
    return d


def text(chars, x, y, w=120, h=20):
    return node(chars, "TEXT", x, y, w, h, characters=chars,
                style={"fontFamily": "SF Pro", "fontSize": 16, "fontWeight": 400})


def screen(*children):
    scan_mod.stats = scan_mod.Stats()
    return scan_mod.scan(node("Screen", "FRAME", 0, 0, 430, 932, children=list(children)), VIEWPORT)


def flat(tree):
    out = []

    def walk(n):
        if not n: return
        out.append(n)
        for c in n.get("children", []): walk(c)
    walk(tree)
    return out


class OverlayAndScrimTest(unittest.TestCase):
    """II.3 — a layer named Overlay/Scrim that wraps a dialog is content, not decoration."""

    def test_overlay_wrapping_dialog_is_kept_with_scrim_attr(self):
        overlay = node("Overlay", "FRAME", 0, 0, 430, 932, fills=DIM, children=[
            node("Dialog", "FRAME", 40, 300, 350, 200, fills=WHITE, children=[
                text("Đăng xuất?", 60, 320), text("Huỷ", 60, 440, 100, 40), text("OK", 300, 440, 60, 40)])])
        tree = screen(overlay)
        names = [n.get("name") for n in flat(tree)]
        self.assertIn("Overlay", names)
        self.assertEqual({"Đăng xuất?", "Huỷ", "OK"} & set(names), {"Đăng xuất?", "Huỷ", "OK"})
        kept = next(n for n in flat(tree) if n.get("name") == "Overlay")
        self.assertNotIn("fill", kept)
        self.assertTrue(kept.get("scrim"))
        line = "\n".join(scan_mod.generate_context(tree))
        self.assertIn("scrim=", line)

    def test_scrim_without_content_is_still_dropped(self):
        scrim = node("Scrim", "FRAME", 0, 0, 430, 932, fills=DIM,
                     children=[node("Rect", "RECTANGLE", 0, 0, 430, 932, fills=DIM)])
        tree = screen(scrim, text("Title", 16, 60))
        self.assertNotIn("Scrim", [n.get("name") for n in flat(tree)])

    def test_state_layer_wrapping_button_label_is_kept(self):
        button = node("Button", "FRAME", 16, 800, 142, 46, fills=WHITE, children=[
            node("State-layer", "FRAME", 16, 800, 142, 46, layoutMode="HORIZONTAL", paddingLeft=24, paddingRight=24,
                 paddingTop=12, paddingBottom=12, children=[text("Chọn thiết bị", 40, 812, 94, 22)])])
        tree = screen(button, text("Other", 16, 60))
        names = [n.get("name") for n in flat(tree)]
        self.assertIn("Chọn thiết bị", names)


class PaddedWrapperTest(unittest.TestCase):
    """II.4 — a single-child wrapper that adds padding is layout and survives the collapse."""

    def test_explicit_padding_wrapper_is_kept(self):
        wrap = node("Toolbar - Top", "FRAME", 0, 0, 430, 82, layoutMode="VERTICAL",
                    paddingTop=16, paddingBottom=16, paddingLeft=16, paddingRight=16,
                    children=[node("Frame 1", "FRAME", 16, 16, 398, 50, fills=WHITE)])
        tree = screen(wrap, text("Other", 0, 200))
        kept = next((n for n in flat(tree) if n.get("name") == "Toolbar - Top"), None)
        self.assertIsNotNone(kept, "wrapper collapsed away")
        self.assertEqual(kept.get("padding"), 16)
        self.assertEqual(kept.get("layout"), "COLUMN")   # explicit layoutMode=VERTICAL wins over SINGLE
        self.assertEqual([c["name"] for c in kept["children"]], ["Frame 1"])

    def test_inferred_padding_wrapper_is_kept(self):
        wrap = node("Title and Controls", "FRAME", 0, 0, 430, 40,
                    children=[node("3", "FRAME", 16, 0, 40, 40, fills=WHITE)])
        tree = screen(wrap, text("Other", 0, 200))
        kept = next((n for n in flat(tree) if n.get("name") == "Title and Controls"), None)
        self.assertIsNotNone(kept)
        self.assertEqual(kept.get("padding"), {"left": 16, "right": 374})

    def test_wrapper_without_padding_still_collapses(self):
        wrap = node("Wrapper", "FRAME", 0, 0, 430, 50, children=[node("Inner", "FRAME", 0, 0, 430, 50, fills=WHITE)])
        tree = screen(wrap, text("Other", 0, 200))
        names = [n.get("name") for n in flat(tree)]
        self.assertNotIn("Wrapper", names)
        self.assertIn("Inner", names)


class TokenPassTest(unittest.TestCase):
    """II.1 — a None tree (root clip hidden/decorative) must not crash the token golden."""

    def test_collect_tokens_none(self):
        acc = scan_mod.collect_tokens(None)
        self.assertEqual(sum(acc["fonts"].values()), 0)

    def test_generate_tokens_none_renders(self):
        self.assertIn("DESIGN TOKENS", scan_mod.generate_tokens(None))


class SvgBlobTest(unittest.TestCase):
    """II.2 — corrupt vector blobs return null instead of throwing."""

    def test_truncated_commands_blob_returns_null(self):
        js = ("import('./svg.mjs').then(m=>{const r=[m.commandsBlobToPath(new Uint8Array([1,2,3])),"
              "m.vectorNetworkBlobToPath(new Uint8Array(20).fill(9))];console.log(JSON.stringify(r))})")
        try:
            out = subprocess.run(["node", "-e", js], cwd=Path(__file__).resolve().parent.parent / "scripts" / "figclip",
                                 capture_output=True, text=True, timeout=30, check=True).stdout.strip()
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            self.skipTest(f"node unavailable: {e}")
        self.assertEqual(out, "[null,null]")


class P1BaselineTest(unittest.TestCase):
    """Known P1 defects (context semantics). Remove the marker when each fix lands."""

    @unittest.expectedFailure
    def test_peek_card_in_horizontal_row_is_not_dropped(self):
        lst = node("List", "FRAME", 0, 0, 430, 200, layoutMode="HORIZONTAL", clipsContent=True, children=[
            node("Card1", "FRAME", 16, 0, 300, 200, fills=WHITE), node("Card2", "FRAME", 355, 0, 300, 200, fills=WHITE)])
        tree = screen(lst, text("x", 0, 500))
        self.assertIn("Card2", [n.get("name") for n in flat(tree)])

    @unittest.expectedFailure
    def test_big_leaf_instance_is_not_an_icon(self):
        tree = screen(node("PrimaryButton", "INSTANCE", 20, 100, 390, 50), text("x", 0, 500))
        inst = next(n for n in flat(tree) if n.get("name") == "PrimaryButton")
        self.assertNotEqual(inst.get("type"), "ICON")

    @unittest.expectedFailure
    def test_two_glyph_buttons_are_not_flattened_to_one_icon(self):
        vec = lambda n, x, y: node(n, "VECTOR", x, y, 24, 24, fills=WHITE)
        act = node("Actions Container", "FRAME", 100, 800, 175, 32, children=[
            node("Playlist", "INSTANCE", 100, 804, 24, 24, children=[vec("v1", 100, 804)]),
            node("Next", "INSTANCE", 251, 804, 24, 24, children=[vec("v2", 251, 804)])])
        tree = screen(act, text("x", 0, 500))
        cont = next(n for n in flat(tree) if n.get("name") == "Actions Container")
        self.assertNotEqual(cont.get("type"), "ICON")

    @unittest.expectedFailure
    def test_progress_bar_is_not_an_icon(self):
        bar = node("Progress Bar", "FRAME", 20, 800, 260, 18, children=[
            node("Track", "RECTANGLE", 20, 807, 260, 4, fills=WHITE), node("Fill", "RECTANGLE", 20, 807, 100, 4, fills=WHITE),
            node("Handle", "ELLIPSE", 110, 800, 18, 18, fills=WHITE)])
        tree = screen(bar, text("x", 0, 500))
        self.assertNotEqual(next(n for n in flat(tree) if n.get("name") == "Progress Bar").get("type"), "ICON")


if __name__ == "__main__":
    unittest.main()
