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

import typer
from rich.console import Console
from rich.padding import Padding
from rich.table import Table
from typer.core import TyperCommand

from git_muster import __version__

HELP = (
    "Inspect every local branch in the current Git repository. Git Muster separates "
    "uncommitted work from committed branch state, then shows which branches are "
    "unpublished, ahead, behind, or diverged from their configured upstream. When the "
    "GitHub CLI is authenticated, pull-request state appears in the same report."
)

EPILOG = """
[bold]Examples[/bold]

  [cyan]git muster[/cyan]
  Refresh remote-tracking refs, then report every local branch.

  [cyan]git muster --no-fetch[/cyan]
  Use the remote-tracking data already on disk.

  [cyan]git muster --plain[/cyan]
  Emit stable ASCII output without color for logs and pipes.

[bold]Effects[/bold]

The default run executes [cyan]git fetch --all --prune[/cyan]. It never switches, deletes,
merges, rebases, or pushes branches. Use [cyan]--no-fetch[/cyan] for a fully read-only run.
"""


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
    table.add_row("[green]in sync[/green]", "Local and configured upstream tips agree.")
    table.add_row("[yellow]ahead N[/yellow]", "N local commits have not been pushed.")
    table.add_row("[blue]behind N[/blue]", "N upstream commits are missing locally.")
    table.add_row("[red]ahead N, behind M[/red]", "The histories have diverged.")
    table.add_row("[dim]local only[/dim]", "The branch has no configured upstream.")
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


def command_output(command: str, *args: str) -> str | None:
    """Run a command quietly, returning ``None`` when it is unavailable or fails."""
    try:
        result = subprocess.run(
            [command, *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.rstrip("\r\n")


def git_output(*args: str) -> str:
    """Run a required Git command or raise a concise operational error."""
    output = command_output("git", *args)
    if output is None:
        raise RuntimeError(f"git {' '.join(args)} failed")
    return output


def compact_age(relative: str) -> str:
    """Shorten a Git relative date when terminal space is constrained."""
    match = re.match(r"^(\d+)\s+(\w)", relative)
    if match:
        return "".join(match.groups())
    return relative.removesuffix(" ago")


def fit(value: str, limit: int, ellipsis: str) -> str:
    """Middle-truncate text while retaining its recognizable ending."""
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    keep_end = max(4, int((limit - 1) * 0.6))
    keep_start = limit - 1 - keep_end
    return value[:keep_start] + ellipsis + value[-keep_end:]


@dataclass(frozen=True)
class PullRequest:
    """Pull-request presentation data for one branch."""

    text: str
    colour: Callable[[str], str]


@dataclass(frozen=True)
class Branch:
    """Collected status for one local branch."""

    name: str
    tracking: str
    state_text: str
    state_mark: str
    state_colour: Callable[[str], str]
    updated: str
    pull_request: PullRequest
    is_current: bool


def run_report(*, no_fetch: bool = False, plain: bool = False) -> int:
    """Run the report and return a process exit status."""
    repo_root = command_output("git", "rev-parse", "--show-toplevel")
    if repo_root is None:
        print("git muster: current directory is not inside a Git repository", file=sys.stderr)
        return 2

    use_colour = not plain and sys.stdout.isatty() and not bool(os.environ.get("NO_COLOR"))
    modern_terminal = sys.platform != "win32" or bool(
        os.environ.get("WT_SESSION")
        or os.environ.get("TERM_PROGRAM")
        or os.environ.get("TERMINAL_EMULATOR")
    )
    use_symbols = not plain and modern_terminal

    def paint(code: str) -> Callable[[str], str]:
        return lambda text: f"\033[{code}m{text}\033[0m" if use_colour else text

    bold = paint("1")
    dim = paint("2")
    red = paint("31")
    green = paint("32")
    yellow = paint("33")
    blue = paint("34")

    if use_symbols:
        glyph = {
            "current": "▸",
            "synced": "✓",
            "ahead": "↑",
            "behind": "↓",
            "diverged": "⇅",
            "local": "·",
            "rule": "─",
            "ellipsis": "…",
            "notice": "▲",
        }
    else:
        glyph = {
            "current": ">",
            "synced": "=",
            "ahead": "^",
            "behind": "v",
            "diverged": "x",
            "local": ".",
            "rule": "-",
            "ellipsis": "..",
            "notice": "!",
        }

    terminal_width = max(60, min(shutil.get_terminal_size((100, 24)).columns, 160))

    if not no_fetch:
        if sys.stdout.isatty():
            print(dim("fetching..."), end="", flush=True)
        command_output("git", "fetch", "--all", "--prune", "--quiet")
        if sys.stdout.isatty():
            print("\r           \r", end="", flush=True)

    default_branch = command_output("git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    default_branch = default_branch.removeprefix("origin/") if default_branch else "main"

    pull_requests: dict[str, PullRequest] = {}
    pr_json = command_output(
        "gh",
        "pr",
        "list",
        "--state",
        "all",
        "--limit",
        "100",
        "--json",
        "headRefName,number,state,isDraft,reviewDecision",
    )
    if pr_json is not None:
        try:
            pr_rows = json.loads(pr_json)
        except (json.JSONDecodeError, TypeError):
            pr_json = None
        else:
            for pr in pr_rows:
                name = pr.get("headRefName")
                if not name or name == default_branch or name in pull_requests:
                    continue
                state = "draft" if pr.get("isDraft") else str(pr.get("state", "")).lower()
                approved = pr.get("reviewDecision") == "APPROVED"
                colour = (
                    green if approved or state == "open" else yellow if state == "draft" else dim
                )
                suffix = " approved" if approved else ""
                pull_requests[name] = PullRequest(f"#{pr.get('number')} {state}{suffix}", colour)

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

    raw_branches = git_output(
        "for-each-ref",
        "--sort=-committerdate",
        "refs/heads",
        "--format=%(refname:short)\t%(upstream:short)\t%(upstream:track)\t%(committerdate:relative)",
    )
    branches: list[Branch] = []
    for line in raw_branches.splitlines():
        name, upstream, track, updated = line.split("\t", 3)
        detail = track.strip("[]")
        ahead = "ahead" in detail
        behind = "behind" in detail
        if not upstream:
            state_text, state_colour, state_mark = "local only", dim, glyph["local"]
        elif ahead and behind:
            state_text, state_colour, state_mark = detail, red, glyph["diverged"]
        elif ahead:
            state_text, state_colour, state_mark = detail, yellow, glyph["ahead"]
        elif behind:
            state_text, state_colour, state_mark = detail, blue, glyph["behind"]
        else:
            state_text, state_colour, state_mark = "in sync", green, glyph["synced"]

        tracking = "-"
        if upstream:
            remote, _, remote_branch = upstream.partition("/")
            tracking = remote if remote_branch == name else upstream

        branches.append(
            Branch(
                name=name,
                tracking=tracking,
                state_text=state_text,
                state_mark=state_mark,
                state_colour=state_colour,
                updated=updated,
                pull_request=pull_requests.get(name, PullRequest("-", dim)),
                is_current=name == current,
            )
        )

    def natural(values: list[str], heading: str, extra: int = 0) -> int:
        return max([len(heading), *(len(value) for value in values)]) + 2 + extra

    branch_heading = f"BRANCH ({len(branches)} local)"
    show_pr = pr_json is not None
    pr_width = (
        max([len("PULL REQUEST"), *(len(branch.pull_request.text) for branch in branches)])
        if show_pr
        else 0
    )
    columns = {
        "name": natural([branch.name for branch in branches], branch_heading, 2),
        "tracking": natural([branch.tracking for branch in branches], "TRACKING"),
        "state": natural(
            [f"{branch.state_mark} {branch.state_text}" for branch in branches], "STATE"
        ),
        "updated": natural([branch.updated for branch in branches], "UPDATED"),
    }

    overflow = sum(columns.values()) + pr_width - terminal_width
    compact_dates = False
    if overflow > 0:
        compact_dates = True
        compact_width = natural([compact_age(branch.updated) for branch in branches], "UPDATED")
        overflow -= columns["updated"] - compact_width
        columns["updated"] = compact_width
    if overflow > 0:
        floor = len("TRACKING") + 2
        shed = min(overflow, max(0, columns["tracking"] - floor))
        columns["tracking"] -= shed
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
    unpublished = sum(branch.tracking == "-" for branch in branches)
    behind_count = sum("behind" in branch.state_text for branch in branches)

    print()
    print(bold(repo_name) + dim(" :: ") + bold(current or "detached HEAD"))
    joiner = " · " if use_symbols else " | "
    worktree = yellow(f"dirty: {joiner.join(worktree_parts)}") if dirty_lines else green("clean")
    print(dim("worktree, ") + worktree)
    print(dim(glyph["rule"] * total_width))
    heading = (
        pad(branch_heading, columns["name"])
        + pad("TRACKING", columns["tracking"])
        + pad("STATE", columns["state"])
    )
    heading += pad("UPDATED", columns["updated"]) + "PULL REQUEST" if show_pr else "UPDATED"
    print(dim(heading))

    for branch in branches:
        marker = f"{glyph['current']} " if branch.is_current else "  "
        name = fit(branch.name, columns["name"] - 3, glyph["ellipsis"])
        name_padding = " " * max(0, columns["name"] - len(marker) - len(name))
        updated = compact_age(branch.updated) if compact_dates else branch.updated
        row = marker + paint_branch(name, branch.is_current) + name_padding
        row += dim(
            pad(
                fit(branch.tracking, columns["tracking"] - 2, glyph["ellipsis"]),
                columns["tracking"],
            )
        )
        row += branch.state_colour(
            pad(f"{branch.state_mark} {branch.state_text}", columns["state"])
        )
        if show_pr:
            row += dim(pad(updated, columns["updated"]))
            row += branch.pull_request.colour(branch.pull_request.text)
        else:
            row += dim(updated)
        print(row)

    print(dim(glyph["rule"] * total_width))
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
        counts.append(f"{unpublished} never published")
    if counts:
        print(dim("  ·  ".join(counts)))

    if not show_pr:
        print()
        notice = (
            f"{glyph['notice']} Pull request state unknown - "
            "the GitHub CLI is missing or not logged in."
        )
        print(yellow(notice))
        print(yellow("  Install it from https://cli.github.com, then run: gh auth login"))
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
            help="Disable color and Unicode symbols for stable logs and pipes.",
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
