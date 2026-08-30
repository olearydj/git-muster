from __future__ import annotations

import hashlib
import importlib.util
import json
import urllib.error
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(".github/scripts/download_release_distributions.py")
VERSION = "9.9.9"
WHEEL = f"git_muster-{VERSION}-py3-none-any.whl"
SDIST = f"git_muster-{VERSION}.tar.gz"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("download_release_distributions", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pypi_response(
    archives: dict[str, bytes],
    *,
    digests: dict[str, str] | None = None,
    yanked: set[str] | None = None,
) -> tuple[bytes, dict[str, bytes]]:
    urls = []
    for filename, payload in archives.items():
        digest = (digests or {}).get(filename, hashlib.sha256(payload).hexdigest())
        urls.append(
            {
                "filename": filename,
                "url": f"https://files.pythonhosted.example/{filename}",
                "digests": {"sha256": digest},
                "yanked": filename in (yanked or set()),
            }
        )
    return json.dumps({"urls": urls}).encode(), {
        f"https://files.pythonhosted.example/{name}": payload for name, payload in archives.items()
    }


def reader(metadata: bytes, downloads: dict[str, bytes]):
    def read(url: str) -> bytes:
        if url.startswith("https://pypi.org/pypi/"):
            return metadata
        return downloads[url]

    return read


def test_published_archives_are_downloaded_and_verified(tmp_path: Path) -> None:
    script = load_script()
    archives = {WHEEL: b"wheel bytes", SDIST: b"sdist bytes"}
    metadata, downloads = pypi_response(archives)

    verified = script.download_release(VERSION, tmp_path, reader(metadata, downloads))

    assert (tmp_path / WHEEL).read_bytes() == b"wheel bytes"
    assert (tmp_path / SDIST).read_bytes() == b"sdist bytes"
    assert verified[0].startswith(WHEEL)
    assert hashlib.sha256(b"sdist bytes").hexdigest() in verified[1]


@pytest.mark.parametrize("corrupted", [WHEEL, SDIST])
def test_a_digest_mismatch_refuses_to_attach(tmp_path: Path, corrupted: str) -> None:
    script = load_script()
    archives = {WHEEL: b"wheel bytes", SDIST: b"sdist bytes"}
    metadata, downloads = pypi_response(archives, digests={corrupted: "0" * 64})
    destination = tmp_path / "dist"

    with pytest.raises(SystemExit, match="does not match PyPI"):
        script.download_release(VERSION, destination, reader(metadata, downloads))

    # Verification finishes before anything is written, so a later failure
    # cannot leave an earlier archive behind.
    assert not destination.exists()


def test_an_incomplete_release_refuses_to_attach(tmp_path: Path) -> None:
    script = load_script()
    metadata, downloads = pypi_response({WHEEL: b"wheel bytes"})
    destination = tmp_path / "dist"

    with pytest.raises(SystemExit, match="expected"):
        script.download_release(VERSION, destination, reader(metadata, downloads))

    assert not destination.exists()


def test_a_yanked_archive_refuses_to_attach(tmp_path: Path) -> None:
    script = load_script()
    archives = {WHEEL: b"wheel bytes", SDIST: b"sdist bytes"}
    metadata, downloads = pypi_response(archives, yanked={SDIST})
    destination = tmp_path / "dist"

    with pytest.raises(SystemExit, match="is yanked on PyPI"):
        script.download_release(VERSION, destination, reader(metadata, downloads))

    assert not destination.exists()


def test_the_command_line_requires_a_version_and_destination() -> None:
    script = load_script()

    with pytest.raises(SystemExit, match="usage:"):
        script.main(["download_release_distributions.py"])


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exception: object) -> bool:
        return False

    def read(self) -> bytes:
        return self.payload


def test_a_truncated_response_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    script = load_script()
    attempts: list[str] = []

    def urlopen(request: object, timeout: float | None = None) -> FakeResponse:
        attempts.append(getattr(request, "full_url", ""))
        if len(attempts) < 3:
            raise script.http.client.IncompleteRead(b"partial", 500)
        return FakeResponse(b"payload")

    monkeypatch.setattr(script.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(script.time, "sleep", lambda seconds: None)

    assert script.read_url("https://pypi.example/json") == b"payload"
    assert len(attempts) == 3


def test_persistent_failures_report_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    script = load_script()

    def urlopen(request: object, timeout: float | None = None) -> FakeResponse:
        raise urllib.error.URLError("connection reset")

    monkeypatch.setattr(script.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(script.time, "sleep", lambda seconds: None)

    with pytest.raises(SystemExit, match="after 3 attempts"):
        script.read_url("https://pypi.example/json")


def test_an_unpublished_version_is_reported_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = load_script()

    def urlopen(request: object, timeout: float | None = None) -> FakeResponse:
        raise urllib.error.HTTPError("https://pypi.example/json", 404, "Not Found", {}, None)

    monkeypatch.setattr(script.urllib.request, "urlopen", urlopen)

    with pytest.raises(SystemExit, match="is that version published"):
        script.read_url("https://pypi.example/json")
