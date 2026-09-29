from __future__ import annotations

import importlib.machinery
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "gh-ci-monitor"

loader = importlib.machinery.SourceFileLoader("gh_ci_monitor", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
module = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = module
loader.exec_module(module)


class ParsePayloadTests(unittest.TestCase):
    def test_completed_success_snapshot(self) -> None:
        state = module.parse_payload(
            {
                "status": "completed",
                "conclusion": "success",
                "url": "https://github.com/o/r/actions/runs/1",
                "jobs": [
                    {"name": "test", "status": "completed", "conclusion": "success"},
                    {"name": "build", "status": "completed", "conclusion": "success"},
                ],
            }
        )
        self.assertEqual(state.status, "completed")
        self.assertEqual(state.conclusion, "success")
        self.assertEqual(
            state.snapshot,
            "run=completed/success | test=completed/success | build=completed/success",
        )

    def test_running_run_uses_dash_for_missing_conclusion(self) -> None:
        state = module.parse_payload(
            {
                "status": "in_progress",
                "conclusion": "",
                "url": "https://github.com/o/r/actions/runs/2",
                "jobs": [
                    {"name": "test", "status": "in_progress", "conclusion": ""},
                ],
            }
        )
        self.assertEqual(state.snapshot, "run=in_progress/- | test=in_progress/-")

    def test_missing_status_is_rejected(self) -> None:
        with self.assertRaises(module.QueryError):
            module.parse_payload(
                {
                    "conclusion": "success",
                    "url": "https://github.com/o/r/actions/runs/3",
                    "jobs": [],
                }
            )

    def test_invalid_jobs_shape_is_rejected(self) -> None:
        with self.assertRaises(module.QueryError):
            module.parse_payload(
                {
                    "status": "completed",
                    "conclusion": "success",
                    "url": "https://github.com/o/r/actions/runs/4",
                    "jobs": {"not": "a list"},
                }
            )


class SleepTests(unittest.TestCase):
    def test_version_constant_matches_repository_version(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(module.VERSION, version)


if __name__ == "__main__":
    unittest.main()
