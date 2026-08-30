# Security Policy

## Supported versions

Git Muster is a single-maintainer project. Only the latest release on [PyPI](https://pypi.org/project/git-muster/) receives fixes; older versions are superseded rather than patched.

## Reporting a vulnerability

Report suspected vulnerabilities privately through GitHub's [private vulnerability reporting](https://github.com/olearydj/git-muster/security/advisories/new). Do not open a public issue for an unfixed vulnerability.

Please include the Git Muster version, your operating system and Git version, and the smallest reproduction you can share. Expect an initial response within seven days, and a fix or an explanation of why the report is out of scope before any public disclosure.

## Scope

Git Muster reads local repository state. It runs `git` and, when available, `gh` as subprocesses with argument lists rather than a shell, and its only default repository mutation is `git fetch --all --prune`. Findings that involve command injection through branch, remote, or worktree names, unexpected repository mutation, or leakage of credentials handled by `git` or `gh` are in scope.

Vulnerabilities in Git, the GitHub CLI, Typer, or Rich belong to those projects. Report them upstream; if Git Muster's use of them makes an upstream issue exploitable, that is in scope here.

## Release integrity

Releases are built from a tagged commit by [`publish-pypi.yml`](.github/workflows/publish-pypi.yml) and published to PyPI with Trusted Publishing, so no long-lived PyPI token exists. PyPI files carry [attestations](https://docs.pypi.org/attestations/) naming this repository, workflow, and environment as the publisher.

Starting with 0.4.0, the archives attached to a GitHub release are the files PyPI holds. A publishing run attaches the artifacts it just published; a recovery run, which publishes nothing, downloads the archives from PyPI and verifies their SHA-256 digests before attaching them. The 0.3.1 archives were attached by hand before that automation existed: its source distribution is byte-identical to the one on PyPI, while its wheel differs from the PyPI wheel in build metadata only, because the two were built with different uv versions. Treat PyPI, whose files carry attestations, as the authority for any release.
