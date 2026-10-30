"""Audit PE imports and run a shared-SDK executable from an isolated DLL deployment."""

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def imports(dumpbin, image, env):
    result = subprocess.run([str(dumpbin), '/nologo', '/dependents', str(image)],
                            env=env, capture_output=True, text=True, errors='replace',
                            check=True, timeout=60)
    return sorted(set(re.findall(r'^\s+([\w.+-]+\.dll)\s*$', result.stdout,
                                 re.MULTILINE | re.IGNORECASE)))


def verify(sdk, executable, deployment, dumpbin, env):
    sdk, executable, deployment = (Path(p).resolve() for p in (sdk, executable, deployment))
    if deployment.exists():
        raise FileExistsError('Use a new deployment directory')
    manifest = json.loads((sdk / 'sdk-manifest.json').read_text(encoding='utf-8'))
    if manifest['configuration'] != 'windows-x64-shared-release':
        raise ValueError('Expected the shared Release SDK')
    runtime = manifest['runtime_files']
    expected = {item['path']: item['sha256'] for item in manifest['artifacts']}
    sources = []
    for name in runtime:
        path = (sdk / name).resolve()
        if not path.is_relative_to(sdk / 'bin') or path.suffix.lower() != '.dll':
            raise ValueError('Invalid SDK runtime path')
        if digest(path) != expected[name]:
            raise ValueError('Runtime hash mismatch: ' + name)
        # Verify the CMake deployment helper actually copied the correct DLL.
        deployed_by_cmake = executable.parent / path.name
        if digest(deployed_by_cmake) != expected[name]:
            raise ValueError('CMake runtime deployment mismatch: ' + path.name)
        sources.append(path)
    dependencies = imports(dumpbin, executable, env)
    if 'base.dll' not in {name.lower() for name in dependencies}:
        raise ValueError('Executable does not import base.dll; it may be statically linked')
    names = {path.name.lower() for path in sources}
    system = Path(os.environ['SystemRoot']) / 'System32'
    image_imports = {executable.name: dependencies}
    for path in sources:
        image_imports[path.name] = imports(dumpbin, path, env)
    for image, dlls in image_imports.items():
        for name in dlls:
            if (name.lower() not in names and
                    not name.lower().startswith(('api-ms-', 'ext-ms-')) and
                    not (system / name).is_file()):
                raise ValueError(f'Unresolved runtime dependency: {image} -> {name}')
    deployment.mkdir(parents=True)
    target = deployment / executable.name
    shutil.copy2(executable, target)
    for path in sources:
        shutil.copy2(path, deployment / path.name)
    clean_env = dict(env, PATH=str(system) + os.pathsep + os.environ['SystemRoot'])
    previous_mode = ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    try:
        success = subprocess.run([str(target)], cwd=deployment, env=clean_env,
                                 capture_output=True, encoding='utf-8', errors='strict', timeout=60)
        if success.returncode:
            raise RuntimeError(f'Isolated DLL execution failed: {success.returncode}: {success.stderr}')
        base_dll = next(path for path in deployment.iterdir() if path.name.lower() == 'base.dll')
        hidden = base_dll.with_suffix('.dll.disabled')
        base_dll.rename(hidden)
        try:
            failure = subprocess.run([str(target)], cwd=deployment, env=clean_env,
                                     capture_output=True, encoding='utf-8', errors='replace', timeout=60)
            if (failure.returncode & 0xffffffff) != 0xc0000135:
                raise RuntimeError(f'Missing DLL did not produce STATUS_DLL_NOT_FOUND: {failure.returncode}')
        finally:
            hidden.rename(base_dll)
    finally:
        ctypes.windll.kernel32.SetErrorMode(previous_mode)
    result = dict(configuration=manifest['configuration'], deployed_dlls=len(sources),
                  imports=image_imports, output=success.stdout.strip(),
                  missing_base_status='0xC0000135', path=clean_env['PATH'])
    (deployment / 'runtime-verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'imports'}, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--deployment', type=Path, required=True)
    parser.add_argument('--dumpbin', type=Path, required=True)
    parser.add_argument('--environment-file', type=Path)
    args = parser.parse_args()
    env = dict(os.environ)
    if args.environment_file:
        for entry in args.environment_file.read_bytes().decode('utf-8').split('\0'):
            if '=' in entry:
                key, value = entry.split('=', 1)
                env[key] = value
    verify(args.sdk, args.executable, args.deployment, args.dumpbin, env)


if __name__ == '__main__':
    main()
