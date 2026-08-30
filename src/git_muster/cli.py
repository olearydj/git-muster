"""Command-line branch status report."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

import typer
from rich.console import Console
from rich.padding import Padding
from rich.table import Table
from typer.core import TyperCommand

from git_muster import __version__

HELP = (
    "Inspect every local branch in the current Git repository. Git Muster separates "
    "uncommitted work from committed branch state, then shows which branches are "
    "unpublished, ahead, behind, or diverged from their remote branch. When the "
    "GitHub CLI is authenticated, pull-request state appears in the same report."
)

EPILOG = """
[bold]Examples[/bold]

  [cyan]git muster[/cyan]
  Refresh remote-tracking refs, then report every local branch.

  [cyan]git muster --no-fetch[/cyan]
  Use the remote-tracking data already on disk.

  [cyan]git muster --plain[/cyan]
  Emit stable output with ASCII decorations and no color for logs and pipes.

[bold]Linked worktrees[/bold]

The [cyan]WORKTREE[/cyan] column appears only when another checkout holds a branch. Full
checkout paths follow the branch table; other worktrees are not inspected or changed.

[bold]Effects[/bold]

The default run executes [cyan]git fetch --all --prune[/cyan]. It never switches, deletes,
merges, rebases, or pushes branches. Use [cyan]--no-fetch[/cyan] for a fully read-only run.
"""

SYMBOL_GLYPHS = {
    "current": "▸",
    "synced": "✓",
    "ahead": "↑",
    "behind": "↓",
    "diverged": "⇅",
    "gone": "✕",
    "local": "·",
    "rule": "─",
    "ellipsis": "…",
    "notice": "▲",
    "separator": "·",
}

ASCII_GLYPHS = {
    "current": ">",
    "synced": "=",
    "ahead": "^",
    "behind": "v",
    "diverged": "x",
    "gone": "!",
    "local": ".",
    "rule": "-",
    "ellipsis": "..",
    "notice": "!",
    "separator": "|",
}

PR_LIMIT = 100
PR_FIELDS = "headRefName,number,state,isDraft,reviewDecision,url"
REPOSITORY_FIELDS = "nameWithOwner,url,visibility,isFork,parent,isArchived"
ACTIVE_PR_STATES = {"draft", "open", "approved", "changes requested"}

PR_NOTICES: dict[str, tuple[str, ...]] = {
    "missing": (
        "Pull request state unknown - the GitHub CLI is not installed.",
        "  Install it from https://cli.github.com, then run: gh auth login",
    ),
    "unauthenticated": (
        "Pull request state unknown - the GitHub CLI is not logged in.",
        "  Run: gh auth login",
    ),
    "not-github": ("Pull request state unknown - no remote points at a known GitHub host.",),
    "unreachable": (
        "Pull request state unknown - the GitHub CLI could not reach GitHub.",
        "  Run: gh pr list --state all --limit 1",
    ),
    "unusable": (
        "Pull request state unknown - the GitHub CLI returned unexpected data.",
        "  Run: gh pr list --state all --limit 1",
    ),
}


def branch_states_table() -> Table:
    """Build the branch-state reference shown in command help."""
    table = Table(
        title="Branch states",
        title_justify="left",
        title_style="bold",
        border_style="dim",
    )
    table.add_column("State", no_wrap=True)
    table.add_column("Meaning")
    table.add_row("[green]in sync[/green]", "Local and remote branch tips agree.")
    table.add_row("[yellow]ahead N[/yellow]", "N local commits have not been pushed.")
    table.add_row("[blue]behind N[/blue]", "N remote commits are missing locally.")
    table.add_row("[red]ahead N, behind M[/red]", "The histories have diverged.")
    table.add_row("[red]remote gone[/red]", "The configured push branch no longer exists.")
    table.add_row("[dim]local only[/dim]", "No push destination or matching remote branch exists.")
    return table


class MusterCommand(TyperCommand):
    """Typer command that appends Git Muster's state reference table."""

    def format_help(self, ctx: Any, formatter: Any) -> None:
        super().format_help(ctx, formatter)
        Console().print(Padding(branch_states_table(), (0, 1, 1, 1)))


app = typer.Typer(
    name="git muster",
    help=HELP,
    epilog=EPILOG,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    rich_markup_mode="rich",
    pretty_exceptions_enable=False,
)


def command_result(command: str, *args: str) -> tuple[int, str, str] | None:
    """Run a command, returning its status and streams, or ``None`` when it is unavailable."""
    try:
        completed = subprocess.run(
            [command, *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return completed.returncode, completed.stdout.rstrip("\r\n"), completed.stderr.strip()


def command_output(command: str, *args: str) -> str | None:
    """Run a command quietly, returning ``None`` when it is unavailable or fails."""
    result = command_result(command, *args)
    if result is None or result[0] != 0:
        return None
    return result[1]


def git_output(*args: str) -> str:
    """Run a required Git command or raise a concise operational error."""
    result = command_result("git", *args)
    if result is None:
        raise RuntimeError(f"git {' '.join(args)} failed: git is not installed")
    code, stdout, stderr = result
    if code != 0:
        detail = stderr.splitlines()[0] if stderr else f"exit status {code}"
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return stdout


def stream_supports(text: str, stream: Any) -> bool:
    """Report whether a text stream can encode every character in ``text``."""
    encoding = getattr(stream, "encoding", None)
    if not encoding:
        return True
    try:
        text.encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def enable_ansi_escapes() -> bool:
    """Turn on virtual-terminal processing where needed and report ANSI support."""
    if sys.platform != "win32":
        return True
    if not sys.stdout.isatty():
        # Redirected output has no console mode to configure, so leave the
        # decision to --plain, NO_COLOR, and FORCE_COLOR.
        return True
    try:  # pragma: no cover - Windows-only console setup
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError, ValueError):  # pragma: no cover - defensive
        return False


def compact_age(relative: str) -> str:
    """Shorten a Git relative date when terminal space is constrained."""
    match = re.match(r"^(\d+)\s+(\w)", relative)
    if match:
        return "".join(match.groups())
    return relative.removesuffix(" ago")


def fit(value: str, limit: int, ellipsis: str) -> str:
    """Middle-truncate text to exactly ``limit`` cells, retaining its recognizable ending."""
    if len(value) <= limit:
        return value
    if limit <= len(ellipsis):
        return value[:limit]
    budget = limit - len(ellipsis)
    keep_end = max(1, int(budget * 0.6))
    keep_start = budget - keep_end
    if keep_start <= 0:
        return ellipsis + value[-budget:]
    return value[:keep_start] + ellipsis + value[-keep_end:]


@dataclass(frozen=True)
class PullRequest:
    """Pull-request presentation data for one branch."""

    text: str
    colour: Callable[[str], str]
    number: int | None = None
    url: str = ""


@dataclass(frozen=True)
class GitHubRepository:
    """GitHub identity and presentation metadata for the current repository."""

    owner: str
    name: str
    url: str
    visibility: str = ""
    is_fork: bool = False
    parent_url: str = ""
    is_archived: bool = False


@dataclass(frozen=True)
class Branch:
    """Collected status for one local branch."""

    name: str
    upstream: str | None
    publication: str | None
    remote: str
    state_text: str
    state_mark: str
    state_colour: Callable[[str], str]
    updated: str
    pull_request: PullRequest
    is_current: bool
    worktree: str
    worktree_path: str


def hyperlink(text: str, url: str, *, enabled: bool) -> str:
    """Make text clickable with an OSC 8 link on a capable interactive terminal."""
    if not enabled or not url:
        return text
    underlined = f"\033[4m{text}\033[24m"
    return f"\033]8;;{url}\033\\{underlined}\033]8;;\033\\"


def github_repository_url(remote_url: str) -> str:
    """Turn a GitHub clone URL into its canonical HTTPS repository page."""
    scp_match = re.fullmatch(r"(?:[^@/:]+@)?([^/:]+):(.+)", remote_url)
    if scp_match and "://" not in remote_url:
        host, path = scp_match.groups()
    else:
        parsed = urlsplit(remote_url)
        if parsed.scheme not in {"git", "http", "https", "ssh"}:
            return ""
        host, path = parsed.hostname or "", parsed.path

    if host.lower() != "github.com":
        return ""
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not re.fullmatch(r"[-A-Za-z0-9_.]+/[-A-Za-z0-9_.]+", path):
        return ""
    return f"https://github.com/{path}"


def repository_github_url(remotes: set[str]) -> str:
    """Find the repository page, preferring the conventional origin remote."""
    for remote in sorted(remotes, key=lambda name: (name != "origin", name)):
        remote_url = command_output("git", "remote", "get-url", remote) or ""
        if url := github_repository_url(remote_url):
            return url
    return ""


def github_repository(repository_url: str) -> GitHubRepository:
    """Read repository metadata from GitHub, retaining URL-derived identity on failure."""
    owner, name = urlsplit(repository_url).path.strip("/").split("/", 1)
    fallback = GitHubRepository(owner, name, repository_url)
    result = command_result("gh", "repo", "view", f"{owner}/{name}", "--json", REPOSITORY_FIELDS)
    if result is None or result[0] != 0:
        return fallback
    try:
        payload = json.loads(result[1])
    except (json.JSONDecodeError, TypeError, ValueError):
        return fallback
    if not isinstance(payload, dict):
        return fallback

    canonical_url = github_repository_url(str(payload.get("url", ""))) or repository_url
    canonical_name = payload.get("nameWithOwner")
    if isinstance(canonical_name, str) and re.fullmatch(
        r"[-A-Za-z0-9_.]+/[-A-Za-z0-9_.]+", canonical_name
    ):
        owner, name = canonical_name.split("/", 1)
        canonical_url = f"https://github.com/{canonical_name}"
    else:
        owner, name = urlsplit(canonical_url).path.strip("/").split("/", 1)

    visibility = payload.get("visibility")
    visibility = (
        visibility.lower()
        if isinstance(visibility, str) and visibility.upper() in {"PUBLIC", "PRIVATE", "INTERNAL"}
        else ""
    )

    parent_url = ""
    parent = payload.get("parent")
    if isinstance(parent, dict):
        parent_url = github_repository_url(str(parent.get("url", "")))
        parent_name = parent.get("nameWithOwner")
        if (
            not parent_url
            and isinstance(parent_name, str)
            and re.fullmatch(r"[-A-Za-z0-9_.]+/[-A-Za-z0-9_.]+", parent_name)
        ):
            parent_url = f"https://github.com/{parent_name}"

    return GitHubRepository(
        owner=owner,
        name=name,
        url=canonical_url,
        visibility=visibility,
        is_fork=payload.get("isFork") is True,
        parent_url=parent_url,
        is_archived=payload.get("isArchived") is True,
    )


def pull_request_status(row: dict[str, object]) -> str:
    """Normalize GitHub's PR and review fields into a compact status."""
    state = str(row.get("state", "")).upper()
    if state == "MERGED":
        return "merged"
    if state == "CLOSED":
        return "closed"
    if row.get("isDraft"):
        return "draft"
    decision = str(row.get("reviewDecision", "")).upper()
    if decision == "APPROVED":
        return "approved"
    if decision == "CHANGES_REQUESTED":
        return "changes requested"
    return "open"


def github_failure(code: int, stderr: str) -> str:
    """Classify why the GitHub CLI refused to report pull requests."""
    message = stderr.lower()
    if (
        "no git remotes" in message
        or "known github host" in message
        or "not a git repository" in message
    ):
        return "not-github"
    if code == 4 or "gh auth login" in message or "authentication" in message:
        return "unauthenticated"
    return "unreachable"


def github_pull_requests() -> tuple[list[dict[str, object]], str | None]:
    """Read pull requests through the GitHub CLI, explaining any failure."""
    result = command_result(
        "gh", "pr", "list", "--state", "all", "--limit", str(PR_LIMIT), "--json", PR_FIELDS
    )
    if result is None:
        return [], "missing"
    code, stdout, stderr = result
    if code != 0:
        return [], github_failure(code, stderr)
    try:
        parsed = json.loads(stdout)
    except (json.JSONDecodeError, TypeError, ValueError):
        return [], "unusable"
    if not isinstance(parsed, list):
        return [], "unusable"
    rows = [row for row in parsed if isinstance(row, dict)]
    if parsed and not rows:
        return [], "unusable"
    return rows, None


def parse_track(track: str) -> tuple[int, int] | None:
    """Return ahead/behind counts from Git's tracking decoration."""
    if "gone" in track:
        return None
    ahead_match = re.search(r"ahead (\d+)", track)
    behind_match = re.search(r"behind (\d+)", track)
    return (
        int(ahead_match.group(1)) if ahead_match else 0,
        int(behind_match.group(1)) if behind_match else 0,
    )


def publication_for(
    name: str,
    upstream: str,
    upstream_track: str,
    push: str,
    push_track: str,
    remote_refs: set[str],
    remotes: set[str],
) -> tuple[str | None, tuple[int, int] | None, bool]:
    """Find the branch's push/remote counterpart without conflating its upstream."""
    if push:
        gone = "gone" in push_track and push not in remote_refs
        return push, parse_track(push_track), gone

    matching = sorted(ref for ref in remote_refs if ref.partition("/")[2] == name)
    if matching:
        publication = (
            upstream
            if upstream in matching
            else f"origin/{name}"
            if f"origin/{name}" in matching
            else matching[0]
        )
        track = upstream_track if publication == upstream else ""
        return publication, parse_track(track), False

    upstream_remote, separator, upstream_branch = upstream.partition("/")
    if (
        separator
        and upstream_remote in remotes
        and upstream_branch == name
        and "gone" in upstream_track
    ):
        return upstream, None, True
    return None, (0, 0), False


def run_report(*, no_fetch: bool = False, plain: bool = False) -> int:
    """Run the report and return a process exit status."""
    repo_root = command_output("git", "rev-parse", "--show-toplevel")
    if repo_root is None:
        print("git muster: current directory is not inside a Git repository", file=sys.stderr)
        return 2

    interactive = sys.stdout.isatty()
    ansi_ready = enable_ansi_escapes()
    forced_colour = bool(os.environ.get("FORCE_COLOR") or os.environ.get("CLICOLOR_FORCE"))
    use_colour = (
        not plain
        and ansi_ready
        and not os.environ.get("NO_COLOR")
        and (interactive or forced_colour)
    )
    use_links = not plain and ansi_ready and interactive
    modern_terminal = sys.platform != "win32" or bool(
        os.environ.get("WT_SESSION")
        or os.environ.get("TERM_PROGRAM")
        or os.environ.get("TERMINAL_EMULATOR")
    )
    use_symbols = (
        not plain
        and modern_terminal
        and stream_supports("".join(SYMBOL_GLYPHS.values()), sys.stdout)
    )
    glyph = SYMBOL_GLYPHS if use_symbols else ASCII_GLYPHS

    def paint(code: str) -> Callable[[str], str]:
        return lambda text: f"\033[{code}m{text}\033[0m" if use_colour else text

    bold = paint("1")
    dim = paint("2")
    red = paint("31")
    green = paint("32")
    yellow = paint("33")
    blue = paint("34")

    terminal_width = max(60, min(shutil.get_terminal_size((100, 24)).columns, 160))

    fetch_failed = False
    if not no_fetch:
        if interactive:
            print(dim("fetching..."), end="", flush=True)
        fetch_failed = command_output("git", "fetch", "--all", "--prune", "--quiet") is None
        if interactive:
            print("\r           \r", end="", flush=True)

    default_branch = command_output("git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    default_branch = default_branch.removeprefix("origin/") if default_branch else "main"

    pr_rows, pr_reason = github_pull_requests()
    pull_requests: dict[str, PullRequest] = {}
    pr_ranks: dict[str, tuple[bool, int]] = {}
    usable_rows = 0
    for row in pr_rows:
        name = row.get("headRefName")
        number = row.get("number")
        # bool is a subclass of int, so the number's type is compared exactly.
        if not isinstance(name, str) or not name or type(number) is not int or number <= 0:
            continue
        usable_rows += 1
        if name == default_branch:
            continue
        state = pull_request_status(row)
        rank = (state in ACTIVE_PR_STATES, number)
        if name in pr_ranks and pr_ranks[name] >= rank:
            continue
        colour = (
            green
            if state in {"approved", "merged"}
            else red
            if state == "changes requested"
            else yellow
            if state == "draft"
            else dim
            if state == "closed"
            else blue
        )
        pr_ranks[name] = rank
        pull_requests[name] = PullRequest(
            f"#{number} {state}",
            colour,
            number,
            str(row.get("url", "")),
        )
    if pr_rows and not usable_rows:
        pr_reason = "unusable"

    current = command_output("git", "branch", "--show-current") or ""
    dirty = git_output("status", "--short", "--untracked-files=all")
    dirty_lines = dirty.splitlines() if dirty else []
    worktree_counts = {"staged": 0, "modified": 0, "untracked": 0, "conflicted": 0}
    conflict_codes = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
    for line in dirty_lines:
        code = line[:2]
        if code == "??":
            worktree_counts["untracked"] += 1
        elif code in conflict_codes:
            worktree_counts["conflicted"] += 1
        else:
            if code[0] != " ":
                worktree_counts["staged"] += 1
            if code[1] != " ":
                worktree_counts["modified"] += 1

    worktree_parts = [f"{count} {kind}" for kind, count in worktree_counts.items() if count]

    remote_rows = git_output(
        "for-each-ref",
        "refs/remotes",
        "--format=%(refname:short)\t%(symref)",
    )
    remote_refs = {
        ref
        for row in remote_rows.splitlines()
        for ref, symref in [row.split("\t", 1)]
        if not symref
    }
    remotes = set(git_output("remote").splitlines())
    repo_url = repository_github_url(remotes)
    github_repo = github_repository(repo_url) if repo_url else None

    raw_branches = git_output(
        "for-each-ref",
        "--sort=-committerdate",
        "refs/heads",
        "--format=%(refname:short)\t%(upstream:short)\t%(upstream:track)\t%(push:short)\t%(push:track)\t%(committerdate:relative)\t%(worktreepath)",
    )
    branches: list[Branch] = []
    for line in raw_branches.splitlines():
        name, upstream, upstream_track, push, push_track, updated, worktree_path = line.split(
            "\t", 6
        )
        publication, counts, gone = publication_for(
            name,
            upstream,
            upstream_track,
            push,
            push_track,
            remote_refs,
            remotes,
        )
        if publication and counts == (0, 0) and publication != upstream and publication != push:
            raw_counts = git_output(
                "rev-list", "--left-right", "--count", f"{publication}...{name}"
            )
            behind_count, ahead_count = (int(value) for value in raw_counts.split())
            counts = ahead_count, behind_count

        ahead_count, behind_count = counts or (0, 0)
        if gone:
            state_text, state_colour, state_mark = "remote gone", red, glyph["gone"]
        elif not publication:
            state_text, state_colour, state_mark = "local only", dim, glyph["local"]
        elif ahead_count and behind_count:
            state_text = f"ahead {ahead_count}, behind {behind_count}"
            state_colour, state_mark = red, glyph["diverged"]
        elif ahead_count:
            state_text = f"ahead {ahead_count}"
            state_colour, state_mark = yellow, glyph["ahead"]
        elif behind_count:
            state_text = f"behind {behind_count}"
            state_colour, state_mark = blue, glyph["behind"]
        else:
            state_text, state_colour, state_mark = "in sync", green, glyph["synced"]

        remote = "-"
        if publication:
            remote_name, _, remote_branch = publication.partition("/")
            remote = remote_name if remote_branch == name else publication

        linked_worktree = ""
        if worktree_path and Path(worktree_path).resolve() != Path(repo_root).resolve():
            linked_worktree = Path(worktree_path).name

        branches.append(
            Branch(
                name=name,
                upstream=upstream or None,
                publication=publication,
                remote=remote,
                state_text=state_text,
                state_mark=state_mark,
                state_colour=state_colour,
                updated=updated,
                pull_request=pull_requests.get(name, PullRequest("-", dim)),
                is_current=name == current,
                worktree=linked_worktree,
                worktree_path=worktree_path if linked_worktree else "",
            )
        )

    def natural(values: list[str], heading: str, extra: int = 0) -> int:
        return max([len(heading), *(len(value) for value in values)]) + 2 + extra

    branch_heading = f"BRANCH ({len(branches)} local)"
    show_pr = pr_reason is None
    show_worktree = any(branch.worktree for branch in branches)
    pr_width = (
        max([len("PULL REQUEST"), *(len(branch.pull_request.text) for branch in branches)])
        if show_pr
        else 0
    )
    columns = {
        "name": natural([branch.name for branch in branches], branch_heading, 2),
        "remote": natural([branch.remote for branch in branches], "REMOTE"),
        "state": natural(
            [f"{branch.state_mark} {branch.state_text}" for branch in branches], "STATE"
        ),
        "updated": natural([branch.updated for branch in branches], "UPDATED"),
    }
    if show_worktree:
        columns["worktree"] = natural([branch.worktree or "-" for branch in branches], "WORKTREE")

    overflow = sum(columns.values()) + pr_width - terminal_width
    compact_dates = False
    if overflow > 0:
        compact_dates = True
        compact_width = natural([compact_age(branch.updated) for branch in branches], "UPDATED")
        overflow -= columns["updated"] - compact_width
        columns["updated"] = compact_width
    if overflow > 0:
        floor = len("WORKTREE") + 2
        shed = min(overflow, max(0, columns.get("worktree", floor) - floor))
        if show_worktree:
            columns["worktree"] -= shed
        overflow -= shed
    if overflow > 0:
        floor = len("REMOTE") + 2
        shed = min(overflow, max(0, columns["remote"] - floor))
        columns["remote"] -= shed
        overflow -= shed
    if overflow > 0:
        columns["name"] = max(18, columns["name"] - overflow)

    def pad(value: str, width: int) -> str:
        return value.ljust(width)

    def paint_branch(value: str, is_current: bool) -> str:
        slash = value.rfind("/")
        if slash == -1 or not use_colour:
            return bold(value) if is_current else value
        head = dim(value[: slash + 1])
        tail = bold(value[slash + 1 :]) if is_current else value[slash + 1 :]
        return head + tail

    total_width = sum(columns.values()) + pr_width
    repo_name = Path(repo_root).name
    unpushed = sum("ahead" in branch.state_text for branch in branches)
    unpublished = sum(branch.publication is None for branch in branches)
    remote_gone = sum(branch.state_text == "remote gone" for branch in branches)
    behind_count = sum("behind" in branch.state_text for branch in branches)

    print()
    if github_repo:
        owner_url = f"https://github.com/{github_repo.owner}"
        rendered_repo = (
            bold(hyperlink(github_repo.owner, owner_url, enabled=use_links))
            + dim(" / ")
            + bold(hyperlink(github_repo.name, github_repo.url, enabled=use_links))
        )
        if github_repo.visibility:
            rendered_repo += dim(f" [{github_repo.visibility}]")
        if github_repo.is_fork:
            fork_label = hyperlink("[fork]", github_repo.parent_url, enabled=use_links)
            rendered_repo += " " + dim(fork_label)
        if github_repo.is_archived:
            rendered_repo += " " + yellow("[archived]")
    else:
        rendered_repo = bold(repo_name)
    print(rendered_repo + dim(" :: ") + bold(current or "detached HEAD"))
    separator = glyph["separator"]
    worktree = (
        yellow(f"dirty: {f' {separator} '.join(worktree_parts)}") if dirty_lines else green("clean")
    )
    print(dim("worktree, ") + worktree)
    print(dim(glyph["rule"] * total_width))
    heading = (
        pad(branch_heading, columns["name"])
        + pad("REMOTE", columns["remote"])
        + pad("STATE", columns["state"])
    )
    if show_worktree:
        heading += pad("WORKTREE", columns["worktree"])
    if show_pr:
        heading += pad("UPDATED", columns["updated"]) + "PULL REQUEST"
    else:
        heading += "UPDATED"
    print(dim(heading))

    for branch in branches:
        marker = f"{glyph['current']} " if branch.is_current else "  "
        name = fit(branch.name, columns["name"] - 3, glyph["ellipsis"])
        name_padding = " " * max(0, columns["name"] - len(marker) - len(name))
        updated = compact_age(branch.updated) if compact_dates else branch.updated
        row_text = marker + paint_branch(name, branch.is_current) + name_padding
        row_text += dim(
            pad(
                fit(branch.remote, columns["remote"] - 2, glyph["ellipsis"]),
                columns["remote"],
            )
        )
        row_text += branch.state_colour(
            pad(f"{branch.state_mark} {branch.state_text}", columns["state"])
        )
        if show_worktree:
            worktree_name = branch.worktree or "-"
            row_text += dim(
                pad(
                    fit(worktree_name, columns["worktree"] - 2, glyph["ellipsis"]),
                    columns["worktree"],
                )
            )
        if show_pr:
            row_text += dim(pad(updated, columns["updated"]))
            pr = branch.pull_request
            if pr.number is None:
                rendered_pr = pr.text
            else:
                number_text = f"#{pr.number}"
                rendered_pr = (
                    hyperlink(number_text, pr.url, enabled=use_links) + pr.text[len(number_text) :]
                )
            row_text += pr.colour(rendered_pr)
        else:
            row_text += dim(updated)
        print(row_text)

    print(dim(glyph["rule"] * total_width))
    linked_worktrees = [branch for branch in branches if branch.worktree_path]
    if linked_worktrees:
        suffix = "" if len(linked_worktrees) == 1 else "s"
        print(bold(f"{len(linked_worktrees)} other linked worktree{suffix}:"))
        for branch in linked_worktrees:
            print(f"  {branch.name} {dim('->')} {dim(branch.worktree_path)}")

    if dirty_lines:
        suffix = "" if len(dirty_lines) == 1 else "s"
        print(yellow(f"{len(dirty_lines)} uncommitted path{suffix}:"))
        for line in dirty_lines[:8]:
            print("  " + dim(line))
        if len(dirty_lines) > 8:
            print(dim(f"  ...and {len(dirty_lines) - 8} more"))
    else:
        print(green(f"{glyph['synced']} working tree clean"))

    counts: list[str] = []
    if unpushed:
        counts.append(f"{unpushed} with unpushed commits")
    if behind_count:
        counts.append(f"{behind_count} behind")
    if unpublished:
        counts.append(f"{unpublished} local only")
    if remote_gone:
        counts.append(f"{remote_gone} remote gone")
    if counts:
        print(dim(f"  {separator}  ".join(counts)))

    if fetch_failed:
        print()
        print(yellow(f"{glyph['notice']} Fetch failed - branch states may be out of date."))
        print(yellow("  Check network access and remote configuration, or use --no-fetch."))

    if pr_reason is not None:
        notice_lines = PR_NOTICES[pr_reason]
        print()
        print(yellow(f"{glyph['notice']} {notice_lines[0]}"))
        for extra_line in notice_lines[1:]:
            print(yellow(extra_line))
    print()
    return 0


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"git-muster {__version__}")
        raise typer.Exit()


@app.command(cls=MusterCommand, help=HELP, epilog=EPILOG)
def main(
    no_fetch: Annotated[
        bool,
        typer.Option(
            "--no-fetch",
            help=(
                "Skip git fetch and report against remote-tracking refs already on disk. "
                "Useful offline and for a fully read-only run."
            ),
            rich_help_panel="Report options",
        ),
    ] = False,
    plain: Annotated[
        bool,
        typer.Option(
            "--plain",
            help=(
                "Disable color, hyperlinks, and Unicode interface symbols for stable logs and "
                "pipes. Repository-provided text is preserved."
            ),
            rich_help_panel="Report options",
        ),
    ] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the installed version and exit.",
        ),
    ] = False,
) -> None:
    """Show every local Git branch and what needs attention."""
    del version
    try:
        status = run_report(no_fetch=no_fetch, plain=plain)
    except RuntimeError as error:
        typer.echo(f"git muster: {error}", err=True)
        raise typer.Exit(2) from None
    if status:
        raise typer.Exit(status)


def entrypoint() -> None:
    """Run the Typer application."""
    app()
