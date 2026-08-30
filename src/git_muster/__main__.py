"""Run Git Muster as ``python -m git_muster``."""

from git_muster.cli import entrypoint

if __name__ == "__main__":  # pragma: no cover - exercised through a subprocess
    entrypoint()
