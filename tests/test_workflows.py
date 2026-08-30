from __future__ import annotations

import re
from pathlib import Path

import pytest

CI = Path(".github/workflows/ci.yml")
PUBLISH = Path(".github/workflows/publish-pypi.yml")
DEPENDABOT = Path(".github/dependabot.yml")

PINNED_ACTION = re.compile(
    r"^\s+uses: [\w.\-]+/[\w.\-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+$",
)

VERIFICATION_COMMANDS = (
    "uv sync --locked --all-groups",
    "uv run --locked pytest",
    "uv run --locked ruff format --check .",
    "uv run --locked ruff check .",
    "uv run --locked ty check",
    "uv build",
)


@pytest.mark.parametrize("workflow", [CI, PUBLISH])
def test_every_action_is_pinned_to_a_commit_with_a_version_comment(workflow: Path) -> None:
    used = [line for line in workflow.read_text().splitlines() if "uses:" in line]

    assert used, f"{workflow} should use at least one action"
    for line in used:
        assert PINNED_ACTION.match(line.rstrip()), f"{workflow}: unpinned action -> {line.strip()}"


@pytest.mark.parametrize("workflow", [CI, PUBLISH])
def test_every_job_is_bounded_by_a_timeout(workflow: Path) -> None:
    text = workflow.read_text()

    assert text.count("timeout-minutes:") == text.count("runs-on:")
    assert "concurrency:" in text


def test_ci_runs_the_documented_verification_on_both_supported_pythons() -> None:
    text = CI.read_text()

    assert 'python-version: ["3.13", "3.14"]' in text
    assert "fail-fast: false" in text
    for command in VERIFICATION_COMMANDS:
        assert command in text, command
    assert "git diff --exit-code -- uv.lock" in text
    assert "permissions:\n  contents: read" in text
    assert "pull_request_target" not in text


def test_ci_whitespace_check_survives_a_force_push() -> None:
    text = CI.read_text()

    assert 'git cat-file -e "$base^{commit}"' in text
    assert 'base="$(git hash-object -t tree /dev/null)"' in text
    assert "PUSH_BEFORE: ${{ github.event.before }}" in text


def workflow_steps(job: str) -> dict[str, str]:
    """Map each step name in a job block to the lines that configure it."""
    steps: dict[str, str] = {}
    current: str | None = None
    for line in job.splitlines():
        stripped = line.strip()
        if stripped.startswith("- name: "):
            current = stripped.removeprefix("- name: ")
            steps[current] = ""
        elif current is not None:
            steps[current] += f"{line}\n"
    return steps


def test_recovery_runs_validate_the_tag_but_skip_the_build() -> None:
    text = PUBLISH.read_text()
    verify_job = text.split("\n  verify-distributions:\n", maxsplit=1)[1].split(
        "\n  publish:\n", maxsplit=1
    )[0]
    steps = workflow_steps(verify_job)
    gate = "if: ${{ !inputs.assets_only }}"

    # A published release's files stay recoverable even if its tag no longer builds.
    for step in (
        "Install uv",
        "Install locked dependencies",
        "Verify source",
        "Build distributions",
        "Verify distribution contract",
        "Store verified distributions",
    ):
        assert gate in steps[step], f"{step} should be skipped for an assets_only run"
    for step in (
        "Check out release tag",
        "Validate release identity",
        "Confirm a published release owns the tag",
    ):
        assert gate not in steps[step], f"{step} must run in both modes"


def test_publish_workflow_uses_release_and_manual_tag_triggers() -> None:
    text = PUBLISH.read_text()

    assert "release:" in text
    assert "types: [published]" in text
    assert "workflow_dispatch:" in text
    assert "github.event.release.tag_name || inputs.tag" in text
    assert "ref: ${{ env.RELEASE_TAG }}" in text


def test_publish_workflow_validates_tag_and_distributions() -> None:
    text = PUBLISH.read_text()

    assert 'test "$project_version" = "$version"' in text
    assert "git describe --tags --exact-match" in text
    assert 'wheel="dist/git_muster-$version-py3-none-any.whl"' in text
    assert 'sdist="dist/git_muster-$version.tar.gz"' in text
    assert "archive_count=$(find dist -maxdepth 1 -type f" in text
    assert 'uv tool run --from "./$wheel"' in text


def test_publish_workflow_requires_a_published_release_for_the_tag() -> None:
    text = PUBLISH.read_text()

    assert 'gh release view "$RELEASE_TAG" --json tagName,isDraft' in text
    assert "select(.isDraft == false) | .tagName" in text
    assert 'test "$published_tag" = "$RELEASE_TAG"' in text


def test_publish_workflow_uses_narrow_oidc_permissions_without_a_token() -> None:
    text = PUBLISH.read_text()
    publish_job = text.split("\n  publish:\n", maxsplit=1)[1]

    assert "permissions: {}" in text
    assert "environment:\n      name: pypi" in publish_job
    assert "permissions:\n      id-token: write" in publish_job
    assert "gh-action-pypi-publish@dc37677b" in publish_job
    assert text.count("id-token: write") == 1
    assert "PYPI_TOKEN" not in text
    assert "password:" not in text


def test_assets_can_be_reattached_without_republishing_to_pypi() -> None:
    text = PUBLISH.read_text()
    publish_job = text.split("\n  publish:\n", maxsplit=1)[1].split("\n  attach", maxsplit=1)[0]
    attach_job = text.split("\n  attach-release-assets:\n", maxsplit=1)[1]

    assert "assets_only:" in text
    assert "type: boolean" in text
    assert "if: ${{ !inputs.assets_only }}" in publish_job
    assert "always()" in attach_job
    assert "if: ${{ !inputs.assets_only }}" in attach_job
    assert "if: ${{ inputs.assets_only }}" in attach_job
    assert "needs.verify-distributions.result == 'success'" in attach_job
    assert "needs.publish.result != 'failure'" in attach_job
    assert "needs.publish.result != 'cancelled'" in attach_job
    assert "skip-existing" not in text


def test_recovery_runs_attach_the_files_pypi_already_serves() -> None:
    text = PUBLISH.read_text()
    attach_job = text.split("\n  attach-release-assets:\n", maxsplit=1)[1]
    script = Path(".github/scripts/download_release_distributions.py")

    assert script.exists()
    assert 'python3 .github/scripts/download_release_distributions.py "${RELEASE_TAG#v}" dist' in (
        attach_job
    )
    assert "sha256" in script.read_text()
    # Recovering a tag published before this script existed must still work, so
    # the checkout takes the dispatched ref rather than the release tag.
    assert "ref: ${{ env.RELEASE_TAG }}" not in attach_job


def test_release_assets_come_from_the_verified_build() -> None:
    text = PUBLISH.read_text()
    attach_job = text.split("\n  attach-release-assets:\n", maxsplit=1)[1]

    assert "needs: [verify-distributions, publish]" in attach_job
    assert "permissions:\n      contents: write" in attach_job
    assert "name: pypi-distributions" in attach_job
    assert 'gh release upload "$RELEASE_TAG" dist/git_muster-* --clobber' in attach_job
    assert "id-token" not in attach_job


def test_dependabot_watches_actions_and_dependencies() -> None:
    text = DEPENDABOT.read_text()

    assert "package-ecosystem: github-actions" in text
    assert "package-ecosystem: uv" in text


def test_dependabot_leaves_declared_python_bounds_alone() -> None:
    text = DEPENDABOT.read_text()
    uv_block = text.split("package-ecosystem: uv", maxsplit=1)[1]
    actions_block = text.split("package-ecosystem: github-actions", maxsplit=1)[1].split(
        "package-ecosystem: uv", maxsplit=1
    )[0]

    # Raising a major means rewriting pyproject.toml's bounds, which stays a
    # human decision; action pins carry no such policy, so they keep flowing.
    assert 'update-types: ["version-update:semver-major"]' in uv_block
    assert "ignore:" not in actions_block
