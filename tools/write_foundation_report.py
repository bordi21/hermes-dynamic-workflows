from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def count_tests(path: Path) -> str:
    if not path.exists():
        return "unknown"
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"Ran (\d+) tests?", text)
    return match.group(1) if match else "unknown"


def status_label(value: int) -> str:
    return "PASS" if value == 0 else "FAIL"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--initial-log", required=True)
    parser.add_argument("--initial-status", type=int, required=True)
    parser.add_argument("--stabilized-log", required=True)
    parser.add_argument("--stabilized-status", type=int, required=True)
    parser.add_argument("--final-log", required=True)
    parser.add_argument("--final-status", type=int, required=True)
    args = parser.parse_args()

    tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    package_files = [path for path in tracked if path.startswith("hermes_dynamic_workflows/")]
    test_files = [path for path in tracked if path.startswith("tests/") and path.endswith(".py")]

    report = f'''# Foundation Baseline — T00 to T02

- Base commit: `{args.base_commit}`
- Branch: `refactor/t00-t02-foundation`
- Python: `3.11`
- Test command: `python -m unittest discover -s tests -v`
- Initial baseline: `{status_label(args.initial_status)}` — `{count_tests(Path(args.initial_log))}` tests
- Stabilized baseline: `{status_label(args.stabilized_status)}` — `{count_tests(Path(args.stabilized_log))}` tests
- Post-change suite: `{status_label(args.final_status)}` — `{count_tests(Path(args.final_log))}` tests
- Tracked package files at verification: `{len(package_files)}`
- Tracked test modules at verification: `{len(test_files)}`

## T00 — Executable baseline

The original suite ran before T01/T02 changes. It exposed one pre-existing Linux-only defect: bundled agent-type files are lowercase, while resolution and the existing test also use names such as `Plan` and `Explore`. The fallback name comparison was case-sensitive, so `resolve_agent_type("Plan")` returned `None`.

T00 repaired only that baseline defect by making the resolved frontmatter name comparison case-insensitive. The complete suite was then rerun and had to pass before T01/T02 were allowed to execute.

## T01 — Hermes profile inheritance

Workflow children now instantiate fresh `AIAgent` sessions with profile context files and memory enabled. The role-specific ephemeral prompt remains additive, while task-specific context stays isolated in the child's scoped first user message. The default blocked-toolset list no longer blocks `memory`.

Repository tests inspect the actual `AIAgent` constructor arguments. This is code-level evidence, not a live installed-Hermes canary.

## T02 — Structured package schemas

Nine canonical Draft 2020-12 handoff schemas define planner, task, worker result, review request, review verdict, repair, integration result, final validation, and final report packages. They use the plugin's existing schema-validation path rather than a second parser.

Tests require planner-authored reviewer guidelines, strict `PASS`/`FAIL`/`BLOCKED` verdicts, and repair lineage containing the original task, previous result, and review feedback.

## Verification boundary

This report proves repository behavior under GitHub Actions. It does not claim the branch has been installed on the VPS or that a live profile has passed SOUL/memory canary verification.
'''

    path = ROOT / "docs" / "FOUNDATION_BASELINE.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
