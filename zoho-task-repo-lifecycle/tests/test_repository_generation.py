import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "repo_lifecycle_dry_run.py"
SPEC = importlib.util.spec_from_file_location("repo_lifecycle", MODULE_PATH)
assert SPEC and SPEC.loader
lifecycle = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = lifecycle
SPEC.loader.exec_module(lifecycle)


def sample_task() -> dict:
    return {
        "id": "110",
        "key": "BI1-T110",
        "name": "Lifecycle regression",
        "description": "Generate a complete repository.",
        "status": {"name": "In Progress"},
        "tags": [{"name": "repo-needed"}],
        "link": {
            "self": {
                "url": "https://projectsapi.zoho.com/restapi/portal/898600220/projects/2543412000001324010/tasks/110/"
            }
        },
    }


def sample_decision() -> object:
    return lifecycle.Decision(
        task_id="110",
        task_key="BI1-T110",
        title="Lifecycle regression",
        repo_name="bi1-t110-lifecycle-regression",
        action="would-create",
        reason="eligible",
    )


class RepositoryGenerationTests(unittest.TestCase):
    def test_generated_git_paths_exclude_unrelated_directory_contents(self) -> None:
        self.assertNotIn("docs", lifecycle.GENERATED_GIT_PATHS)
        self.assertNotIn("scripts", lifecycle.GENERATED_GIT_PATHS)
        self.assertNotIn("artifacts", lifecycle.GENERATED_GIT_PATHS)
        self.assertIn("docs/CURRENT_HANDOFF.md", lifecycle.GENERATED_GIT_PATHS)
        self.assertIn("scripts/.gitkeep", lifecycle.GENERATED_GIT_PATHS)
        self.assertIn("scripts/sync_commits_to_zoho.py", lifecycle.GENERATED_GIT_PATHS)
        self.assertIn(".zoho-project-task.json", lifecycle.GENERATED_GIT_PATHS)
        self.assertIn("artifacts/.gitkeep", lifecycle.GENERATED_GIT_PATHS)
        for workflow in (
            "agent-readiness.yml",
            "python-quality.yml",
            "repository-validation.yml",
            "claude-context-check.yml",
            "issue-development.yml",
            "pr-validation.yml",
            "security.yml",
            "sync-commits-to-zoho.yml",
        ):
            self.assertIn(f".github/workflows/{workflow}", lifecycle.GENERATED_GIT_PATHS)

    def test_staging_leaves_unrelated_dirty_work_unstaged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            with patch.object(lifecycle, "LOCAL_REPO_ROOT", Path(directory)):
                lifecycle.ensure_local_files(
                    root, sample_task(), sample_decision(), "https://example.test/repo"
                )
            commands = (
                ["git", "init", "-b", "main"],
                ["git", "config", "user.name", "Lifecycle Test"],
                ["git", "config", "user.email", "lifecycle-test@example.invalid"],
                ["git", "add", "."],
                ["git", "commit", "-m", "Initial fixture"],
            )
            for command in commands:
                result = lifecycle.run_process(command, root)
                self.assertEqual(result.returncode, 0, result.stderr)
            (root / "STATUS.md").write_text((root / "STATUS.md").read_text() + "\nGenerated update.\n")
            unrelated = root / "docs/USER_WORK.md"
            unrelated.write_text("Do not stage this work.\n")
            lifecycle.stage_generated_files(root)
            staged = lifecycle.run_process(
                ["git", "diff", "--cached", "--name-only"], root
            ).stdout.splitlines()
            self.assertIn("STATUS.md", staged)
            self.assertNotIn("docs/USER_WORK.md", staged)
            self.assertTrue(unrelated.is_file())

    def test_staging_skips_ignored_untracked_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(lifecycle.run_process(["git", "init", "-b", "main"], root).returncode, 0)
            (root / ".gitignore").write_text("docs/CURRENT_HANDOFF.md\n")
            handoff = root / "docs/CURRENT_HANDOFF.md"
            handoff.parent.mkdir()
            handoff.write_text("Private local handoff.\n")
            paths = lifecycle.stageable_generated_paths(root)
            self.assertNotIn("docs/CURRENT_HANDOFF.md", paths)
            self.assertIn(".gitignore", paths)

    def test_extended_legacy_gitignore_is_owned_without_rule_loss(self) -> None:
        base = lifecycle.load_template(".gitignore.tmpl")
        existing = base + "\n# User rules\nprivate/\n"
        migrated = lifecycle.safe_legacy_migration_content(
            ".gitignore",
            existing,
            base,
            lifecycle.add_ownership_header(".gitignore", base, "BI1-T110"),
            sample_decision(),
        )
        self.assertIsNotNone(migrated)
        assert migrated is not None
        self.assertTrue(migrated.endswith(existing))
        self.assertIn("private/", migrated)

    def test_temporary_lifecycle_repo_commits_and_pushes_all_workflows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            root = temporary / "repo"
            remote = temporary / "remote.git"
            with patch.object(lifecycle, "LOCAL_REPO_ROOT", temporary):
                lifecycle.ensure_local_files(
                    root, sample_task(), sample_decision(), "https://example.test/repo"
                )
            commands = (
                (["git", "init", "--bare", str(remote)], temporary),
                (["git", "init", "-b", "main"], root),
                (["git", "config", "user.name", "Lifecycle Test"], root),
                (["git", "config", "user.email", "lifecycle-test@example.invalid"], root),
                (["git", "add", "."], root),
                (["git", "commit", "-m", "Test generated lifecycle repository"], root),
                (["git", "remote", "add", "origin", str(remote)], root),
                (["git", "push", "-u", "origin", "main"], root),
            )
            for command, cwd in commands:
                result = lifecycle.run_process(command, cwd)
                self.assertEqual(result.returncode, 0, result.stderr)
            remote_head = lifecycle.run_process(
                ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/main"], temporary
            )
            self.assertEqual(remote_head.returncode, 0, remote_head.stderr)
            workflows = {path.name for path in (root / ".github/workflows").glob("*.yml")}
            self.assertEqual(
                workflows,
                {
                    "agent-readiness.yml",
                    "python-quality.yml",
                    "repository-validation.yml",
                    "claude-context-check.yml",
                    "issue-development.yml",
                    "pr-validation.yml",
                    "security.yml",
                    "sync-commits-to-zoho.yml",
                },
            )

    def test_every_generated_file_has_ownership_metadata(self) -> None:
        contents = lifecycle.starter_file_contents(
            sample_task(), sample_decision(), "https://example.test/repo"
        )
        for relative_name, generated in contents.items():
            self.assertIn("Generated by zoho-task-repo-lifecycle", generated, relative_name)
            self.assertIn("Task: BI1-T110", generated, relative_name)
            self.assertIn("Repository lifecycle version: 2", generated, relative_name)

    def test_fresh_generation_creates_complete_scaffold(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            with patch.object(lifecycle, "LOCAL_REPO_ROOT", Path(directory)):
                lifecycle.ensure_local_files(root, sample_task(), sample_decision(), "https://example.test/repo")
            lifecycle.verify_existing_repo_files(root)
            for relative_name in lifecycle.REQUIRED_GENERATED_FILES:
                self.assertTrue((root / relative_name).is_file(), relative_name)
                generated = (root / relative_name).read_text()
                self.assertNotRegex(generated, r"\{\{[A-Z_]+\}\}", relative_name)
                self.assertIn("Generated by zoho-task-repo-lifecycle", generated, relative_name)
                self.assertIn("Task: BI1-T110", generated, relative_name)
                self.assertIn("Repository lifecycle version: 2", generated, relative_name)
            mapping = json.loads((root / ".zoho-project-task.json").read_text())
            self.assertEqual(mapping["required_task_tag"], "repo-needed")
            self.assertEqual(mapping["task_key"], "BI1-T110")
            self.assertEqual(mapping["portal_id"], "898600220")
            self.assertEqual(mapping["project_id"], "2543412000001324010")
            self.assertEqual(mapping["task_id"], "110")

    def test_generation_requires_one_matching_zoho_api_scope(self) -> None:
        task = sample_task()
        task.pop("link")
        with self.assertRaisesRegex(
            lifecycle.ApplyBlocked,
            "exactly one matching portal/project/task API scope",
        ):
            lifecycle.starter_file_contents(
                task, sample_decision(), "https://example.test/repo"
            )

    def test_resume_repairs_missing_files_and_preserves_existing_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            readme = root / "README.md"
            readme.write_text("Zoho Task ID: 110\nUser work must survive.\n")
            with patch.object(lifecycle, "LOCAL_REPO_ROOT", Path(directory)):
                lifecycle.ensure_local_files(root, sample_task(), sample_decision(), "https://example.test/repo")
            self.assertIn("Generated by zoho-task-repo-lifecycle", readme.read_text())
            self.assertIn("User work must survive.", readme.read_text())
            lifecycle.verify_existing_repo_files(root)

    def test_legacy_workflow_migrates_once_and_rerun_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            with patch.object(lifecycle, "LOCAL_REPO_ROOT", Path(directory)):
                lifecycle.ensure_local_files(root, sample_task(), sample_decision(), "https://example.test/repo")
                workflow = root / ".github/workflows/repository-validation.yml"
                legacy = workflow.read_text().removeprefix(
                    lifecycle.ownership_header(
                        ".github/workflows/repository-validation.yml", "BI1-T110"
                    )
                )
                workflow.write_text(legacy)
                lifecycle.ensure_local_files(root, sample_task(), sample_decision(), "https://example.test/repo")
                migrated = workflow.read_text()
                self.assertIn("# Generated by zoho-task-repo-lifecycle", migrated)
                self.assertIn("# Task: BI1-T110", migrated)
                lifecycle.ensure_local_files(root, sample_task(), sample_decision(), "https://example.test/repo")
                self.assertEqual(workflow.read_text(), migrated)

    def test_known_legacy_coordination_files_are_owned_without_content_loss(self) -> None:
        cases = {
            "STATUS.md": "# BI1-T110 Status\n\nUser-maintained state.\n",
            "CODEX.md": "# Codex Instructions\n\nUse this repo for BI1-T110.\n",
            "docs/CURRENT_HANDOFF.md": "# Current Handoff\n\nBI1-T110 user history.\n",
            ".github/ISSUE_TEMPLATE/zoho-task.md": (
                "---\nname: Zoho Task\n---\n\n## Zoho Metadata\n\n## Acceptance Criteria\n"
            ),
            ".github/PULL_REQUEST_TEMPLATE.md": (
                "## Zoho Task\n\n## Validation\n\n## Safety\n"
            ),
        }
        for relative_name, existing in cases.items():
            with self.subTest(relative_name=relative_name):
                migrated = lifecycle.safe_legacy_migration_content(
                    relative_name,
                    existing,
                    "different canonical content",
                    "owned canonical content",
                    sample_decision(),
                )
                self.assertIsNotNone(migrated)
                assert migrated is not None
                self.assertTrue(migrated.endswith(existing))
                self.assertIn("Repository lifecycle version: 2", migrated)

    def test_validation_reports_missing_files_before_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                lifecycle.ApplyBlocked,
                r"Repository generation incomplete\. Missing files: .*STATUS\.md.*CLAUDE\.md.*CODEX\.md",
            ):
                lifecycle.verify_existing_repo_files(Path(directory))


if __name__ == "__main__":
    unittest.main()
