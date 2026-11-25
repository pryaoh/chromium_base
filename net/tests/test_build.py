import json
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from net import build, sync_source


class NetBuildTests(TestCase):
    def test_combined_source_extends_pinned_base_lock(self):
        base = json.loads((ROOT / "source.lock.json").read_text())
        net = sync_source.combined_lock()
        self.assertEqual(net["target"], "//net:net")
        self.assertEqual(net["repositories"][0]["revision"], base["repositories"][0]["revision"])
        inputs = set(net["repositories"][0]["paths"])
        self.assertTrue(set(base["repositories"][0]["paths"]).issubset(inputs))
        self.assertTrue({"net", "url", "crypto"}.issubset(inputs))
        for original in base["repositories"][1:]:
            self.assertIn(original, net["repositories"])

    def test_net_plan_uses_same_args_and_output_as_base(self):
        source = ROOT / "vendor/chromium-net"
        plan = build.chromium_base.make_plan(source, "chromium", linkage="shared",
                                             output_dir=source / "out/sh")
        with patch("builtins.print") as output:
            self.assertEqual(build.main(["plan"]), 0)
        self.assertEqual(json.loads(output.call_args.args[0]), dict(target="//net:net", **plan))
