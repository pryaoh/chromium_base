import json
from pathlib import Path
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from net import enable_in_base as enable
from base.scripts.sync_source import INVENTORY, verify_snapshot, write_inventory


class PromotionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        self.base = root / "base"
        self.combined = root / "combined"
        self.output = self.base / "out/sh"
        self.backup = self.base.with_name("base.base-backup")
        self.base.mkdir()
        self.combined.mkdir()
        for directory, overlay, lock in (
            (self.base, "standalone", enable.base_lock()),
            (self.combined, "net/standalone", enable.combined_lock()),
        ):
            shutil.copyfile(enable.ROOT / overlay / "BUILD.gn", directory / "BUILD.gn")
            (directory / "common.h").write_text("pinned content")
            write_inventory(directory, lock)
        old_time = 1700000000000000000
        os.utime(self.base / "common.h", ns=(old_time, old_time))
        self.output.mkdir(parents=True)
        self.plan = enable.driver.make_plan(self.base, "chromium", linkage="shared",
                                            output_dir=self.output)
        self.identity = {**verify_snapshot(self.base), "gn_version": "test-version"}
        self.report = {"ok": True, "identity": self.identity}
        (self.output / "args.gn").write_text(self.plan["gn_args"])
        for name in ("base.dll", "base.dll.lib", ".ninja_log", ".ninja_deps", "build.ninja"):
            (self.output / name).touch()
        llvm = (Path(self.plan["llvm_root"]) / "bin").as_posix()
        (self.output / "toolchain.ninja").write_text(
            f"  command = {llvm}/clang-cl.exe\n  command = {llvm}/lld-link.exe\n")
        enable.driver.write_manifest(self.plan, self.report, "built")
        self.original = (self.output / enable.driver.MANIFEST).read_bytes()
        self.other = self.base / "out/cs/unrelated.txt"
        self.other.parent.mkdir()
        self.other.write_text("keep")
        doctor = patch.object(enable.driver, "inspect_environment", return_value=self.report)
        doctor.start()
        self.addCleanup(doctor.stop)

    def switch(self, recover=False):
        enable.switch(self.base, self.combined, "chromium", None, recover)

    def sibling(self, name, identity):
        output = self.base / "out" / name
        output.mkdir(parents=True)
        plan = enable.driver.make_plan(self.base, "external", llvm_root=self.base.parent / "llvm",
                                       linkage="static", output_dir=output)
        (output / "args.gn").write_text(plan["gn_args"])
        enable.driver.write_manifest(plan, {"identity": identity}, "built")
        path = output / enable.driver.MANIFEST
        path.write_bytes(json.dumps(json.loads(path.read_bytes()), indent=3).encode() + b"\r\n")
        return plan, path

    def test_sibling_static_output_accepts_its_own_toolchain_after_switch(self):
        identity = {**self.identity, "compiler_versions": {"clang-cl": "external"}}
        plan, _ = self.sibling("chromium-base/external-static", identity)
        stale_plan, stale_path = self.sibling("stale", {**identity, "source_inventory_sha256": "old"})
        stale_bytes = stale_path.read_bytes()
        self.switch()
        report = {"ok": True, "identity": {**identity, **verify_snapshot(self.base)}}
        self.assertEqual(enable.driver.read_manifest(plan, report)["state"], "needs_configure")
        self.assertEqual(stale_path.read_bytes(), stale_bytes)
        with self.assertRaisesRegex(ValueError, "identity"):
            enable.driver.read_manifest(stale_plan, report)
        self.assertEqual(self.other.read_text(), "keep")

    def test_recovers_exact_bytes_after_multiple_manifest_updates(self):
        _, path = self.sibling("es", {**self.identity, "compiler_versions": {"clang-cl": "external"}})
        originals = {path: path.read_bytes(), self.output / enable.driver.MANIFEST: self.original}
        unlink = Path.unlink

        def interrupt_commit(target, *args, **kwargs):
            if target.name.endswith(".net-switch.json"):
                raise KeyboardInterrupt
            return unlink(target, *args, **kwargs)

        with patch.object(Path, "unlink", interrupt_commit):
            with self.assertRaises(KeyboardInterrupt):
                self.switch()
        for target in originals:
            self.assertEqual(json.loads(target.read_bytes())["state"], "needs_configure")
        self.switch(recover=True)
        for target, original in originals.items():
            self.assertEqual(target.read_bytes(), original)

    def test_promote_preserves_build_and_matching_input_timestamps(self):
        combined_identity = verify_snapshot(self.combined)
        self.switch()
        self.assertFalse(self.combined.exists())
        self.assertEqual(verify_snapshot(self.base), combined_identity)
        self.assertEqual(verify_snapshot(self.backup)["revision"], self.identity["revision"])
        self.assertEqual((self.base / "common.h").stat().st_mtime_ns,
                         (self.backup / "common.h").stat().st_mtime_ns)
        self.assertEqual(self.other.read_text(), "keep")
        manifest = json.loads((self.output / enable.driver.MANIFEST).read_bytes())
        self.assertEqual(manifest["state"], "needs_configure")
        self.assertEqual(manifest["identity"], {**self.identity, **combined_identity})
        self.assertEqual(manifest["plan"], self.plan)

    def test_changed_input_and_wrong_tool_identity_are_rejected(self):
        (self.combined / "common.h").write_text("different")
        write_inventory(self.combined, enable.combined_lock())
        with self.assertRaisesRegex(ValueError, "common.h"):
            self.switch()
        shutil.copyfile(self.base / "common.h", self.combined / "common.h")
        write_inventory(self.combined, enable.combined_lock())
        self.report["identity"] = {**self.identity, "gn_version": "changed"}
        with self.assertRaisesRegex(ValueError, "identity"):
            self.switch()
        self.assertFalse(self.backup.exists())
        self.assertEqual((self.output / enable.driver.MANIFEST).read_bytes(), self.original)

    def test_rejects_existing_combined_outputs(self):
        (self.combined / "out").mkdir()
        with self.assertRaisesRegex(ValueError, "out"):
            self.switch()
        self.assertTrue(self.other.exists())
        self.assertFalse(self.backup.exists())

    def test_rejects_active_output(self):
        (self.output / ".ninja_lock").touch()
        with self.assertRaisesRegex(ValueError, "active build"):
            self.switch()
        self.assertFalse(self.backup.exists())

    def test_rolls_back_a_failed_second_rename(self):
        original_rename = Path.rename

        def fail_promotion(path, target):
            if path == self.combined:
                raise PermissionError("fixture permits recovery only")
            return original_rename(path, target)

        with patch.object(Path, "rename", fail_promotion):
            with self.assertRaisesRegex(PermissionError, "fixture"):
                self.switch()
        self.assertFalse(self.backup.exists())
        self.assertFalse((self.combined / "out").exists())
        self.assertEqual((self.output / enable.driver.MANIFEST).read_bytes(), self.original)

    def test_recovers_interruption_between_two_manifest_updates(self):
        _, sibling = self.sibling("es", self.identity)
        original_sibling = sibling.read_bytes()
        write = enable.atomic_write
        manifest_count = 0

        def interrupt_update(path, data):
            nonlocal manifest_count
            if path.name == enable.driver.MANIFEST:
                manifest_count += 1
                if manifest_count == 2:
                    raise KeyboardInterrupt
            write(path, data)

        with patch.object(enable, "atomic_write", interrupt_update):
            with self.assertRaises(KeyboardInterrupt):
                self.switch()
        states = {json.loads(p.read_bytes())["state"] for p in
                  (self.output / enable.driver.MANIFEST, sibling)}
        self.assertEqual(states, {"built", "needs_configure"})
        self.switch(recover=True)
        self.assertFalse(self.backup.exists())
        self.assertTrue((self.combined / INVENTORY).exists())
        self.assertFalse((self.combined / "out").exists())
        self.assertEqual((self.output / enable.driver.MANIFEST).read_bytes(), self.original)
        self.assertEqual(sibling.read_bytes(), original_sibling)
        self.assertEqual(self.other.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
