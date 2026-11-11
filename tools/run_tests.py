"""Explicit repository regression runner (stdlib only; never called by generation).

Examples (also suitable as explicit CI steps)::

    python tools/run_tests.py --list
    python tools/run_tests.py --skill service-workspace --jobs 2 --timeout 300
    python tools/run_tests.py --module .opencode/skills/materialize-full-service/tests/test_batch_shell.py --class BatchShellDecryptTests
    python tools/run_tests.py --all --jobs 2 --timeout 600

Segments are skills/modules/classes, NOT verified fast/integration/Java categories.
--list enumerates source paths without importing or executing tests. Each selected
module runs in its own interpreter; --jobs only overlaps these isolated processes.
Timeouts apply per module. Tests retain their own prerequisites/skips and may run
local Java tools; this runner does not grant Maven, database, network or deployment
authorization, and never changes authorization environment variables. Use bounded
module selection when those prerequisites are not authorized. No shell commands
or arbitrary paths can be supplied. Cancellation attempts to stop ordinary child
process trees (POSIX process group; Windows taskkill /T /F), not hostile detached
processes; the parent is still terminated if the tree command is unavailable.
"""

import argparse
import ast
from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / '.opencode' / 'skills'


def inventory():
    """Only conventional test modules inside repository skill test directories."""
    return {
        path.relative_to(ROOT).as_posix(): path
        for path in sorted(SKILLS.glob('*/tests/test_*.py'))
        if path.resolve().is_relative_to(SKILLS.resolve())
    }


def select(known, skills=(), modules=(), all_modules=False):
    available = {Path(name).parts[2] for name in known}
    unknown = set(skills) - available
    if unknown:
        raise ValueError('Unknown skills: ' + ', '.join(sorted(unknown)))
    normalized = [name.replace('\\', '/') for name in modules]
    unknown = set(normalized) - known.keys()
    if unknown:
        raise ValueError('Unknown test modules: ' + ', '.join(sorted(unknown)))
    return [path for name, path in known.items()
            if all_modules or name in normalized or Path(name).parts[2] in skills]


def classes_in(path):
    """Source-declared test classes only; no imports or test execution."""
    tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)
            and any(isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name.startswith('test_') for child in node.body)}


def command(path, classes=()):
    if classes:
        return [sys.executable, '-m', 'unittest', '-v',
                *[path.stem + '.' + name for name in classes]]
    return [sys.executable, '-m', 'unittest', 'discover', '-v',
            '-s', str(path.parent), '-p', path.name]


def stop_tree(process):
    if os.name == 'nt':
        # Kill the tree before reaping its parent so taskkill can locate children.
        try:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=False, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            pass  # Still terminate/reap the parent if tree cancellation is unavailable.
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=15)


@dataclass
class Result:
    module: str
    seconds: float
    returncode: int
    timed_out: bool
    skips: int
    output: str


def run_modules(paths, jobs, timeout, classes=()):
    pending = iter(paths)
    active = []
    results = []
    try:
        exhausted = False
        while active or not exhausted:
            while len(active) < jobs and not exhausted:
                path = next(pending, None)
                if path is None:
                    exhausted = True
                    break
                # Files avoid pipe-buffer deadlocks without reader threads.
                preferred = Path.home() / 'AppData/Local/Temp/opencode'
                output = tempfile.TemporaryFile(dir=preferred if preferred.is_dir() else None)
                options = ({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
                           if os.name == 'nt' else {'start_new_session': True})
                try:
                    process = subprocess.Popen(command(path, classes), cwd=path.parent,
                                               stdout=output, stderr=subprocess.STDOUT,
                                               **options)
                except BaseException:
                    output.close()
                    raise
                active.append((path, process, output, time.monotonic()))
            for entry in active[:]:
                path, process, output, started = entry
                elapsed = time.monotonic() - started
                expired = elapsed >= timeout
                code = process.poll()
                if code is None and not expired:
                    continue
                timed_out = code is None and expired
                if timed_out:
                    stop_tree(process)
                output.seek(0)
                text = output.read().decode('utf-8', errors='replace')
                output.close()
                result = Result(path.relative_to(ROOT).as_posix(), elapsed,
                                process.returncode, timed_out,
                                sum(int(n) for n in re.findall(r'\bskipped=(\d+)', text)), text)
                results.append(result)
                active.remove(entry)
                print(text, end='' if text.endswith('\n') else '\n', flush=True)
                print(f'{result.module}: {elapsed:.2f}s returncode={result.returncode} '
                      f'skips={result.skips} timeout={timed_out}', flush=True)
            if active:
                time.sleep(0.05)
    finally:
        for _, process, output, _ in active:
            try:
                stop_tree(process)
            finally:
                output.close()
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--skill', action='append', default=[], help='Select a known skill (repeatable)')
    parser.add_argument('--module', action='append', default=[], help='Exact repo-relative module path (repeatable)')
    parser.add_argument('--class', dest='classes', action='append', default=[], help='Source-declared class; requires one selected module')
    parser.add_argument('--all', action='store_true', help='Explicit complete regression selection')
    parser.add_argument('--list', action='store_true', help='Dry enumeration only; defaults to all modules')
    parser.add_argument('--jobs', type=int, default=1, help='Concurrent isolated module processes (default: 1)')
    parser.add_argument('--timeout', type=float, default=300, help='Positive seconds per module (default: 300)')
    args = parser.parse_args(argv)
    if args.jobs < 1 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--jobs and --timeout must be positive finite values')
    if not (args.skill or args.module or args.all or args.list):
        parser.error('Choose --skill, --module, --all or --list; no implicit regression run')
    try:
        paths = select(inventory(), args.skill, args.module,
                       args.all or (args.list and not (args.skill or args.module)))
        if not paths:
            raise ValueError('No test modules selected')
        if args.classes:
            if len(paths) != 1 or set(args.classes) - classes_in(paths[0]):
                raise ValueError('--class requires one module and known source-declared test classes')
            args.classes = list(dict.fromkeys(args.classes))
    except (ValueError, SyntaxError) as error:
        parser.error(str(error))
    if args.list:
        for path in paths:
            print(path.relative_to(ROOT).as_posix() +
                  (': ' + ', '.join(args.classes) if args.classes else ''))
        print(f'{len(paths)} module(s); dry enumeration, no tests imported or executed')
        return 0
    started = time.monotonic()
    try:
        results = run_modules(paths, args.jobs, args.timeout, args.classes)
    except KeyboardInterrupt:
        print('Interrupted; active process trees stopped.', file=sys.stderr)
        return 130
    failed = sum(result.returncode != 0 or result.timed_out for result in results)
    print(f'Summary: modules={len(results)} failed={failed} '
          f'skips={sum(result.skips for result in results)} '
          f'wall={time.monotonic() - started:.2f}s '
          f'module-seconds={sum(result.seconds for result in results):.2f}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
