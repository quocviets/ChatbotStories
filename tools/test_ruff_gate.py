import unittest
from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools import ruff_gate
from tools.ruff_gate import build_state, find_increases


class RuffGateTests(unittest.TestCase):
    def test_main_fails_when_existing_target_needs_formatting(self):
        lint_result = CompletedProcess([], 0, stdout="[]", stderr="")
        format_result = CompletedProcess([], 1, stdout="", stderr="")

        with patch(
            "tools.ruff_gate.subprocess.run",
            side_effect=[lint_result, format_result],
        ):
            result = ruff_gate.main()

        self.assertEqual(result, 1)

    def test_find_increases_only_returns_diagnostics_above_baseline(self):
        baseline = {"legacy.py:F401": 1, "unchanged.py:I001": 1}
        current = {"legacy.py:F401": 2, "unchanged.py:I001": 1, "new.py:B023": 1}

        self.assertEqual(
            find_increases(current, baseline),
            {"legacy.py:F401": 1, "new.py:B023": 1},
        )

    def test_build_state_counts_rules_and_lists_python_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app" / "sample.py"
            source.parent.mkdir()
            source.write_text("import os\n", encoding="utf-8")

            state = build_state(
                [{"filename": str(source), "code": "F401"}],
                root,
                ["app"],
            )

        self.assertEqual(
            state,
            {"files": ["app/sample.py"], "diagnostics": {"app/sample.py:F401": 1}},
        )


if __name__ == "__main__":
    unittest.main()
