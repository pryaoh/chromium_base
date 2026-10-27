import json
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import chromium_base as driver


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "chromium_base.py"


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source with spaces"
        self.llvm = self.root / "LLVM $custom"

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args], text=True,
            capture_output=True, check=False,
        )

    def plan(self, *args):
        result = self.run_cli("plan", "--source", str(self.source), *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_external_default_selects_explicit_root_without_creating_files(self):
        result = self.plan("--llvm-root", str(self.llvm))
        self.assertEqual(result["toolchain"], "external")
        self.assertEqual(Path(result["llvm_root"]), self.llvm)
        self.assertIn('clang_use_chrome_plugins = false', result["gn_args"])
        self.assertIn(r'\$custom', result["gn_args"])
        self.assertFalse(self.source.exists())
        self.assertFalse(self.llvm.exists())

    def test_chromium_uses_checkout_and_leaves_plugin_defaults(self):
        result = self.plan("--toolchain", "chromium")
        self.assertEqual(Path(result["llvm_root"]), self.source / "third_party/llvm-build/Release+Asserts")
        self.assertNotIn("clang_base_path", result["gn_args"])
        self.assertNotIn("clang_use_chrome_plugins", result["gn_args"])
        self.assertIn("use_custom_libcxx = true", result["gn_args"])

    def test_all_modes_have_independent_output_directories_and_correct_flags(self):
        outputs = set()
        for mode in ("external", "chromium"):
            for linkage in ("static", "shared"):
                for config in ("release", "debug"):
                    args = ["--toolchain", mode, "--linkage", linkage, "--configuration", config]
                    if mode == "external":
                        args += ["--llvm-root", str(self.llvm)]
                    result = self.plan(*args)
                    outputs.add(result["output"])
                    self.assertIn("is_component_build = " + ("true" if linkage == "shared" else "false"), result["gn_args"])
                    self.assertIn("is_debug = " + ("true" if config == "debug" else "false"), result["gn_args"])
        self.assertEqual(len(outputs), 8)

    def test_chromium_rejects_an_external_override(self):
        result = self.run_cli("plan", "--source", str(self.source), "--toolchain", "chromium", "--llvm-root", str(self.llvm))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--llvm-root", result.stderr)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = driver.make_plan(self.root / "src", llvm_root=self.root / "LLVM with spaces")
        self.output = Path(self.plan["output"])
        self.report = {
            "ok": True, "errors": [], "warnings": [],
            "gn": str(self.root / "gn.exe"),
            "depot_tools": str(self.root / "depot tools"),
            "identity": {"revision": "a" * 40, "compiler_versions": {"clang-cl": "clang version 23.1.0"}},
        }

    def successful_gn(self, command, **kwargs):
        self.assertEqual(command[1], "gen")
        self.assertEqual(command[2], str(self.output))
        self.assertIn("--fail-on-unused-args", command)
        self.assertEqual(kwargs["env"]["DEPOT_TOOLS_WIN_TOOLCHAIN"], "0")
        self.assertEqual(Path(kwargs["cwd"]), Path(self.plan["source"]))
        (self.output / "build.ninja").write_text("# fixture", encoding="utf-8")
        llvm = Path(self.plan["llvm_root"]).as_posix()
        (self.output / "toolchain.ninja").write_text(
            f'command = "{llvm}/bin/clang-cl.exe"\ncommand = "{llvm}/bin/lld-link.exe"\n', encoding="utf-8")
        return 0

    def configure_success(self):
        with patch.object(driver, "run_command", side_effect=self.successful_gn):
            driver.configure(self.plan, self.report)

    def test_doctor_reports_all_missing_inputs_without_falling_back(self):
        # An existing bundled compiler cannot satisfy an explicitly selected external path.
        bundled = Path(self.plan["source"]) / "third_party/llvm-build/Release+Asserts/bin"
        bundled.mkdir(parents=True)
        (bundled / "clang-cl.exe").write_bytes(b"not executable")
        report = driver.inspect_environment(self.plan, self.root / "missing depot", self.root / "missing gn")
        self.assertFalse(report["ok"])
        errors = "\n".join(report["errors"])
        self.assertIn("clang-cl.exe", errors)
        self.assertIn(str(Path(self.plan["llvm_root"])), errors)
        self.assertIn("autoninja.py", errors)
        self.assertIn("base/BUILD.gn", errors)
        self.assertFalse(self.output.exists())

    def test_configure_preserves_an_unowned_directory(self):
        self.output.mkdir(parents=True)
        args = self.output / "args.gn"
        args.write_text("user configuration", encoding="utf-8")
        with patch.object(driver, "run_command") as run:
            with self.assertRaisesRegex(ValueError, "unmanaged"):
                driver.configure(self.plan, self.report)
            run.assert_not_called()
        self.assertEqual(args.read_text(), "user configuration")

    def test_generation_failure_is_recorded_and_cannot_be_built(self):
        with patch.object(driver, "run_command", return_value=7):
            with self.assertRaises(subprocess.CalledProcessError) as error:
                driver.configure(self.plan, self.report)
        self.assertEqual(error.exception.returncode, 7)
        manifest = json.loads((self.output / ".chromium-base.json").read_text())
        self.assertEqual(manifest["state"], "configure_failed")
        with self.assertRaisesRegex(ValueError, "configure"):
            driver.build(self.plan, self.report)

    def test_build_uses_selected_arguments_and_records_success(self):
        self.configure_success()
        def build_process(command, **kwargs):
            self.assertEqual(command, [sys.executable, str(self.root / "depot tools/autoninja.py"), "-C", str(self.output), "base"])
            return 0
        with patch.object(driver, "run_command", side_effect=build_process):
            driver.build(self.plan, self.report)
        manifest = json.loads((self.output / ".chromium-base.json").read_text())
        self.assertEqual(manifest["state"], "built")
        self.assertEqual(manifest["identity"]["revision"], "a" * 40)

    def test_modified_args_are_preserved_and_block_build(self):
        self.configure_success()
        path = self.output / "args.gn"
        path.write_text("manually modified", encoding="utf-8")
        with patch.object(driver, "run_command") as run:
            with self.assertRaisesRegex(ValueError, "args.gn"):
                driver.build(self.plan, self.report)
            run.assert_not_called()
        self.assertEqual(path.read_text(), "manually modified")

    def test_changed_source_or_compiler_blocks_reuse(self):
        self.configure_success()
        for changed in ({"revision": "b" * 40}, {"compiler_versions": {"clang-cl": "clang version 24.0.0"}}):
            report = dict(self.report, identity=dict(self.report["identity"], **changed))
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, "identity"):
                driver.build(self.plan, report)

    def test_wrong_compiler_in_generated_rules_prevents_success(self):
        def wrong_gn(command, **kwargs):
            self.successful_gn(command, **kwargs)
            (self.output / "toolchain.ninja").write_text("command = other/clang-cl.exe\n", encoding="utf-8")
            return 0
        with patch.object(driver, "run_command", side_effect=wrong_gn):
            with self.assertRaisesRegex(ValueError, "toolchain.ninja"):
                driver.configure(self.plan, self.report)
        self.assertEqual(json.loads((self.output / ".chromium-base.json").read_text())["state"], "configure_failed")

    def test_build_failure_clears_previous_success(self):
        self.configure_success()
        with patch.object(driver, "run_command", return_value=9):
            with self.assertRaises(subprocess.CalledProcessError):
                driver.build(self.plan, self.report)
        self.assertEqual(json.loads((self.output / ".chromium-base.json").read_text())["state"], "build_failed")

    def test_doctor_failure_prevents_output_creation(self):
        report = dict(self.report, ok=False, errors=["missing LLVM"])
        with self.assertRaisesRegex(ValueError, "missing LLVM"):
            driver.configure(self.plan, report)
        self.assertFalse(self.output.exists())

    def test_bundled_shared_configuration_accepts_relative_ninja_paths(self):
        self.plan = driver.make_plan(self.root / "src", toolchain="chromium", linkage="shared")
        self.output = Path(self.plan["output"])
        def generate(command, **kwargs):
            self.successful_gn(command, **kwargs)
            relative = "../../../third_party/llvm-build/Release+Asserts/bin"
            (self.output / "toolchain.ninja").write_text(
                f"command = {relative}/clang-cl.exe\ncommand = {relative}/lld-link.exe\n", encoding="utf-8")
            return 0
        with patch.object(driver, "run_command", side_effect=generate):
            driver.configure(self.plan, self.report)

    def test_doctor_rejects_mismatched_tool_versions(self):
        llvm = Path(self.plan["llvm_root"])
        (llvm / "bin").mkdir(parents=True)
        for name in ("clang-cl", "lld-link", "llvm-lib"):
            (llvm / "bin" / (name + ".exe")).touch()
        def version(command, **kwargs):
            return "LLD 24.0.0" if "lld-link" in command[0] else "clang version 23.1.0"
        with patch.object(driver, "capture", side_effect=version), patch.object(driver, "windows_prerequisites", return_value=({}, [])):
            report = driver.inspect_environment(self.plan, self.root / "depot", self.root / "gn.exe")
        self.assertFalse(report["ok"])
        self.assertIn("mismatched major versions", "\n".join(report["errors"]))

    def test_cli_preserves_build_process_exit_code(self):
        with contextlib.redirect_stderr(io.StringIO()), patch.object(driver, "inspect_environment", return_value=self.report), patch.object(driver, "build", side_effect=subprocess.CalledProcessError(17, ["autoninja"])):
            self.assertEqual(driver.main(["build", "--source", str(self.root / "src"), "--llvm-root", str(self.root / "llvm")]), 17)

    def test_external_llvm_on_another_drive_accepts_absolute_tool_paths(self):
        with patch.object(driver.os.path, "relpath", side_effect=ValueError("path is on another mount")):
            self.configure_success()

    def ready_doctor_report(self, toolchain_text=None):
        self.plan = driver.make_plan(self.root / "src", llvm_root=self.root / "LLVM")
        source = Path(self.plan["source"])
        for name in (".gn", "DEPS", "base/BUILD.gn", "build/config/BUILDCONFIG.gn"):
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        llvm = Path(self.plan["llvm_root"])
        (llvm / "bin").mkdir(parents=True)
        for name in ("clang-cl.exe", "lld-link.exe"):
            (llvm / "bin" / name).touch()
        gn = self.root / "gn.exe"
        gn.touch()
        depot = self.root / "depot"
        depot.mkdir()
        (depot / "autoninja.py").touch()
        if toolchain_text is not None:
            path = source / "build/toolchain/toolchain.gni"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(toolchain_text, encoding="utf-8")
        def capture(command, **kwargs):
            if command[0] == "git":
                if "--show-toplevel" in command:
                    return str(source)
                return "" if "status" in command else "a" * 40
            if "clang-cl" in command[0]:
                return "clang version 23.1.0"
            if "lld-link" in command[0]:
                return "LLD 23.1.0"
            return "2400"
        with patch.object(driver, "capture", side_effect=capture), patch.object(driver, "windows_prerequisites", return_value=({}, [])):
            return driver.inspect_environment(self.plan, depot, gn)

    def test_doctor_accepts_upstream_lld_librarian_without_llvm_lib(self):
        report = self.ready_doctor_report()
        self.assertTrue(report["ok"], report["errors"])

    def test_doctor_explains_upstream_unquoted_llvm_path_limit(self):
        with patch.object(driver, "windows_prerequisites", return_value=({}, [])):
            report = driver.inspect_environment(self.plan, self.root / "depot", self.root / "gn.exe")
        self.assertIn("whitespace", "\n".join(report["errors"]))

    def test_conditional_clang_versions_defer_compatibility_to_gn(self):
        report = self.ready_doctor_report('''if (llvm_force_head_revision) {
  clang_version = "24"
} else {
  clang_version = "23"
}
''')
        self.assertTrue(report["ok"], report["errors"])
        self.assertIn("conditional", "\n".join(report["warnings"]))

    def test_unambiguous_wrong_clang_major_is_rejected(self):
        report = self.ready_doctor_report('clang_version = "24"\n')
        self.assertFalse(report["ok"])
        self.assertIn("expects Clang major 24", "\n".join(report["errors"]))

    def test_generated_rules_reject_extra_parent_prefix_and_executable_suffix(self):
        self.plan = driver.make_plan(self.root / "src", toolchain="chromium")
        self.output = Path(self.plan["output"])
        self.output.mkdir(parents=True)
        (self.output / "build.ninja").touch()
        for root, suffix in (
            ("../../../../third_party/llvm-build/Release+Asserts/bin", ""),
            ("other/../../../third_party/llvm-build/Release+Asserts/bin", ""),
            ("../../../third_party/llvm-build/Release+Asserts/bin", ".old"),
        ):
            with self.subTest(root=root, suffix=suffix):
                (self.output / "toolchain.ninja").write_text(
                    f"command = {root}/clang-cl.exe{suffix}\ncommand = {root}/lld-link.exe{suffix}\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "toolchain.ninja"):
                    driver.verify_generated_toolchain(self.plan)


if __name__ == "__main__":
    unittest.main()
