import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def module(self):
        import sync_source
        return sync_source

    def test_paths_cannot_escape_snapshot_or_write_git_metadata(self):
        sync = self.module()
        for path in ("../escape", "/absolute", "C:/absolute", ".git/config", "base/../../escape", "base\\..\\escape"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                sync.safe_path(path)

    def test_lock_requires_commit_shas_and_narrow_paths(self):
        sync = self.module()
        repo = {"name": "chromium", "url": "https://github.com/chromium/chromium.git",
                "revision": "main", "destination": "", "paths": ["base"]}
        with self.assertRaisesRegex(ValueError, "revision"):
            sync.validate_lock({"schema": 1, "repositories": [repo]})
        repo["revision"] = "a" * 40
        repo["paths"] = ["."]
        with self.assertRaises(ValueError):
            sync.validate_lock({"schema": 1, "repositories": [repo]})

    def test_archive_traversal_is_rejected_before_any_write(self):
        sync = self.module()
        archive = self.root / "bad.tar"
        with tarfile.open(archive, "w") as tar:
            good = tarfile.TarInfo("base/good.h")
            good.size = 2
            tar.addfile(good, io.BytesIO(b"ok"))
            bad = tarfile.TarInfo("../escape")
            bad.size = 3
            tar.addfile(bad, io.BytesIO(b"bad"))
        dest = self.root / "out"
        with self.assertRaises(ValueError):
            sync.extract_archive(archive, dest)
        self.assertFalse((dest / "base/good.h").exists())

    def test_export_includes_only_selected_source_paths(self):
        sync = self.module()
        repo = self.root / "repo"
        repo.mkdir()
        for name in ("base/file.h", "build/config.gni", "chrome/browser/unused.cc", "LICENSE"):
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        # Export selected objects, regardless of archive-only attributes.
        (repo / ".gitattributes").write_text("base/file.h export-ignore\n")
        def git(*args):
            return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()
        git("init", "-q")
        git("add", ".")
        git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
        revision = git("rev-parse", "HEAD")
        # Local Git replacement objects must not change the pinned export.
        original = git("rev-parse", revision + ":base/file.h")
        replacement = git("rev-parse", revision + ":chrome/browser/unused.cc")
        git("replace", original, replacement)
        dest = self.root / "snapshot"
        sync.export_tree(repo, revision, ["base", "build", "LICENSE"], dest)
        self.assertTrue((dest / "base/file.h").is_file())
        self.assertEqual((dest / "base/file.h").read_text(), "base/file.h")
        self.assertTrue((dest / "LICENSE").is_file())
        self.assertFalse((dest / "chrome").exists())
        self.assertFalse((dest / ".git").exists())
        with self.assertRaisesRegex(ValueError, "not found"):
            sync.export_tree(repo, revision, ["base", "missing-source-path"], self.root / "bad-snapshot")

    def test_snapshot_verification_detects_modified_and_missing_sources(self):
        sync = self.module()
        dest = self.root / "snapshot"
        dest.mkdir()
        header = dest / "header.h"
        header.write_text("original")
        sync.write_inventory(dest, {"schema": 1, "repositories": [{"revision": "a" * 40}]})
        self.assertEqual(sync.verify_snapshot(dest)["revision"], "a" * 40)
        extra = dest / "injected.h"
        extra.write_text("new")
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            sync.verify_snapshot(dest)
        extra.unlink()
        (dest / "out").mkdir()
        (dest / "out/build.ninja").write_text("generated")
        sync.verify_snapshot(dest)
        header.write_text("changed")
        with self.assertRaisesRegex(ValueError, "modified"):
            sync.verify_snapshot(dest)
        header.unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            sync.verify_snapshot(dest)

    def test_sync_preserves_existing_destination(self):
        sync = self.module()
        dest = self.root / "snapshot"
        dest.mkdir()
        (dest / "mine").write_text("keep")
        with self.assertRaisesRegex(ValueError, "exists"):
            sync.synchronize({"schema": 1, "repositories": []}, dest, self.root / "cache", None)
        self.assertEqual((dest / "mine").read_text(), "keep")

    def test_added_directory_link_cannot_bypass_inventory(self):
        sync = self.module()
        dest = self.root / "snapshot"
        dest.mkdir()
        (dest / "header.h").write_text("original")
        sync.write_inventory(dest, {"repositories": [{"revision": "a" * 40}]})
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "injected.h").write_text("extra")
        link = dest / "extra"
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
        else:
            link.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "filesystem link"):
            sync.verify_snapshot(dest)


if __name__ == "__main__":
    unittest.main()
