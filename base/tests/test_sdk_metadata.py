import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sdk_metadata


class WindowsCommandTests(unittest.TestCase):
    def test_round_trip_quoted_paths_and_embedded_quotes(self):
        tokens = ['clang-cl.exe', 'C:\\SDK with spaces\\include\\',
                  '/DNAME="two words"', '', r'a\"b', 'plain', '/libpath:C:\Program Files\SDK']
        self.assertEqual(sdk_metadata.windows_split(subprocess.list2cmdline(tokens)), tokens)

    def test_unterminated_quote_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'quote'):
            sdk_metadata.windows_split('link.exe "broken')


class ContractTests(unittest.TestCase):
    def test_ninja_response_quoted_outside_at_sign(self):
        raw = 'lld-link.exe "/OUT:probe.exe" "@./probe.rsp"'
        expanded = 'lld-link.exe "/OUT:probe.exe" "probe.obj "path with spaces/a.lib" kernel32.lib"'
        command = sdk_metadata.expanded_command(raw, expanded)
        self.assertEqual(sdk_metadata.link_contract(command, ['probe.obj'])['inputs'],
                         ['path with spaces/a.lib'])

    def test_consumer_flags_exclude_internal_policy_plugins_and_modules(self):
        flags = ['/MT', '-fcomplete-member-pointers', '-Xclang', '-add-plugin',
                 '-Xclang', 'find-bad-constructs', '-fmodules',
                 '-fmodule-map-file=gen/build/modules/module.modulemap',
                 '/std:c++23preview', '/GR-', '-I../../third_party/libc++/src/include']
        clean, includes = sdk_metadata.consumer_flags(flags)
        self.assertEqual(clean, ['/MT', '-fcomplete-member-pointers', '/std:c++23preview', '/GR-'])
        self.assertEqual(includes, ['../../third_party/libc++/src/include'])

    def test_invalid_split_flag_is_not_silently_ignored(self):
        with self.assertRaises(ValueError):
            sdk_metadata.consumer_flags(['-Xclang'])

    def test_reject_shared_or_debug_build_before_export(self):
        good = {'target_cpu': 'x64', 'is_clang': True, 'use_custom_libcxx': True,
                'is_component_build': False, 'is_debug': False, 'use_lld': True}
        sdk_metadata.validate_configuration(good)
        for key, value in (('is_debug', True), ('is_component_build', True),
                           ('target_cpu', 'arm64'), ('use_custom_libcxx', False),
                           ('is_asan', True), ('custom_toolchain', '//other')):
            with self.subTest(key=key), self.assertRaises(ValueError):
                sdk_metadata.validate_configuration(dict(good, **{key: value}))

    def test_shared_export_requires_explicit_selection_and_dynamic_crt(self):
        args = dict(target_cpu='x64', is_clang=True, use_lld=True,
                    use_custom_libcxx=True, is_component_build=True, is_debug=False)
        sdk_metadata.validate_configuration(args, linkage='shared')
        self.assertEqual(sdk_metadata.runtime_contract(['/MD'], ['COMPONENT_BUILD'], 'shared'),
                         'MultiThreadedDLL')
        with self.assertRaises(ValueError):
            sdk_metadata.runtime_contract(['/MT'], ['COMPONENT_BUILD'], 'shared')
        with self.assertRaises(ValueError):
            sdk_metadata.runtime_contract(['/MD'], [], 'shared')
        with self.assertRaises(ValueError):
            sdk_metadata.runtime_contract(['/MT'], ['COMPONENT_BUILD'], 'static')

    def test_link_inputs_skip_probe_but_preserve_runtime_objects_libraries_and_system_libs(self):
        command = 'python wrapper.py link-wrapper env False C:/LLVM/bin/lld-link.exe /OUT:consumer.exe /MACHINE:X64 obj/probe.obj obj/base/base.lib obj/runtime.obj obj/rust/libstd.rlib kernel32.lib /PDB:consumer.pdb /INCLUDE:required /SUBSYSTEM:CONSOLE,10.0'
        result = sdk_metadata.link_contract(command, ['obj/probe.obj'])
        self.assertEqual(result['inputs'], ['obj/base/base.lib', 'obj/runtime.obj', 'obj/rust/libstd.rlib'])
        self.assertEqual(result['system_libs'], ['kernel32.lib'])
        self.assertEqual(result['options'], ['/MACHINE:X64', '/INCLUDE:required'])

    def test_unexpanded_response_and_unexpected_input_are_rejected(self):
        for argument in ('@hidden.rsp', 'unknown.file'):
            with self.subTest(argument=argument), self.assertRaises(ValueError):
                sdk_metadata.link_contract('lld-link.exe ' + argument, [])

    def test_windows_nasm_object_suffix_is_a_runtime_input(self):
        result = sdk_metadata.link_contract('lld-link.exe /lib obj/crypto/aes-win.o', [])
        self.assertEqual(result['inputs'], ['obj/crypto/aes-win.o'])

    def test_root_level_import_libraries_are_not_system_libraries(self):
        result = sdk_metadata.link_contract('lld-link.exe base.dll.lib kernel32.lib', [],
                                           local_outputs=['base.dll.lib'])
        self.assertEqual(result['inputs'], ['base.dll.lib'])
        self.assertEqual(result['system_libs'], ['kernel32.lib'])


if __name__ == '__main__':
    unittest.main()
