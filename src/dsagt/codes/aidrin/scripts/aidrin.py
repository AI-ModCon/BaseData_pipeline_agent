"""Run AIDRIN for a DSAGT project: a per-stage readiness gate, or any aidrin command.

Two forms, both wrapped by ``dsagt-run`` so each call is one execution record:

    gate <file> [--profile P] [--target COL] [--categorical "a,b"]
                [--numerical "c,d"] [--report PATH]
        Runs every metric in the profile as its own ``aidrin run`` and writes
        one JSON object ``{metric: result}`` to stdout and to ``--report``.

    [--report PATH] <aidrin args...>
        Passes the arguments to ``aidrin`` unchanged (``run k-anonymity
        data.csv "age,sex"``, ``list``, ``summarize ...``); stdout is echoed
        and, with ``--report``, also written to that file.

The ``aidrin`` executable is ``$DSAGT_AIDRIN_BIN`` when set, else the
``readiness.executable`` line of ``.dsagt/config.yaml`` in the working
directory (``dsagt-run`` already requires the cwd to be the project dir).
stdlib only: this runs under whatever ``python`` the agent's shell has.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROFILES = {
    "quality": ("completeness", "duplicity", "outliers"),
    "supervised": (
        "completeness",
        "duplicity",
        "outliers",
        "class-imbalance",
        "feature-relevance",
    ),
}

_EXECUTABLE_RE = re.compile(r"^\s+executable:\s*(.+?)\s*$", re.MULTILINE)


def resolve_executable() -> str:
    env = os.environ.get("DSAGT_AIDRIN_BIN")
    if env:
        return env
    config = Path.cwd() / ".dsagt" / "config.yaml"
    if not config.exists():
        sys.exit(
            f"aidrin: no .dsagt/config.yaml in {Path.cwd()}; run from the "
            "project directory or set DSAGT_AIDRIN_BIN."
        )
    text = config.read_text()
    block = text.split("readiness:", 1)
    match = _EXECUTABLE_RE.search(block[1]) if len(block) == 2 else None
    if not match:
        sys.exit(
            "aidrin: readiness.executable is not set in .dsagt/config.yaml; "
            "re-run `dsagt init --readiness aidrin` or set DSAGT_AIDRIN_BIN."
        )
    return os.path.expanduser(match.group(1).strip("'\""))


def metric_argv(metric: str, args: argparse.Namespace) -> list[str]:
    """Positional arguments for *metric* from the gate options."""
    if metric == "class-imbalance":
        if not args.target:
            sys.exit(f"aidrin gate: {metric} requires --target")
        return [args.target]
    if metric == "feature-relevance":
        if not args.target or not (args.categorical or args.numerical):
            sys.exit(
                f"aidrin gate: {metric} requires --target and at least one of "
                "--categorical / --numerical"
            )
        return [args.categorical or "", args.numerical or "", args.target]
    return []


def run_aidrin(executable: str, argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([executable, *argv], capture_output=True, text=True)


def gate(executable: str, args: argparse.Namespace) -> int:
    report: dict = {"file": args.file, "profile": args.profile, "metrics": {}}
    failed = False
    for metric in PROFILES[args.profile]:
        proc = run_aidrin(
            executable, ["run", metric, args.file, *metric_argv(metric, args)]
        )
        if proc.returncode != 0:
            failed = True
            report["metrics"][metric] = {"error": proc.stderr.strip()}
            continue
        try:
            report["metrics"][metric] = json.loads(proc.stdout)
        except json.JSONDecodeError:
            report["metrics"][metric] = {"raw": proc.stdout}
    text = json.dumps(report, indent=2)
    print(text)
    if args.report:
        write_report(args.report, text)
    return 1 if failed else 0


def passthrough(executable: str, report_path: str | None, argv: list[str]) -> int:
    proc = run_aidrin(executable, argv)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if report_path and proc.returncode == 0:
        write_report(report_path, proc.stdout)
    return proc.returncode


def write_report(path: str, text: str) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)


def parse_gate(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="aidrin gate")
    p.add_argument("file")
    p.add_argument("--profile", choices=sorted(PROFILES), default="quality")
    p.add_argument("--target", default=None)
    p.add_argument("--categorical", default=None)
    p.add_argument("--numerical", default=None)
    p.add_argument("--report", default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        sys.exit(__doc__)
    executable = resolve_executable()
    if argv[0] == "gate":
        return gate(executable, parse_gate(argv[1:]))
    report_path = None
    if argv[0] == "--report":
        if len(argv) < 3:
            sys.exit("aidrin: --report needs a path followed by aidrin arguments")
        report_path, argv = argv[1], argv[2:]
    return passthrough(executable, report_path, argv)


if __name__ == "__main__":
    sys.exit(main())
