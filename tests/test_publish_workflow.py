from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/publish-pypi.yml")


def test_publish_workflow_uses_release_and_manual_tag_triggers() -> None:
    text = WORKFLOW.read_text()

    assert "release:" in text
    assert "types: [published]" in text
    assert "workflow_dispatch:" in text
    assert "github.event.release.tag_name || inputs.tag" in text
    assert "ref: ${{ env.RELEASE_TAG }}" in text


def test_publish_workflow_validates_tag_and_distributions() -> None:
    text = WORKFLOW.read_text()

    assert 'test "$project_version" = "$version"' in text
    assert "git describe --tags --exact-match" in text
    assert 'wheel="dist/git_muster-$version-py3-none-any.whl"' in text
    assert 'sdist="dist/git_muster-$version.tar.gz"' in text
    assert "archive_count=$(find dist -maxdepth 1 -type f" in text
    assert 'uv tool run --from "./$wheel"' in text


def test_publish_workflow_uses_narrow_oidc_permissions_without_a_token() -> None:
    text = WORKFLOW.read_text()
    publish_job = text.split("\n  publish:\n", maxsplit=1)[1]

    assert "permissions: {}" in text
    assert "environment:\n      name: pypi" in publish_job
    assert "permissions:\n      id-token: write" in publish_job
    assert "gh-action-pypi-publish@dc37677b" in publish_job
    assert "PYPI_TOKEN" not in text
    assert "password:" not in text
