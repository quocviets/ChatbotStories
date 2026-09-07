import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = Path(__file__).with_name("ruff-baseline.json")


def build_state(
    diagnostics: list[dict[str, object]], root: Path, targets: list[str]
) -> dict[str, object]:
    files = []
    for target in targets:
        path = root / target
        candidates = [path] if path.is_file() else path.rglob("*.py")
        files.extend(
            candidate.resolve().relative_to(root).as_posix()
            for candidate in candidates
            if candidate.suffix == ".py"
        )

    counts = Counter(
        f"{Path(str(item['filename'])).resolve().relative_to(root).as_posix()}:{item['code']}"
        for item in diagnostics
    )
    return {"files": sorted(files), "diagnostics": dict(sorted(counts.items()))}


def find_increases(current: dict[str, int], baseline: dict[str, int]) -> dict[str, int]:
    # Known limitation: count baselines ignore same-rule replacement within one file;
    # use a diff-aware gate if this becomes a real escape hatch.
    return {
        key: count - baseline.get(key, 0)
        for key, count in current.items()
        if count > baseline.get(key, 0)
    }


def main() -> int:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    targets = baseline["targets"]
    lint = subprocess.run(
        [sys.executable, "-m", "ruff", "check", *targets, "--output-format", "json", "--no-cache"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if lint.returncode not in {0, 1}:
        sys.stderr.write(lint.stderr)
        return lint.returncode

    current = build_state(json.loads(lint.stdout), ROOT, targets)
    increases = find_increases(current["diagnostics"], baseline["diagnostics"])
    formatted = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", *targets, "--no-cache"],
        cwd=ROOT,
        check=False,
    )
    format_exit = formatted.returncode

    if increases:
        for key, count in increases.items():
            print(f"new Ruff diagnostic: {key} (+{count})")

    if increases or format_exit:
        return 1

    print(f"Ruff baseline gate passed ({sum(current['diagnostics'].values())} legacy diagnostics).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
