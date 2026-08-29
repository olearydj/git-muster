from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from git_muster import cli

runner = CliRunner()


def run_git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def make_repository(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    repository = tmp_path / "example"
    remote.mkdir()
    repository.mkdir()
    run_git(remote, "init", "--bare")
    run_git(repository, "init", "-b", "main")
    run_git(repository, "config", "user.name", "Git Muster Tests")
    run_git(repository, "config", "user.email", "git-muster@example.invalid")

    readme = repository / "README.md"
    readme.write_text("example\n")
    run_git(repository, "add", "README.md")
    run_git(repository, "commit", "-m", "initial")
    run_git(repository, "remote", "add", "origin", str(remote))
    run_git(repository, "push", "-u", "origin", "main")

    run_git(repository, "switch", "-c", "feature/report")
    readme.write_text("example\nfeature\n")
    run_git(repository, "commit", "-am", "start report")
    run_git(repository, "push", "-u", "origin", "feature/report")
    readme.write_text("example\nfeature\nlocal commit\n")
    run_git(repository, "commit", "-am", "continue report")
    run_git(repository, "branch", "scratch", "main")
    run_git(repository, "config", "branch.scratch.remote", ".")
    run_git(repository, "config", "branch.scratch.merge", "refs/heads/main")
    run_git(repository, "branch", "published", "main")
    run_git(repository, "push", "origin", "published:published")
    run_git(repository, "worktree", "add", str(tmp_path / "linked-main"), "main")
    (repository / "notes.txt").write_text("not committed\n")
    return repository


def stub_gh(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, object]] | None) -> None:
    real_command_output = cli.command_output

    def command_output(command: str, *args: str) -> str | None:
        if command == "gh":
            return None if rows is None else json.dumps(rows)
        return real_command_output(command, *args)

    monkeypatch.setattr(cli, "command_output", command_output)


@pytest.mark.parametrize(
    ("relative", "expected"),
    [("12 minutes ago", "12m"), ("3 weeks ago", "3w"), ("yesterday", "yesterday")],
)
def test_compact_age(relative: str, expected: str) -> None:
    assert cli.compact_age(relative) == expected


def test_fit_keeps_the_distinctive_end_of_a_branch_name() -> None:
    assert cli.fit("docs/very-long-branch", 12, "…") == "docs/…branch"


def test_report_combines_worktree_branch_and_pr_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = make_repository(tmp_path)
    monkeypatch.chdir(repository)
    stub_gh(
        monkeypatch,
        [
            {
                "headRefName": "feature/report",
                "number": 42,
                "state": "OPEN",
                "isDraft": True,
                "reviewDecision": "",
                "url": "https://github.example/pull/42",
            },
            {
                "headRefName": "published",
                "number": 43,
                "state": "OPEN",
                "isDraft": False,
                "reviewDecision": "CHANGES_REQUESTED",
                "url": "https://github.example/pull/43",
            },
        ],
    )

    assert cli.run_report(no_fetch=True, plain=True) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert "example :: feature/report" in captured.out
    assert "dirty: 1 untracked" in captured.out
    assert "feature/report" in captured.out
    assert "^ ahead 1" in captured.out
    assert "#42 draft" in captured.out
    assert "#43 changes requested" in captured.out
    assert "scratch" in captured.out
    assert ". local only" in captured.out
    assert "published" in captured.out
    assert "= in sync" in captured.out
    assert "WORKTREE" in captured.out
    assert "linked-main" in captured.out
    assert "1 other linked worktree:" in captured.out
    assert f"main -> {tmp_path / 'linked-main'}" in captured.out
    assert "1 with unpushed commits" in captured.out
    assert "1 local only" in captured.out
    assert "?? notes.txt" in captured.out


def test_report_works_without_github_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = make_repository(tmp_path)
    monkeypatch.chdir(repository)
    stub_gh(monkeypatch, None)

    assert cli.run_report(no_fetch=True, plain=True) == 0

    captured = capsys.readouterr()
    assert "PULL REQUEST" not in captured.out
    assert "Pull request state unknown" in captured.out


def test_outside_repository_is_actionable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    assert cli.run_report(no_fetch=True, plain=True) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "git muster: current directory is not inside a Git repository\n"


def test_help_explains_usage_states_and_effects() -> None:
    result = runner.invoke(cli.app, ["--help"])
    unstyled = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", result.stdout)
    help_text = " ".join(unstyled.split())

    assert result.exit_code == 0
    assert "Inspect every local branch" in help_text
    assert "--no-fetch" in help_text
    assert "--plain" in help_text
    assert "Branch states" in help_text
    assert "State" in help_text
    assert "Meaning" in help_text
    assert "│" in result.stdout
    assert "local only" in help_text
    assert "remote gone" in help_text
    assert "Linked worktrees" in help_text
    assert "checkout paths" in help_text
    assert "Effects" in help_text
    assert "git fetch --all --prune" in help_text


def test_short_help_flag_and_version() -> None:
    help_result = runner.invoke(cli.app, ["-h"])
    version_result = runner.invoke(cli.app, ["--version"])

    assert help_result.exit_code == 0
    assert "Report options" in help_result.stdout
    assert version_result.exit_code == 0
    assert version_result.stdout == "git-muster 0.3.1\n"


def test_typer_interface_passes_report_options(monkeypatch: pytest.MonkeyPatch) -> None:
    received: dict[str, bool] = {}

    def run_report(*, no_fetch: bool, plain: bool) -> int:
        received.update(no_fetch=no_fetch, plain=plain)
        return 0

    monkeypatch.setattr(cli, "run_report", run_report)

    result = runner.invoke(cli.app, ["--no-fetch", "--plain"])

    assert result.exit_code == 0
    assert received == {"no_fetch": True, "plain": True}


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"isDraft": True, "state": "OPEN"}, "draft"),
        ({"state": "OPEN", "reviewDecision": "APPROVED"}, "approved"),
        ({"state": "OPEN", "reviewDecision": "CHANGES_REQUESTED"}, "changes requested"),
        ({"state": "OPEN", "reviewDecision": ""}, "open"),
        ({"state": "MERGED"}, "merged"),
        ({"state": "CLOSED"}, "closed"),
    ],
)
def test_pull_request_status(row: dict[str, object], expected: str) -> None:
    assert cli.pull_request_status(row) == expected


def test_hyperlink_is_only_emitted_when_enabled() -> None:
    url = "https://github.example/pull/42"
    assert cli.hyperlink("#42", url, enabled=False) == "#42"
    assert cli.hyperlink("#42", url, enabled=True) == (
        "\033]8;;https://github.example/pull/42\033\\\033[4m#42\033[24m\033]8;;\033\\"
    )


def test_publication_is_independent_of_a_local_upstream() -> None:
    publication, counts, gone = cli.publication_for(
        "topic",
        "main",
        "[ahead 1]",
        "",
        "",
        {"origin/topic"},
        {"origin"},
    )

    assert publication == "origin/topic"
    assert counts == (0, 0)
    assert gone is False


def test_missing_same_name_remote_is_not_reported_as_local_only() -> None:
    publication, counts, gone = cli.publication_for(
        "topic",
        "origin/topic",
        "[gone]",
        "",
        "",
        set(),
        {"origin"},
    )

    assert publication == "origin/topic"
    assert counts is None
    assert gone is True
