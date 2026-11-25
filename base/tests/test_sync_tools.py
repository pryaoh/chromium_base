import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sync_tools
from sync_source import sha256


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.tools = self.root / "tools"

    def package(self, entries=None):
        archive = self.cache / "tool.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            for name, value in (entries or {"bin/tool.exe": b"fixture"}).items():
                bundle.writestr(name, value)
        return {"archive": archive.name, "url": "https://example.invalid/tool.zip", "sha256": sha256(archive)}

    def test_bad_cached_checksum_does_not_install(self):
        package = self.package()
        (self.cache / "tool.zip").write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "checksum"):
            sync_tools.install("test", package, self.cache, self.tools)
        self.assertFalse((self.tools / "test").exists())

    def test_zip_traversal_is_validated_before_writing(self):
        self.package({"ok": b"ok", "../escape": b"bad"})
        output = self.root / "output"
        with self.assertRaises(ValueError):
            sync_tools.unpack(self.cache / "tool.zip", output)
        self.assertFalse(output.exists())

    def test_existing_directory_is_preserved(self):
        package = self.package()
        target = self.tools / "test"
        target.mkdir(parents=True)
        (target / "mine").write_text("keep")
        with self.assertRaisesRegex(ValueError, "Existing"):
            sync_tools.install("test", package, self.cache, self.tools)
        self.assertEqual((target / "mine").read_text(), "keep")

    def test_verified_package_is_reusable(self):
        package = self.package()
        sync_tools.install("test", package, self.cache, self.tools)
        sync_tools.install("test", package, self.cache, self.tools)
        self.assertEqual((self.tools / "test/bin/tool.exe").read_bytes(), b"fixture")
        self.assertEqual(json.loads((self.tools / "test/.package.json").read_text())["package"], package)
        (self.tools / "test/bin/tool.exe").write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "modified"):
            sync_tools.install("test", package, self.cache, self.tools)


if __name__ == "__main__":
    unittest.main()
