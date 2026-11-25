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


class CommitStatusTests(unittest.TestCase):
    def test_empty_statuses_is_waiting(self) -> None:
        state = module.parse_commit_status_payload(
            {"state": "pending", "statuses": []},
            repo="o/r",
            sha="1234567890abcdef1234567890abcdef12345678",
        )
        self.assertFalse(state.started)
        self.assertFalse(state.completed)
        self.assertEqual(state.overall_state, "waiting")

    def test_pending_and_success_commit_status(self) -> None:
        pending = module.parse_commit_status_payload(
            {
                "state": "pending",
                "statuses": [
                    {
                        "context": "gitea-ci / build",
                        "state": "pending",
                        "description": "Running on Gitea",
                        "target_url": "https://example.invalid/runs/10",
                    }
                ],
            },
            repo="o/r",
            sha="abcdef1234567890",
        )
        self.assertTrue(pending.started)
        self.assertFalse(pending.completed)
        self.assertEqual(pending.overall_state, "pending")
        self.assertIn("gitea-ci / build=pending (Running on Gitea)", pending.snapshot)

        done = module.parse_commit_status_payload(
            {
                "state": "success",
                "statuses": [
                    {
                        "context": "gitea-ci / build",
                        "state": "success",
                        "description": "Passed",
                        "target_url": "https://example.invalid/runs/10",
                    },
                    {
                        "context": "other / lint",
                        "state": "failure",
                        "description": "Ignored by prefix",
                    },
                ],
            },
            repo="o/r",
            sha="abcdef1234567890",
            context_prefix="gitea-ci",
        )
        self.assertTrue(done.completed)
        self.assertEqual(done.overall_state, "success")
        self.assertEqual(len(done.items), 1)

    def test_failure_status_and_comment_extraction(self) -> None:
        failed = module.parse_commit_status_payload(
            {
                "state": "failure",
                "statuses": [
                    {
                        "context": "gitea-ci / build",
                        "state": "failure",
                        "description": 'Failed at "Vet & test"',
                    }
                ],
            },
            repo="o/r",
            sha="abcdef1234567890",
        )
        self.assertTrue(failed.completed)
        self.assertEqual(failed.overall_state, "failure")

        comments = [
            {"body": "ordinary human comment"},
            {
                "body": '<!-- gitea-ci-failure context="gitea-ci / build" step="Vet & test" -->\n### Gitea CI Failed\n```text\nFAIL TestFoo\n```'
            },
        ]
        extracted = module.extract_failure_comment(comments, context_prefix="gitea-ci")
        self.assertIsNotNone(extracted)
        assert extracted is not None
        self.assertNotIn("<!-- gitea-ci-failure", extracted)
        self.assertIn("FAIL TestFoo", extracted)

        self.assertIsNone(module.extract_failure_comment(comments, context_prefix="unrelated"))

        generic_comments = [
            {
                "body": '<!-- ci-failure context="jenkins / build" -->\nBuild broke at lint'
            }
        ]
        generic = module.extract_failure_comment(generic_comments, context_prefix="jenkins")
        self.assertEqual(generic, "Build broke at lint")

        custom = module.extract_failure_comment(
            [{"body": "[CUSTOM-FAIL]\nunit test error"}],
            failure_marker="[CUSTOM-FAIL]",
        )
        self.assertEqual(custom, "unit test error")


class ArgParsingTests(unittest.TestCase):
    def test_legacy_run_id_mode(self) -> None:
        args = module.parse_args(["12345", "--repo", "o/r"])
        self.assertEqual(args.run_id, "12345")
        self.assertEqual(args.repo, "o/r")

    def test_ref_mode_defaults(self) -> None:
        args = module.parse_args(["--ref", "HEAD"])
        self.assertIsNone(args.run_id)
        self.assertEqual(args.ref, "HEAD")
        self.assertEqual(args.mode, "auto")
        self.assertEqual(args.wait_start, 45.0)

    def test_reject_conflicting_or_missing_targets(self) -> None:
        with self.assertRaises(SystemExit):
            module.parse_args([])
        with self.assertRaises(SystemExit):
            module.parse_args(["12345", "--ref", "HEAD"])
        with self.assertRaises(SystemExit):
            module.parse_args(["--ref", "HEAD", "--commit", "abc"])


class SleepTests(unittest.TestCase):
    def test_version_constant_matches_repository_version(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(module.VERSION, version)


if __name__ == "__main__":
    unittest.main()
