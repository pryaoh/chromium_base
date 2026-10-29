"""Build/run the consumer fixture and audit its real Ninja dependencies.

Use an x64 VS Developer shell, or --environment-file from the verified GN build.
The SDK should already have been moved to a different directory before this run.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--llvm-root', type=Path, required=True)
    parser.add_argument('--cmake', required=True)
    parser.add_argument('--ninja', required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--environment-file', type=Path)
    parser.add_argument('--original-source', type=Path, default=ROOT / 'vendor/chromium')
    args = parser.parse_args()
    sdk, work = args.sdk.resolve(), args.work.resolve()
    if work.exists():
        raise ValueError('Use a fresh verification work directory')
    env = dict(os.environ)
    if args.environment_file:
        for entry in args.environment_file.read_bytes().decode('utf-8').split('\0'):
            if '=' in entry:
                key, value = entry.split('=', 1)
                env[key] = value
    source = work / 'source'
    shutil.copytree(ROOT / 'tests/sdk_consumer', source)
    build = work / 'build'
    def run(command, name):
        result = subprocess.run([str(x) for x in command], env=env, capture_output=True,
                                encoding='utf-8', errors='replace')
        (work / (name + '.log')).write_text(result.stdout + result.stderr, encoding='utf-8')
        if result.returncode:
            print((result.stdout + result.stderr)[-7000:])
            raise RuntimeError(f'{name} failed: {result.returncode}')
        print(name + ': OK', flush=True)
        return result.stdout
    run([args.cmake, '-S', source, '-B', build, '-G', 'Ninja',
         '-DCMAKE_MAKE_PROGRAM=' + str(Path(args.ninja).resolve()),
         '-DCMAKE_TOOLCHAIN_FILE=' + str(sdk / 'lib/cmake/ChromiumBase/chromium-base-toolchain.cmake'),
         '-DCHROMIUM_BASE_LLVM_ROOT=' + str(args.llvm_root.resolve()),
         '-DCMAKE_PREFIX_PATH=' + str(sdk), '-DCMAKE_BUILD_TYPE=Release'], 'configure')
    run([args.cmake, '--build', build, '--verbose'], 'build')
    output = run([build / 'sdk_consumer.exe'], 'execute')
    if 'CHROMIUM BASE: JSON, files, task runner OK' not in output:
        raise ValueError('Consumer verification output missing')
    dependencies = run([args.ninja, '-C', build, '-t', 'deps'], 'dependencies')
    commands = run([args.ninja, '-C', build, '-t', 'commands'], 'commands')
    original = str(args.original_source.resolve()).replace('\\', '/').lower()
    for name, text in [('dependencies', dependencies), ('commands', commands),
                       ('package', (sdk / 'lib/cmake/ChromiumBase/ChromiumBaseConfig.cmake').read_text())]:
        if original in text.replace('\\', '/').lower():
            raise ValueError('Original source/build path leaked into ' + name)
    dep_paths = [Path(line.strip()).resolve() for line in dependencies.splitlines()
                 if line.startswith('    ') and line.strip()]
    system_includes = [Path(value).resolve() for key, values in env.items()
                       if key.upper() in ('INCLUDE', 'EXTERNAL_INCLUDE')
                       for value in values.split(';') if value]
    allowed = [sdk, source, args.llvm_root.resolve(), *system_includes]
    unexpected = [str(path) for path in dep_paths
                  if not any(path.is_relative_to(root) for root in allowed)]
    if unexpected:
        raise ValueError('Headers outside SDK/compiler/system/fixture: ' + ', '.join(unexpected[:10]))
    if not any(path.is_relative_to(sdk / 'include/generated') for path in dep_paths):
        raise ValueError('Ninja did not record exported generated headers')
    if not any(path.is_relative_to(sdk / 'include/source/third_party/libc++') for path in dep_paths):
        raise ValueError('Consumer did not use the exported libc++ headers')
    summary = dict(sdk=str(sdk), header_dependencies=len(dep_paths),
                   output=output.strip(), original_source_references=False)
    (work / 'verification.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
