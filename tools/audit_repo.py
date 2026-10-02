"""Read-only PitchComm repository audit.

Checks, in order:

  1. config symbols: every CONFIG_PITCHCOMM_* reference under firmware/ is
     defined by firmware/Kconfig or a firmware .conf file
  2. em-dash: no U+2014 in any text file tracked by git
  3. cmake sources: every firmware/src/*.c and *.cpp is listed in
     firmware/CMakeLists.txt
  4. catalog: firmware/include/pc/catalog.h and gui/catalog.json match
     generate_catalog.rendered()
  5. ncs version: firmware/ncs_version.txt is one line like v3.4.0
     (audit(check_version=False) drops only this rule; preflight --audio uses that)
  6. empty files: no zero-byte file under firmware source, roles, boards,
     tools/, or gui/

The audit never writes anything. It exits 0 when clean and 1 otherwise.
tools/preflight.py calls audit() and accepts --skip-audit to bypass it.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

from generate_catalog import ROOT, rendered

EM_DASH = '\u2014'
CONFIG_REF = re.compile(r'CONFIG_PITCHCOMM_[A-Z0-9_]+')
KCONFIG_CONFIG = re.compile(r'^\s*(?:menu)?config\s+(PITCHCOMM_[A-Z0-9_]+)\s*$')
CONF_DEFINE = re.compile(r'^\s*(?:#\s*)?CONFIG_(PITCHCOMM_[A-Z0-9_]+)(?:=|\s+is not set\b)')
NCS_VERSION = re.compile(r'^v[0-9]+\.[0-9]+\.[0-9]+$')
SKIP_DIRS = {'build', '__pycache__', '.git', '.pytest_cache'}
MAX_ERRORS_SHOWN = 5


def read_text(path):
    """Return UTF-8 text, or None for missing or binary files."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b'\x00' in data:
        return None
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return None


def iter_text_files(base, skip_dirs=SKIP_DIRS):
    """Yield (path, text) for readable text files under base."""
    if not base.is_dir():
        return
    for path in sorted(base.rglob('*')):
        if not path.is_file():
            continue
        if skip_dirs.intersection(path.relative_to(base).parts[:-1]):
            continue
        text = read_text(path)
        if text is not None:
            yield path, text


def check_config_symbols(root):
    """Every CONFIG_PITCHCOMM_* reference must be a known symbol."""
    defined = set()
    kconfig = read_text(root / 'firmware/Kconfig')
    if kconfig is not None:
        for line in kconfig.splitlines():
            match = KCONFIG_CONFIG.match(line)
            if match:
                defined.add('CONFIG_' + match.group(1))
    for path in sorted((root / 'firmware').rglob('*.conf')):
        if SKIP_DIRS.intersection(path.relative_to(root / 'firmware').parts[:-1]):
            continue
        text = read_text(path)
        if text is None:
            continue
        for line in text.splitlines():
            match = CONF_DEFINE.match(line)
            if match:
                defined.add('CONFIG_' + match.group(1))
    references = 0
    errors = []
    for path, text in iter_text_files(root / 'firmware'):
        relative = path.relative_to(root).as_posix()
        for match in CONFIG_REF.finditer(text):
            references += 1
            token = match.group(0)
            line = text.count('\n', 0, match.start()) + 1
            if text[match.end():match.end() + 1] == '*':
                if not any(symbol.startswith(token) for symbol in defined):
                    errors.append(f'{relative}:{line}: {token}* matches no defined symbol')
            elif token not in defined:
                errors.append(f'{relative}:{line}: {token} is not defined in firmware/Kconfig or a conf file')
    return {'name': 'CONFIG_PITCHCOMM_* references', 'ok': not errors,
            'detail': f'{len(defined)} symbols defined, {references} references scanned', 'errors': errors}


def walk_files(root):
    """Yield (relative posix path, path) for files under root, skipping SKIP_DIRS."""
    root = Path(root)
    if not root.is_dir():
        return
    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        if SKIP_DIRS.intersection(path.relative_to(root).parts[:-1]):
            continue
        yield path.relative_to(root).as_posix(), path


def tracked_files(root):
    """Return (candidates, source) for rules that prefer git-tracked files.

    Candidate paths are made relative to root, so pointing a rule at a
    subdirectory of a repository does not silently scan nothing. Falls back to
    a filesystem walk when git is unavailable, when root is not inside a
    repository, or when git lists no file under root while files exist there.
    """
    root = Path(root).resolve()
    try:
        top = subprocess.run(['git', '-C', str(root), 'rev-parse', '--show-toplevel'],
                             capture_output=True, encoding='utf-8', errors='replace',
                             check=True).stdout.strip()
        listing = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'],
                                 capture_output=True, encoding='utf-8', errors='replace',
                                 check=True).stdout
        top_path = Path(top)
        candidates = []
        for name in listing.split('\0'):
            if not name:
                continue
            path = top_path / name
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                continue  # tracked in the repository but outside this root
            if path.is_file():
                candidates.append((relative, path))
        if candidates:
            return candidates, 'git'
    except (OSError, subprocess.CalledProcessError):
        pass
    return list(walk_files(root)), 'filesystem walk'


def check_em_dash(root):
    """No U+2014 in tracked text files; walk the tree when git cannot help."""
    root = Path(root).resolve()
    candidates, source = tracked_files(root)
    errors = []
    scanned = 0
    for name, path in candidates:
        text = read_text(path)
        if text is None:
            continue
        scanned += 1
        for number, line in enumerate(text.splitlines(), 1):
            if EM_DASH in line:
                errors.append(f'{name}:{number}: contains U+2014 em-dash')
    if scanned == 0:
        present = list(walk_files(root))
        if present:
            errors.append(f'{len(present)} file(s) exist but none could be scanned as text; '
                          'the em-dash rule inspected nothing')
    detail = f'{scanned} files scanned'
    if source == 'filesystem walk':
        detail += ' (filesystem walk)'
    return {'name': 'U+2014 em-dash in tracked text files', 'ok': not errors,
            'detail': detail, 'errors': errors}


def strip_cmake_comments(text):
    """Cut each line at its first '#'.

    Simple by design: a '#' inside a quoted argument also truncates that line.
    CMake source lists do not normally quote '#'.
    """
    return '\n'.join(line.split('#', 1)[0] for line in text.splitlines())


def check_cmake_sources(root):
    """Every firmware/src/*.c and *.cpp must be listed in CMakeLists.txt."""
    source_dir = root / 'firmware/src'
    names = sorted(path.name for path in source_dir.glob('*.c'))
    names += sorted(path.name for path in source_dir.glob('*.cpp'))
    cmake = read_text(root / 'firmware/CMakeLists.txt')
    errors = []
    if cmake is None:
        errors.append('firmware/CMakeLists.txt is missing or unreadable')
    else:
        cmake = strip_cmake_comments(cmake)
        for name in names:
            if not re.search(r'(?<![A-Za-z0-9_.])' + re.escape(name) + r'(?![A-Za-z0-9_.])', cmake):
                errors.append(f'firmware/src/{name} is not listed in firmware/CMakeLists.txt')
    return {'name': 'firmware/src sources in firmware/CMakeLists.txt', 'ok': not errors,
            'detail': f'{len(names)} source files checked', 'errors': errors}


def check_catalog(root):
    """Both generated catalog files must match rendered()."""
    try:
        version, files = rendered(root)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {'name': 'generated catalog files', 'ok': False, 'detail': 'cannot render the catalog',
                'errors': [f'catalog render failed: {error}']}
    errors = []
    for name, expected in files.items():
        actual = read_text(root / name)
        if actual is None:
            errors.append(f'{name} is missing or not UTF-8 text; run python tools/generate_catalog.py')
        elif actual.replace('\r\n', '\n') != expected:
            errors.append(f'{name} does not match rendered(); run python tools/generate_catalog.py')
    return {'name': 'generated catalog files', 'ok': not errors,
            'detail': f'{len(files)} files, dictionary {version:08x}', 'errors': errors}


def check_ncs_version(root):
    """firmware/ncs_version.txt must be exactly one vX.Y.Z line."""
    path = root / 'firmware/ncs_version.txt'
    errors = []
    detail = 'missing'
    try:
        raw = path.read_text(encoding='ascii')
    except FileNotFoundError:
        errors.append('firmware/ncs_version.txt is missing; restore the pinned NCS version (for example v3.4.0)')
    except (UnicodeDecodeError, OSError) as error:
        errors.append(f'firmware/ncs_version.txt is not readable as ASCII: {error}')
    else:
        text = raw.strip()
        lines = [line for line in raw.splitlines() if line.strip()]
        if len(lines) != 1 or not NCS_VERSION.fullmatch(text):
            errors.append(f'firmware/ncs_version.txt must be one line like v3.4.0 (found {text!r})')
        else:
            detail = text
    return {'name': 'firmware/ncs_version.txt', 'ok': not errors, 'detail': detail, 'errors': errors}


def check_empty_files(root):
    """No zero-byte files in firmware source, tools or gui."""
    bases = [root / 'firmware/src', root / 'firmware/include', root / 'firmware/tests',
             root / 'firmware/roles', root / 'firmware/boards',
             root / 'tools', root / 'gui']
    errors = []
    scanned = 0
    for base in bases:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob('*')):
            if not path.is_file():
                continue
            if SKIP_DIRS.intersection(path.relative_to(base).parts[:-1]):
                continue
            if path.suffix == '.pyc':
                continue
            scanned += 1
            try:
                size = path.stat().st_size
            except OSError as error:
                errors.append(f'{path.relative_to(root).as_posix()}: cannot stat: {error}')
                continue
            if size == 0:
                errors.append(f'{path.relative_to(root).as_posix()}: zero bytes')
    return {'name': 'empty source/tool/gui files', 'ok': not errors,
            'detail': f'{scanned} files checked', 'errors': errors}


def audit(root=ROOT, check_version=True):
    """Run the checks and return a report dictionary (never writes).

    check_version=False drops only the firmware/ncs_version.txt rule, which
    lets audio-only preflight skip the toolchain pin without weakening the
    catalog drift, config symbol, CMake, em-dash or empty-file checks.
    """
    root = Path(root)
    checks = [check_config_symbols(root), check_em_dash(root), check_cmake_sources(root),
              check_catalog(root)]
    if check_version:
        checks.append(check_ncs_version(root))
    checks.append(check_empty_files(root))
    errors = []
    for check in checks:
        errors.extend(f'{check["name"]}: {message}' for message in check['errors'])
    report = {'ok': not errors, 'root': str(root), 'checks': checks, 'errors': errors}
    report['summary'] = format_summary(report)
    return report


def format_summary(report):
    """One compact PASS/FAIL block for printing."""
    lines = []
    for check in report['checks']:
        status = 'PASS' if check['ok'] else 'FAIL'
        lines.append(f'[{status}] {check["name"]}: {check["detail"]}')
        for message in check['errors'][:MAX_ERRORS_SHOWN]:
            lines.append(f'       {message}')
        if len(check['errors']) > MAX_ERRORS_SHOWN:
            lines.append(f'       ... and {len(check["errors"]) - MAX_ERRORS_SHOWN} more')
    failed = sum(1 for check in report['checks'] if not check['ok'])
    lines.append(f'audit_repo: {"PASS" if report["ok"] else "FAIL"} '
                 f'({len(report["checks"]) - failed} of {len(report["checks"])} checks passed, '
                 f'{len(report["errors"])} error(s))')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT,
                        help='repository root (default: the repo containing tools/)')
    args = parser.parse_args()
    report = audit(args.root)
    print(report['summary'])
    sys.exit(0 if report['ok'] else 1)


if __name__ == '__main__':
    main()
