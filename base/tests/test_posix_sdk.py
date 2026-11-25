import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import call, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_posix_sdk as sdk


class ToolInstallTests(unittest.TestCase):
    def test_macos_installs_otool_package_after_clang(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "DEPS").write_text("'gn_version': 'test'")
            with zipfile.ZipFile(work / "gn.zip", "w") as archive:
                archive.writestr("gn", b"")
            with patch.object(sdk, "SOURCE", work), patch.object(sdk, "WORK", work), \
                 patch.object(sdk, "run") as run:
                sdk.install_tools("Darwin")
            updater = "tools/clang/scripts/update.py"
            run.assert_has_calls([call(sys.executable, updater),
                                  call(sys.executable, updater, "--package", "objdump")])


class SharedLibraryTests(unittest.TestCase):
    def test_exports_native_components_and_only_links_direct_dependencies(self):
        for host, suffix in (("Linux", ".so"), ("Darwin", ".dylib")):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                build = root / "out/sdk-shared"
                build.mkdir(parents=True)
                names = [f"lib{name}{suffix}" for name in ("base", "direct", "transitive")]
                for name in names:
                    (build / name).write_bytes(name.encode())
                (build / "sdk_probe.runtime_deps").write_text("\n".join([*names, "gen/table.h"]))
                (build / "probe.o").touch()
                (build / "sdk_probe.rsp").write_text("probe.o " + " ".join(names[:2]))
                compdb = [{"output": "sdk_probe", "command": "clang++ @sdk_probe.rsp", "file": "probe.o"}]
                target = {"include_dirs": [], "defines": ["COMPONENT_BUILD"], "cflags": [], "cflags_cc": []}
                stage = root / "relocated sdk"
                with patch.object(sdk.platform, "system", return_value=host), \
                     patch.object(sdk, "output", return_value=json.dumps(compdb)):
                    sdk.package_library(target, stage, "shared", build)
                lib = stage / "lib"
                for name in names:
                    self.assertEqual((lib / name).read_bytes(), name.encode())
                config = (lib / "cmake/ChromiumBase/ChromiumBaseConfig.cmake").read_text()
                self.assertIn("SHARED IMPORTED", config)
                self.assertIn(f'IMPORTED_LOCATION "${{_chromium_base_root}}/lib/{names[0]}"', config)
                self.assertIn(f'"${{_chromium_base_root}}/lib/{names[1]}"', config)
                self.assertNotIn(names[2], config)
                self.assertNotIn(str(build), config)

    def test_requires_base_in_runtime_deps(self):
        with tempfile.TemporaryDirectory() as tmp:
            build = Path(tmp)
            (build / "sdk_probe.runtime_deps").write_text("./sdk_probe\n")
            with self.assertRaisesRegex(ValueError, "Missing Chromium base"):
                sdk.copy_component_libraries(build, build, ".so")


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
            with patch.object(sdk.platform, "system", return_value="Linux"), \
                 patch.object(sdk.subprocess, "run", return_value=failure):
                with self.assertRaisesRegex(RuntimeError, r"broken\.a.*script line 3"):
                    sdk.merge_library(inputs, lib)
