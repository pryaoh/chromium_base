"""Interpret the Windows GN/Ninja consumer contract without executing its commands."""

import re


def windows_split(command):
    """Split MS CRT command-line quoting, including escaped quotes/backslashes."""
    result, token, quoted, started = [], [], False, False
    i = 0
    while i < len(command):
        char = command[i]
        if char.isspace() and not quoted:
            if started:
                result.append(''.join(token))
                token, started = [], False
            i += 1
            continue
        started = True
        if char == '\\':
            end = i
            while end < len(command) and command[end] == '\\':
                end += 1
            count = end - i
            if end < len(command) and command[end] == '"':
                token.extend('\\' * (count // 2))
                if count % 2:
                    token.append('"')
                else:
                    quoted = not quoted
                i = end + 1
            else:
                token.extend('\\' * count)
                i = end
        elif char == '"':
            quoted = not quoted
            i += 1
        else:
            token.append(char)
            i += 1
    if quoted:
        raise ValueError('Unterminated command quote')
    if started:
        result.append(''.join(token))
    return result


def expanded_command(raw, expanded):
    """Remove Ninja compdb's enclosing quotes around expanded response content."""
    matches = list(re.finditer(r'"@[^"\r\n]+"|@"[^"\r\n]+"|@[^\s"]+', raw))
    if len(matches) != 1:
        raise ValueError('Expected exactly one linker response file')
    match = matches[0]
    prefix, suffix = raw[:match.start()], raw[match.end():]
    if not expanded.startswith(prefix) or (suffix and not expanded.endswith(suffix)):
        raise ValueError('Expanded command does not match Ninja command')
    middle = expanded[len(prefix):len(expanded) - len(suffix) if suffix else None]
    if not (middle.startswith('"') and middle.endswith('"')):
        raise ValueError('Unexpected Ninja response expansion')
    return prefix + middle[1:-1] + suffix


def consumer_flags(flags):
    result, includes = [], []
    i = 0
    while i < len(flags):
        flag = flags[i]
        if flag in ('-Xclang', '-mllvm'):
            if i + 1 == len(flags):
                raise ValueError('Dangling compiler argument: ' + flag)
            # Chromium policy plugins, module cache and backend tuning are build-local.
            i += 2
            continue
        if flag.startswith('-I'):
            if flag == '-I':
                i += 1
                if i == len(flags):
                    raise ValueError('Missing include directory')
                includes.append(flags[i])
            else:
                includes.append(flag[2:])
        elif ('module' in flag or flag.startswith(('-fcrash-diagnostics-dir=',
                '-ffile-compilation-dir=', '-fdebug-compilation-dir='))):
            pass
        else:
            result.append(flag)
        i += 1
    return result, includes


def validate_configuration(args, linkage='static'):
    if linkage not in ('static', 'shared'):
        raise ValueError('Unsupported SDK linkage: ' + linkage)
    required = dict(target_cpu='x64', is_clang=True, use_lld=True,
                    use_custom_libcxx=True, is_component_build=linkage == 'shared', is_debug=False)
    for key, value in required.items():
        if args.get(key) != value:
            raise ValueError(f'Export requires {key} = {value!r}')
    supported = set(required) | {'clang_base_path', 'clang_use_chrome_plugins',
        'use_remoteexec', 'rust_sysroot_absolute', 'rust_bindgen_root',
        'rust_crubit_root', 'rustc_version'}
    if args.keys() - supported:
        raise ValueError('Unsupported SDK build arguments: ' + ', '.join(sorted(args.keys() - supported)))


def runtime_contract(flags, defines, linkage):
    """Require CRT and component ABI to agree with the selected SDK kind."""
    expected = '/MD' if linkage == 'shared' else '/MT'
    crt_flags = {flag.upper() for flag in flags if flag.upper() in ('/MT', '/MD', '/MTD', '/MDD')}
    component = any(value.split('=', 1)[0] == 'COMPONENT_BUILD' for value in defines)
    if crt_flags != {expected} or component != (linkage == 'shared'):
        raise ValueError('GN consumer CRT/component ABI does not match SDK linkage')
    return 'MultiThreadedDLL' if linkage == 'shared' else 'MultiThreaded'


def parse_args(text):
    """Accept explicit scalar arguments; refuse GN expressions/imports ambiguously parsed."""
    result = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = re.fullmatch(r'\s*(\w+)\s*=\s*(true|false|"[^"\r\n]*"|-?\d+)\s*', line)
        if not match or match[1] in result:
            raise ValueError('SDK export requires unambiguous scalar GN arguments')
        value = match[2]
        result[match[1]] = (value == 'true' if value in ('true', 'false') else
                              value[1:-1] if value.startswith('"') else int(value))
    return result


def link_contract(command, excluded, local_outputs=()):
    tokens = windows_split(command)
    positions = [i for i, arg in enumerate(tokens)
                 if arg.replace('\\', '/').rsplit('/', 1)[-1].lower() == 'lld-link.exe']
    if len(positions) != 1:
        raise ValueError('Expected selected lld-link command')
    inputs, system, options = [], [], []
    excluded = {p.replace('\\', '/') for p in excluded}
    local_outputs = {p.replace('\\', '/').lower() for p in local_outputs}
    for arg in tokens[positions[0] + 1:]:
        norm = arg.replace('\\', '/')
        lower = arg.lower()
        if norm in excluded:
            continue
        if arg.startswith('@'):
            raise ValueError('Unexpanded linker response file')
        if lower.startswith(('/out:', '/pdb:', '/pdbsourcepath:', '/pdbaltpath:',
                             '/natvis:', '/implib:', '/manifestfile:', '/libpath:', '-libpath:',
                             '/subsystem:')):
            continue
        if lower in ('/lldignoreenv', '/wx'):
            continue
        if lower.endswith(('.obj', '.o', '.lib', '.rlib')) and not arg.startswith(('/', '-')):
            if '/' not in norm and lower.endswith('.lib') and norm.lower() not in local_outputs:
                system.append(arg)
            else:
                inputs.append(norm)
        elif arg.startswith(('/', '-')):
            options.append(arg)
        else:
            raise ValueError('Unexpected linker input: ' + arg)
    return dict(inputs=inputs, system_libs=system, options=options,
                linker=tokens[positions[0]])
