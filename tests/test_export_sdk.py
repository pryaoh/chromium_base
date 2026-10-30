import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import export_sdk


class ExportTests(unittest.TestCase):
    def test_existing_destination_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'sdk'
            dest.mkdir()
            (dest / 'keep').write_text('original')
            with self.assertRaises(FileExistsError):
                export_sdk.check_destination(dest, [Path(tmp) / 'source'])
            self.assertEqual((dest / 'keep').read_text(), 'original')

    def test_destination_cannot_contain_or_overlap_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source'
            with self.assertRaises(ValueError):
                export_sdk.check_destination(source / 'sdk', [source])

    def test_relative_paths_cannot_escape_allowed_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                export_sdk.contained(Path(tmp) / '../escape', Path(tmp))

    def test_extensionless_libcxx_and_generated_headers_are_selected(self):
        self.assertTrue(export_sdk.is_header('third_party/libc++/src/include/vector'))
        self.assertTrue(export_sdk.is_header('buildtools/third_party/libc++/__config_site'))
        self.assertTrue(export_sdk.is_header('base/feature_buildflags.h'))
        self.assertFalse(export_sdk.is_header('base/example.cc'))
        self.assertFalse(export_sdk.is_header('base/test/data/file.json'))

    def test_archive_failure_does_not_publish_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.lib'
            source.write_bytes(b'!<thin>\n')
            dest = root / 'dest.lib'
            with mock.patch.object(export_sdk, 'run', side_effect=RuntimeError('librarian failed')):
                with self.assertRaises(RuntimeError):
                    export_sdk.materialize(source, dest, ['a.obj'], 'lld-link', root)
            self.assertFalse(dest.exists())

    def test_regular_archive_is_copied_without_rearchiving(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, dest = root / 'source.rlib', root / 'dest.rlib'
            source.write_bytes(b'!<arch>\ncontents')
            export_sdk.materialize(source, dest, None, 'not-called', root)
            self.assertEqual(source.read_bytes(), dest.read_bytes())

    def test_cmake_string_rejects_list_or_expression_injection(self):
        for value in ('a;b', '$<TARGET_FILE:evil>', '${ENV}', 'line\nbreak'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                export_sdk.cmake_quote(value)

    def test_export_passes_source_to_existing_toolchain_verifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            build = source / 'out/build'
            build.mkdir(parents=True)
            (build / 'args.gn').write_text('target_cpu = "x64"\nis_clang = true\n'
                'use_lld = true\nuse_custom_libcxx = true\nis_debug = false\n'
                'is_component_build = false\nclang_base_path = "' +
                (root / 'llvm').as_posix() + '"\n')
            args = SimpleNamespace(source=source, build_dir=build, destination=root / 'sdk',
                                   allow_unmanaged_build=True, toolchain='external')
            with mock.patch.object(export_sdk, 'verify_snapshot', return_value={}), \
                 mock.patch('chromium_base.verify_generated_toolchain', side_effect=RuntimeError('stop')) as verify:
                with self.assertRaisesRegex(RuntimeError, 'stop'):
                    export_sdk.export(args)
                self.assertEqual(verify.call_args.args[0]['source'], str(source.resolve()))

    def test_runtime_dependencies_reject_escape_and_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            build = Path(tmp)
            (build / 'base.dll').write_bytes(b'MZ')
            self.assertEqual(export_sdk.runtime_files(['consumer.exe', 'consumer.exe.pdb',
                                                       './base.dll', './base.dll.pdb'], build),
                             [build / 'base.dll'])
            for entries in (['../escape.dll'], ['missing.dll'], ['unknown.dat']):
                with self.subTest(entries=entries), self.assertRaises((ValueError, FileNotFoundError)):
                    export_sdk.runtime_files(entries, build)

    def test_runtime_deployment_rejects_flattening_collisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            build = Path(tmp)
            (build / 'nested').mkdir()
            (build / 'base.dll').write_bytes(b'MZ')
            (build / 'nested/base.dll').write_bytes(b'MZ')
            with self.assertRaisesRegex(ValueError, 'collision'):
                export_sdk.runtime_files(['base.dll', 'nested/base.dll'], build)


if __name__ == '__main__':
    unittest.main()
