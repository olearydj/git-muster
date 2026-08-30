from __future__ import annotations

import io
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from git_muster import __version__, cli

runner = CliRunner()


@pytest.fixture(autouse=True)
def stable_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep width and color decisions independent of the developer's terminal."""
    monkeypatch.setenv("COLUMNS", "120")
    monkeypatch.setenv("LINES", "40")
    for variable in ("NO_COLOR", "FORCE_COLOR", "CLICOLOR_FORCE"):
        monkeypatch.delenv(variable, raising=False)


def run_git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def init_repository(tmp_path: Path, name: str) -> tuple[Path, Path]:
    remote = tmp_path / f"{name}-remote.git"
    repository = tmp_path / name
    remote.mkdir()
    repository.mkdir()
    run_git(remote, "init", "--bare")
    run_git(repository, "init", "-b", "main")
    run_git(repository, "config", "user.name", "Git Muster Tests")
    run_git(repository, "config", "user.email", "git-muster@example.invalid")
    return repository, remote


def commit(repository: Path, text: str, message: str) -> None:
    (repository / "README.md").write_text(text)
    run_git(repository, "add", "README.md")
    run_git(repository, "commit", "-m", message)


def make_repository(tmp_path: Path) -> Path:
    repository, remote = init_repository(tmp_path, "example")
    commit(repository, "example\n", "initial")
    run_git(repository, "remote", "add", "origin", str(remote))
    run_git(repository, "push", "-u", "origin", "main")

    run_git(repository, "switch", "-c", "feature/report")
    commit(repository, "example\nfeature\n", "start report")
    run_git(repository, "push", "-u", "origin", "feature/report")
    commit(repository, "example\nfeature\nlocal commit\n", "continue report")
    run_git(repository, "branch", "scratch", "main")
    run_git(repository, "config", "branch.scratch.remote", ".")
    run_git(repository, "config", "branch.scratch.merge", "refs/heads/main")
    run_git(repository, "branch", "published", "main")
    run_git(repository, "push", "origin", "published:published")
    run_git(repository, "worktree", "add", str(tmp_path / "linked-main"), "main")
    (repository / "notes.txt").write_text("not committed\n")
    return repository


def make_states_repository(tmp_path: Path) -> Path:
    """Build a repository holding every reportable branch state, on a detached HEAD."""
    repository, remote = init_repository(tmp_path, "states")
    commit(repository, "base\n", "initial")
    run_git(repository, "remote", "add", "origin", str(remote))
    run_git(repository, "push", "-u", "origin", "main")

    run_git(repository, "switch", "-c", "feature/removed-upstream")
    commit(repository, "base\nremoved\n", "removed upstream")
    run_git(repository, "push", "-u", "origin", "feature/removed-upstream")
    run_git(repository, "push", "origin", ":feature/removed-upstream")

    run_git(repository, "switch", "-c", "behind", "main")
    run_git(repository, "push", "-u", "origin", "behind")
    commit(repository, "base\nbehind\n", "remote only commit")
    run_git(repository, "push", "origin", "behind")
    run_git(repository, "reset", "--hard", "HEAD~1")

    run_git(repository, "switch", "-c", "diverged", "main")
    run_git(repository, "push", "-u", "origin", "diverged")
    commit(repository, "base\nremote\n", "remote side")
    run_git(repository, "push", "origin", "diverged")
    run_git(repository, "reset", "--hard", "HEAD~1")
    commit(repository, "base\nlocal\n", "local side")

    run_git(repository, "checkout", "--detach", "main")
    return repository


def stub_gh(monkeypatch: pytest.MonkeyPatch, result: tuple[int, str, str] | None) -> None:
    """Answer GitHub CLI invocations with a fixed command result, leaving Git alone."""
    real_command_result = cli.command_result

    def command_result(command: str, *args: str) -> tuple[int, str, str] | None:
        if command == "gh":
            return result
        return real_command_result(command, *args)

    monkeypatch.setattr(cli, "command_result", command_result)


def gh_rows(rows: list[dict[str, object]]) -> tuple[int, str, str]:
    return 0, json.dumps(rows), ""


def unstyle(text: str) -> str:
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)


@pytest.mark.parametrize(
    ("relative", "expected"),
    [("12 minutes ago", "12m"), ("3 weeks ago", "3w"), ("yesterday", "yesterday")],
)
def test_compact_age(relative: str, expected: str) -> None:
    assert cli.compact_age(relative) == expected


def test_fit_keeps_the_distinctive_end_of_a_branch_name() -> None:
    assert cli.fit("docs/very-long-branch", 12, "…") == "docs/…branch"


@pytest.mark.parametrize("ellipsis", ["…", ".."])
@pytest.mark.parametrize("limit", [1, 2, 3, 5, 8, 12, 18, 24])
def test_fit_never_exceeds_its_limit(limit: int, ellipsis: str) -> None:
    value = "feature/removed-upstream"

    assert len(cli.fit(value, limit, ellipsis)) == min(limit, len(value))


def test_report_combines_worktree_branch_and_pr_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = make_repository(tmp_path)
    monkeypatch.chdir(repository)
    stub_gh(
        monkeypatch,
        gh_rows(
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
            ]
        ),
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


def test_plain_output_uses_ascii_interface_glyphs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(make_repository(tmp_path))
    stub_gh(monkeypatch, gh_rows([]))

    assert cli.run_report(no_fetch=True, plain=True) == 0

    captured = capsys.readouterr()
    assert captured.out.isascii(), "built-in plain-mode text should use ASCII glyphs"
    assert "\x1b[" not in captured.out
    assert "1 with unpushed commits  |  1 local only" in captured.out


def test_plain_output_preserves_unicode_repository_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = make_repository(tmp_path)
    run_git(repository, "branch", "café", "main")
    monkeypatch.chdir(repository)
    stub_gh(monkeypatch, gh_rows([]))

    assert cli.run_report(no_fetch=True, plain=True) == 0

    captured = capsys.readouterr()
    assert "café" in captured.out
    assert "\x1b[" not in captured.out
    assert "·" not in captured.out


def test_report_uses_symbols_and_color_when_color_is_forced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(make_repository(tmp_path))
    monkeypatch.setenv("FORCE_COLOR", "1")
    stub_gh(monkeypatch, gh_rows([]))

    assert cli.run_report(no_fetch=True) == 0

    captured = capsys.readouterr()
    assert "\x1b[1m" in captured.out
    assert "─" in captured.out
    assert "▸ " in captured.out
    assert "  ·  " in captured.out
    # The current branch is dimmed up to its final slash and bold afterwards.
    assert "\x1b[2mfeature/\x1b[0m\x1b[1mreport\x1b[0m" in captured.out
    # Hyperlinks stay off when stdout is not an interactive terminal.
    assert "\x1b]8;;" not in captured.out


def test_no_color_wins_over_forced_color(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(make_repository(tmp_path))
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    stub_gh(monkeypatch, gh_rows([]))

    assert cli.run_report(no_fetch=True) == 0

    captured = capsys.readouterr()
    assert "\x1b[" not in captured.out
    assert "─" in captured.out, "NO_COLOR removes color but keeps Unicode symbols"


def test_symbols_fall_back_when_the_stream_cannot_encode_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(make_repository(tmp_path))
    monkeypatch.setattr(cli, "stream_supports", lambda text, stream: False)
    stub_gh(monkeypatch, gh_rows([]))

    assert cli.run_report(no_fetch=True) == 0

    captured = capsys.readouterr()
    assert captured.out.isascii()


def test_stream_supports_detects_encodable_text() -> None:
    ascii_stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    utf8_stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")

    assert cli.stream_supports("▸", utf8_stream) is True
    assert cli.stream_supports("plain", ascii_stream) is True
    assert cli.stream_supports("▸", ascii_stream) is False
    assert cli.stream_supports("▸", io.StringIO()) is True


def test_enable_ansi_escapes_is_a_no_op_off_windows() -> None:
    assert cli.enable_ansi_escapes() is (sys.platform != "win32")


def test_redirected_windows_output_still_honors_forced_color(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "stdout", io.StringIO())

    assert cli.enable_ansi_escapes() is True


def test_report_covers_behind_diverged_gone_and_detached_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(make_states_repository(tmp_path))
    stub_gh(monkeypatch, gh_rows([]))

    assert cli.run_report(no_fetch=True, plain=True) == 0

    captured = capsys.readouterr()
    assert "states :: detached HEAD" in captured.out
    assert "v behind 1" in captured.out
    assert "x ahead 1, behind 1" in captured.out
    assert "! remote gone" in captured.out
    assert "= working tree clean" in captured.out
    assert "1 with unpushed commits" in captured.out
    assert "2 behind" in captured.out
    assert "1 remote gone" in captured.out
    assert "WORKTREE" not in captured.out


def test_narrow_terminal_compacts_columns_without_breaking_alignment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(make_states_repository(tmp_path))
    monkeypatch.setenv("COLUMNS", "60")
    stub_gh(monkeypatch, gh_rows([]))

    assert cli.run_report(no_fetch=True, plain=True) == 0

    lines = capsys.readouterr().out.splitlines()
    rules = [index for index, line in enumerate(lines) if line and set(line) == {"-"}]
    width = len(lines[rules[0]])
    table_rows = lines[rules[0] + 2 : rules[1]]

    assert table_rows, "the table should still list branches"
    assert ".." in "\n".join(table_rows), "long branch names are truncated when space is short"
    assert all(len(line) <= width for line in table_rows), "rows must not overflow the rule"
    assert re.search(r"\b\d+[a-z]\b", "\n".join(table_rows)), "dates are compacted when narrow"


def test_report_warns_when_fetch_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = make_repository(tmp_path)
    run_git(repository, "remote", "set-url", "origin", str(tmp_path / "missing-remote.git"))
    monkeypatch.chdir(repository)
    stub_gh(monkeypatch, gh_rows([]))

    assert cli.run_report(plain=True) == 0

    captured = capsys.readouterr()
    assert "! Fetch failed - branch states may be out of date." in captured.out
    assert "use --no-fetch" in captured.out
    assert "BRANCH (" in captured.out, "the report still renders from on-disk refs"


def test_successful_fetch_is_silent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(make_repository(tmp_path))
    stub_gh(monkeypatch, gh_rows([]))

    assert cli.run_report(plain=True) == 0

    assert "Fetch failed" not in capsys.readouterr().out


def test_report_works_without_github_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(make_repository(tmp_path))
    stub_gh(monkeypatch, None)

    assert cli.run_report(no_fetch=True, plain=True) == 0

    captured = capsys.readouterr()
    assert "PULL REQUEST" not in captured.out
    assert "Pull request state unknown - the GitHub CLI is not installed." in captured.out
    assert "https://cli.github.com" in captured.out


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ((4, "", "gh auth login required"), "the GitHub CLI is not logged in"),
        (
            (1, "", "none of the git remotes point to a known GitHub host"),
            "no remote points at a known GitHub host",
        ),
        ((1, "", "dial tcp: lookup api.github.com: no such host"), "could not reach GitHub"),
        ((0, "not json", ""), "returned unexpected data"),
    ],
)
def test_report_explains_each_github_cli_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    result: tuple[int, str, str],
    expected: str,
) -> None:
    monkeypatch.chdir(make_repository(tmp_path))
    stub_gh(monkeypatch, result)

    assert cli.run_report(no_fetch=True, plain=True) == 0

    captured = capsys.readouterr()
    assert "PULL REQUEST" not in captured.out
    assert expected in captured.out


@pytest.mark.parametrize(
    ("code", "stderr", "expected"),
    [
        (4, "", "unauthenticated"),
        (1, "To get started with GitHub CLI, please run: gh auth login", "unauthenticated"),
        (1, "authentication token not found", "unauthenticated"),
        (1, "no git remotes found", "not-github"),
        (1, "none of the git remotes ... point to a known GitHub host", "not-github"),
        (1, "connection reset by peer", "unreachable"),
    ],
)
def test_github_failure_classification(code: int, stderr: str, expected: str) -> None:
    assert cli.github_failure(code, stderr) == expected


def test_github_pull_requests_rejects_unexpected_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_gh(monkeypatch, (0, '{"not": "a list"}', ""))
    assert cli.github_pull_requests() == ([], "unusable")

    stub_gh(monkeypatch, (0, '[1, "invalid", null]', ""))
    assert cli.github_pull_requests() == ([], "unusable")

    stub_gh(monkeypatch, gh_rows([]))
    assert cli.github_pull_requests() == ([], None)


def test_pull_request_selection_prefers_the_newest_active_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(make_repository(tmp_path))
    stub_gh(
        monkeypatch,
        gh_rows(
            [
                {
                    "headRefName": "feature/report",
                    "number": 39,
                    "state": "MERGED",
                    "url": "https://github.example/pull/39",
                },
                {
                    "headRefName": "feature/report",
                    "number": 12,
                    "state": "OPEN",
                    "reviewDecision": "APPROVED",
                    "url": "https://github.example/pull/12",
                },
                {
                    "headRefName": "feature/report",
                    "number": 5,
                    "state": "CLOSED",
                    "url": "https://github.example/pull/5",
                },
                {"headRefName": "main", "number": 7, "state": "OPEN"},
                {"number": 8, "state": "OPEN"},
            ]
        ),
    )

    assert cli.run_report(no_fetch=True, plain=True) == 0

    captured = capsys.readouterr()
    assert "#12 approved" in captured.out
    assert "#39 merged" not in captured.out
    assert "#5 closed" not in captured.out
    assert "#7" not in captured.out, "pull requests targeting the default branch are ignored"


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


def test_git_failures_explain_themselves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "command_result", lambda command, *args: (128, "", "fatal: broken"))
    with pytest.raises(RuntimeError, match="git status failed: fatal: broken"):
        cli.git_output("status")

    monkeypatch.setattr(cli, "command_result", lambda command, *args: (1, "", ""))
    with pytest.raises(RuntimeError, match="exit status 1"):
        cli.git_output("status")

    monkeypatch.setattr(cli, "command_result", lambda command, *args: None)
    with pytest.raises(RuntimeError, match="git is not installed"):
        cli.git_output("status")


def test_command_result_reports_missing_commands() -> None:
    assert cli.command_result("git-muster-does-not-exist") is None
    assert cli.command_output("git-muster-does-not-exist") is None
    assert cli.command_output("git", "rev-parse", "--resolve-git-dir", "/does/not/exist") is None


def test_operational_git_errors_exit_with_status_two(monkeypatch: pytest.MonkeyPatch) -> None:
    def run_report(*, no_fetch: bool, plain: bool) -> int:
        raise RuntimeError("git for-each-ref failed: fatal: broken")

    monkeypatch.setattr(cli, "run_report", run_report)

    result = runner.invoke(cli.app, [])

    assert result.exit_code == 2
    assert "git muster: git for-each-ref failed: fatal: broken" in result.output


def test_report_exit_status_is_propagated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "run_report", lambda **_: 2)

    assert runner.invoke(cli.app, []).exit_code == 2


def test_help_explains_usage_states_and_effects() -> None:
    result = runner.invoke(cli.app, ["--help"])
    help_text = " ".join(unstyle(result.stdout).split())

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
    assert version_result.stdout == f"git-muster {__version__}\n"


def test_typer_interface_passes_report_options(monkeypatch: pytest.MonkeyPatch) -> None:
    received: dict[str, bool] = {}

    def run_report(*, no_fetch: bool, plain: bool) -> int:
        received.update(no_fetch=no_fetch, plain=plain)
        return 0

    monkeypatch.setattr(cli, "run_report", run_report)

    result = runner.invoke(cli.app, ["--no-fetch", "--plain"])

    assert result.exit_code == 0
    assert received == {"no_fetch": True, "plain": True}


def test_entrypoint_runs_the_application(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["git-muster", "--version"])

    with pytest.raises(SystemExit) as exit_info:
        cli.entrypoint()

    assert exit_info.value.code == 0


def test_module_execution_reports_the_version() -> None:
    import git_muster.__main__  # noqa: F401  (import side effect only)

    result = subprocess.run(
        [sys.executable, "-m", "git_muster", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == f"git-muster {__version__}"


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"isDraft": True, "state": "OPEN"}, "draft"),
        ({"isDraft": True, "state": "CLOSED"}, "closed"),
        ({"isDraft": True, "state": "MERGED"}, "merged"),
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
    assert cli.hyperlink("#42", "", enabled=True) == "#42"
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


def make_dirty_repository(tmp_path: Path) -> Path:
    """Build a repository holding staged, modified, untracked, and conflicted paths."""
    repository, remote = init_repository(tmp_path, "dirty")
    commit(repository, "base\n", "initial")
    (repository / "tracked.txt").write_text("tracked\n")
    run_git(repository, "add", "tracked.txt")
    run_git(repository, "commit", "-m", "add tracked file")
    run_git(repository, "remote", "add", "origin", str(remote))
    run_git(repository, "push", "-u", "origin", "main")

    run_git(repository, "switch", "-c", "left", "main")
    commit(repository, "left\n", "left side")
    run_git(repository, "switch", "main")
    commit(repository, "main\n", "main side")
    merge = subprocess.run(
        ["git", "merge", "left"],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    assert merge.returncode != 0, "the merge is expected to conflict"

    (repository / "staged.txt").write_text("staged\n")
    run_git(repository, "add", "staged.txt")
    (repository / "tracked.txt").write_text("modified\n")
    for index in range(10):
        (repository / f"scratch-{index}.txt").write_text("scratch\n")
    return repository


def make_quiet_repository(tmp_path: Path) -> Path:
    """Build a repository with a single, fully synchronized branch."""
    repository, remote = init_repository(tmp_path, "quiet")
    commit(repository, "base\n", "initial")
    run_git(repository, "remote", "add", "origin", str(remote))
    run_git(repository, "push", "-u", "origin", "main")
    return repository


def test_worktree_states_are_counted_and_listed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(make_dirty_repository(tmp_path))
    stub_gh(monkeypatch, gh_rows([]))

    assert cli.run_report(no_fetch=True, plain=True) == 0

    captured = capsys.readouterr()
    assert "dirty: 1 staged | 1 modified | 10 untracked | 1 conflicted" in captured.out
    assert "13 uncommitted paths:" in captured.out
    assert "...and 5 more" in captured.out


def test_synchronized_repository_reports_nothing_to_do(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(make_quiet_repository(tmp_path))
    stub_gh(monkeypatch, gh_rows([]))

    assert cli.run_report(no_fetch=True, plain=True) == 0

    captured = capsys.readouterr()
    assert "= in sync" in captured.out
    assert "= working tree clean" in captured.out
    assert "unpushed" not in captured.out
    assert "local only" not in captured.out


def test_interactive_terminal_shows_progress_and_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(make_repository(tmp_path))
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    stub_gh(
        monkeypatch,
        gh_rows(
            [
                {
                    "headRefName": "feature/report",
                    "number": 42,
                    "state": "OPEN",
                    "reviewDecision": "APPROVED",
                    "url": "https://github.example/pull/42",
                }
            ]
        ),
    )

    assert cli.run_report() == 0

    captured = capsys.readouterr()
    assert "fetching..." in captured.out
    assert "\r           \r" in captured.out
    assert "\x1b]8;;https://github.example/pull/42\x1b\\" in captured.out
    assert "Fetch failed" not in captured.out


def test_narrow_terminal_sheds_the_worktree_column(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(make_repository(tmp_path))
    monkeypatch.setenv("COLUMNS", "60")
    stub_gh(
        monkeypatch,
        gh_rows(
            [
                {
                    "headRefName": "feature/report",
                    "number": 4242,
                    "state": "OPEN",
                    "reviewDecision": "CHANGES_REQUESTED",
                    "url": "https://github.example/pull/4242",
                }
            ]
        ),
    )

    assert cli.run_report(no_fetch=True, plain=True) == 0

    lines = capsys.readouterr().out.splitlines()
    rules = [index for index, line in enumerate(lines) if line and set(line) == {"-"}]
    width = len(lines[rules[0]])
    table_rows = lines[rules[0] + 2 : rules[1]]

    assert "WORKTREE" in lines[rules[0] + 1]
    assert all(len(line) <= width for line in table_rows)


def test_a_closed_draft_never_outranks_an_open_pull_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(make_repository(tmp_path))
    stub_gh(
        monkeypatch,
        gh_rows(
            [
                {
                    "headRefName": "feature/report",
                    "number": 99,
                    "state": "CLOSED",
                    "isDraft": True,
                    "url": "https://github.example/pull/99",
                },
                {
                    "headRefName": "feature/report",
                    "number": 12,
                    "state": "OPEN",
                    "url": "https://github.example/pull/12",
                },
            ]
        ),
    )

    assert cli.run_report(no_fetch=True, plain=True) == 0

    captured = capsys.readouterr()
    assert "#12 open" in captured.out
    assert "#99" not in captured.out


def test_incomplete_pull_request_rows_are_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(make_repository(tmp_path))
    stub_gh(
        monkeypatch,
        gh_rows(
            [
                {
                    "headRefName": "feature/report",
                    "number": 12,
                    "state": "OPEN",
                    "url": "https://github.example/pull/12",
                },
                {"headRefName": "published", "state": "OPEN"},
                {"number": 8, "state": "OPEN"},
                {"headRefName": "scratch", "number": True, "state": "OPEN"},
                {"headRefName": "scratch", "number": 0, "state": "OPEN"},
            ]
        ),
    )

    assert cli.run_report(no_fetch=True, plain=True) == 0

    captured = capsys.readouterr()
    assert "#12 open" in captured.out
    assert "#None" not in captured.out
    assert "#True" not in captured.out
    assert "#0 " not in captured.out
    assert "PULL REQUEST" in captured.out


def test_a_payload_without_usable_rows_reports_unexpected_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(make_repository(tmp_path))
    stub_gh(monkeypatch, gh_rows([{"head": "feature/report", "id": "PR_1"}]))

    assert cli.run_report(no_fetch=True, plain=True) == 0

    captured = capsys.readouterr()
    assert "PULL REQUEST" not in captured.out
    assert "returned unexpected data" in captured.out
