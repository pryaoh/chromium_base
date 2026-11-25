import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


spec = importlib.util.spec_from_file_location('net_export', Path(__file__).resolve().parents[1] / 'export_sdk.py')
net_export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(net_export)


class NetExportTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.source = self.root / 'src'
        self.build = self.source / 'out/sh'
        self.build.mkdir(parents=True)

    def test_consumer_tracks_net_defines_and_source_and_generated_include_order(self):
        (self.build / 'ws2_32.lib').touch()  # A stale file cannot redefine a system library.
        raw = {'net_consumer.exe': {'file': 'obj/probe.obj', 'command': 'lld-link.exe @probe.rsp'}}
        expanded = {'net_consumer.exe': {'command': 'lld-link.exe "obj/probe.obj net.dll.lib ws2_32.lib"'}}
        target = dict(cflags=['/MD'], cflags_cc=['-I../../third_party/libc++/src/include'],
                      defines=['COMPONENT_BUILD', 'USE_LIBCXX_MODULES', 'NET_FLAG=1'],
                      include_dirs=['//', '//out/sh/gen', '//out/sh/gen/net'])
        contract = net_export.get_contract('net', target, raw, expanded, self.source, self.build, ['net.dll.lib'])
        self.assertEqual(contract['includes'], ['include/source', 'include/generated',
                          'include/generated/net', 'include/source/third_party/libc++/src/include'])
        self.assertEqual(contract['defines'], ['COMPONENT_BUILD', 'NET_FLAG=1'])
        self.assertEqual(contract['link']['inputs'], ['net.dll.lib'])
        self.assertEqual(contract['link']['system_libs'], ['ws2_32.lib'])
        target['defines'].append('NET_IMPLEMENTATION')
        with self.assertRaisesRegex(ValueError, 'Implementation'):
            net_export.get_contract('net', target, raw, expanded, self.source, self.build, ['net.dll.lib'])

    def test_runtime_preserves_data_paths_and_excludes_probe_and_debug_symbols(self):
        (self.build / 'net.dll').touch()
        (self.build / 'locales').mkdir()
        (self.build / 'locales/en.pak').touch()
        deps = self.build / 'net_consumer.runtime_deps'
        deps.write_text('./net_consumer.exe\nnet.dll\nnet.dll.pdb\n./locales/\n')
        self.assertEqual(list(net_export.runtime_inputs(self.build, 'net')), ['bin/net.dll', 'bin/locales/en.pak'])
        deps.write_text('net.dll\n../outside')
        with self.assertRaisesRegex(ValueError, 'escapes'):
            net_export.runtime_inputs(self.build, 'net')
        deps.write_text('net.dll\nicudtl.dat')
        with self.assertRaisesRegex(FileNotFoundError, 'icudtl'):
            net_export.runtime_inputs(self.build, 'net')

    def test_compatible_external_base_requires_matching_abi_and_artifacts(self):
        sdk = self.root / 'base-sdk'
        (sdk / 'lib/cmake/ChromiumBase').mkdir(parents=True)
        (sdk / 'lib/cmake/ChromiumBase/ChromiumBaseConfig.cmake').touch()
        (sdk / 'lib/base.dll.lib').write_bytes(b'!<arch>\nbase lib')
        src = self.build / 'base.dll.lib'
        src.write_bytes((sdk / 'lib/base.dll.lib').read_bytes())
        art = net_export.sha256(src)
        manifest = dict(source=dict(revision='rev'), compiler_sha256='cc', linker_sha256='ld',
                        configuration='windows-x64-shared-release', compile_options=['/MD'],
                        defines=['COMPONENT_BUILD'], artifacts=[dict(path='lib/base.dll.lib', sha256=art, source_sha256=art)])
        net_export.write_json(sdk / 'sdk-manifest.json', manifest)
        contract = dict(flags=['/MD'], defines=['COMPONENT_BUILD'])
        args = (sdk, 'rev', 'cc', 'ld', contract, {'lib/base.dll.lib': src})
        self.assertEqual(net_export.check_base_sdk(*args), net_export.sha256(sdk / 'sdk-manifest.json'))
        (sdk / 'lib/base.dll.lib').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'different artifact'):
            net_export.check_base_sdk(*args)
        contract['defines'].append('DCHECK_ALWAYS_ON=1')
        with self.assertRaisesRegex(ValueError, 'ABI'):
            net_export.check_base_sdk(*args)

    def test_exports_both_targets_with_relocatable_config_and_integrity_inventory(self):
        llvm = self.root / 'llvm'
        (llvm / 'bin').mkdir(parents=True)
        for tool in ('clang-cl.exe', 'lld-link.exe'):
            (llvm / 'bin' / tool).touch()
        (self.root / 'rust').mkdir()
        args_text = ['target_cpu = "x64"', 'is_component_build = true', 'is_debug = false',
                     'is_clang = true', 'use_lld = true', 'use_custom_libcxx = true',
                     f'clang_base_path = "{llvm.as_posix()}"',
                     f'rust_sysroot_absolute = "{(self.root / "rust").as_posix()}"']
        (self.build / 'args.gn').write_text('\n'.join(args_text))
        (self.source / 'net').mkdir()
        (self.source / 'net/request.h').write_text('#pragma once')
        generated = self.build / 'gen/net'
        generated.mkdir(parents=True)
        (generated / 'features.h').write_text('#define ALLOW 1')
        net_export.write_json(self.source / net_export.INVENTORY,
                              dict(schema=1, revision='pinned', files={'net/request.h': net_export.sha256(self.source / 'net/request.h')}))
        desc, raw, expanded = {}, {}, {}
        for component in ('base', 'net'):
            program = component + '_consumer'
            inputs = ['base'] if component == 'base' else ['net', 'base_i18n', 'base']
            for name in inputs:
                (self.build / (name + '.dll.lib')).write_bytes(b'!<arch>\n' + name.encode())
                (self.build / (name + '.dll')).write_bytes(b'MZ')
            deps = [program + '.exe', *(x + '.dll' for x in inputs)]
            if component == 'net':
                (self.build / 'icudtl.dat').write_bytes(b'icu data')
                deps.append('icudtl.dat')
            (self.build / (program + '.runtime_deps')).write_text('\n'.join(deps))
            desc['//sdk_probe:' + program] = dict(defines=['COMPONENT_BUILD'], cflags=['/MD'],
                cflags_cc=[], include_dirs=['//', '//out/sh/gen'])
            command = f'"{(llvm / "bin/lld-link.exe").as_posix()}" '
            raw[program + '.exe'] = dict(file='probe.obj', command=command + '@probe.rsp')
            content = ' '.join(['probe.obj', *(x + '.dll.lib' for x in inputs), 'ws2_32.lib'])
            expanded[program + '.exe'] = dict(command=command + '"' + content + '"')
        sdk = self.root / 'sdk'
        args = net_export.argparse.Namespace(source=self.source, build_dir=self.build, destination=sdk, jobs=1,
                                             gn=self.root / 'gn', ninja=self.root / 'ninja', base_sdk=None)
        with mock.patch.object(net_export, 'verify_generated_toolchain'), \
             mock.patch.object(net_export.base_export, 'compdb', side_effect=[raw, expanded]), \
             mock.patch.object(net_export.base_export, 'run', side_effect=[
                 '', json.dumps(desc), 'base.dll.lib: solink\nnet.dll.lib: solink\nbase_i18n.dll.lib: solink\n']):
            self.assertEqual(net_export.export(args), sdk)
        config = (sdk / 'lib/cmake/ChromiumNet/ChromiumNetConfig.cmake').read_text()
        self.assertIn('ChromiumBase::base', config)
        self.assertIn('"${_cn_root}/lib/net.dll.lib"', config)
        self.assertIn('"${_cn_root}/lib/base_i18n.dll.lib"', config)
        self.assertNotIn('lib/base.dll.lib', config)
        self.assertNotIn(self.root.as_posix(), config)
        manifest = json.loads((sdk / 'sdk-manifest.json').read_text())
        self.assertCountEqual(manifest['runtime_files'],
                              ['bin/base.dll', 'bin/net.dll', 'bin/base_i18n.dll', 'bin/icudtl.dat'])
        files = json.loads((sdk / 'files.sha256.json').read_text())
        for name in ('include/generated/net/features.h', 'include/source/net/request.h', 'bin/base.dll', 'bin/net.dll',
                     'lib/cmake/ChromiumBase/chromium-base-toolchain.cmake', 'lib/base.dll.lib', 'lib/net.dll.lib'):
            self.assertEqual(files[name], net_export.sha256(sdk / name))

    @unittest.skipUnless(shutil.which('cmake') and shutil.which('ninja') and (shutil.which('cl') or shutil.which('cc')),
                         'Requires CMake, Ninja and a configured C compiler')
    def test_relocated_cmake_consumer_deploys_runtime_data_and_base(self):
        stage = self.root / 'staging'
        base_dir = stage / 'lib/cmake/ChromiumBase'
        base_dir.mkdir(parents=True)
        (base_dir / 'ChromiumBaseConfig.cmake').write_text(
            'add_library(ChromiumBase::base INTERFACE IMPORTED GLOBAL)\n'
            'set_property(TARGET ChromiumBase::base PROPERTY INTERFACE_COMPILE_DEFINITIONS BASE_ABI)\n'
            'get_filename_component(_root "${CMAKE_CURRENT_LIST_DIR}/../../.." ABSOLUTE)\n'
            'set_property(TARGET ChromiumBase::base PROPERTY CHROMIUM_BASE_RUNTIME_FILES "${_root}/bin/base.dll")\n'
            'include("${CMAKE_CURRENT_LIST_DIR}/chromium-base-deploy.cmake")\n')
        shutil.copy2(net_export.ROOT / 'base/cmake/chromium-base-deploy.cmake', base_dir)
        (stage / 'bin/locales').mkdir(parents=True)
        for name in ('base.dll', 'net.dll', 'locales/en.pak'):
            (stage / 'bin' / name).write_text(name)
        contract = dict(includes=[], flags=[], defines=['NET_ABI'], link=dict(options=[], system_libs=[]))
        net_export.write_net_config(stage, contract, [], ['bin/net.dll', 'bin/locales/en.pak'], None)
        sdk = self.root / 'relocated sdk'
        stage.rename(sdk)
        project = self.root / 'consumer'
        project.mkdir()
        (project / 'main.c').write_text('#if !defined(BASE_ABI) || !defined(NET_ABI)\n'
                                       '#error Missing transitive SDK definitions\n#endif\nint main(void){return 0;}\n')
        (project / 'CMakeLists.txt').write_text(
            'cmake_minimum_required(VERSION 3.22)\nproject(consumer LANGUAGES C)\n'
            'find_package(ChromiumNet CONFIG REQUIRED)\n'
            'add_executable(check_consumer main.c)\n'
            'target_link_libraries(check_consumer PRIVATE ChromiumNet::net)\n'
            'chromium_net_deploy_runtime(check_consumer)\n')
        build = self.root / 'consumer-build'
        for args in (['-S', str(project), '-B', str(build), '-G', 'Ninja', f'-DCMAKE_PREFIX_PATH={sdk}'],
                     ['--build', str(build), '--config', 'Release']):
            result = subprocess.run(['cmake', *args], capture_output=True, text=True, errors='replace')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        outputs = list(build.rglob('net.dll'))
        self.assertEqual(len(outputs), 1)
        for name in ('base.dll', 'net.dll', 'locales/en.pak'):
            self.assertEqual((outputs[0].parent / name).read_text(), name)


if __name__ == '__main__':
    unittest.main()
