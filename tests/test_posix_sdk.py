from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_posix_sdk as sdk


class ArchiveTests(unittest.TestCase):
    def test_macos_archive_inputs_follow_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp)
            path = scratch / "library.rlib"
            for magic, command in [(b"!<arch>\n", "addlib"), (b"!<thin>\n", "addlib"),
                                   (b"BC\xc0\xde", "addmod"), (b"\xde\xc0\x17\x0b", "addmod"),
                                   (bytes.fromhex("cffaedfe0c0000010000000001000000"), "addmod")]:
                with self.subTest(header=magic):
                    path.write_bytes(magic)
                    self.assertEqual(sdk.mac_archive_input(path, scratch, 0), (command, path))
            path.write_bytes(b"invalid")
            with self.assertRaisesRegex(ValueError, r"library\.rlib.*696e76616c6964"):
                sdk.mac_archive_input(path, scratch, 0)

    def test_universal_archive_uses_arm64_slice(self):
        def lipo(command, check):
            self.assertEqual(command[:-1], ["xcrun", "lipo", fat, "-thin", "arm64", "-output"])
            self.assertTrue(check)
            command[-1].write_bytes(b"!<arch>\n")

        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp)
            fat = scratch / "universal.a"
            fat.write_bytes(bytes.fromhex("cafebabe"))
            with patch.object(sdk.subprocess, "run", side_effect=lipo):
                command, sliced = sdk.mac_archive_input(fat, scratch, 0)
            self.assertEqual(command, "addlib")
            self.assertNotEqual(fat, sliced)
            self.assertEqual(sliced.read_bytes(), b"!<arch>\n")

    def test_mri_failure_identifies_original_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = Path(tmp)
            inputs = [lib / "first.a", lib / "broken.a"]
            for path in inputs:
                path.write_bytes(b"!<arch>\n")
            failure = subprocess.CompletedProcess([], 1, stderr="error: script line 3: invalid archive")
            with patch.object(sdk.subprocess, "run", return_value=failure):
                with self.assertRaisesRegex(RuntimeError, r"broken\.a.*script line 3"):
                    sdk.merge_library(inputs, lib)
