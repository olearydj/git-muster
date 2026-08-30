"""Download a released version's distributions from PyPI and verify their digests.

The publishing workflow uses this when reattaching assets to a GitHub release
whose version PyPI already holds. Rebuilding from the tag is not enough: two
compatible uv versions can produce wheels that differ in build metadata, which
is exactly the divergence a recovery run has to repair. PyPI is the authority,
so the files it serves are the ones that get attached.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable

PROJECT = "git-muster"
RELEASE_API = "https://pypi.org/pypi/{project}/{version}/json"
TIMEOUT_SECONDS = 60
ATTEMPTS = 3

Reader = Callable[[str], bytes]


def read_url(url: str, attempts: int = ATTEMPTS) -> bytes:
    """Fetch a URL, retrying so one flaky or truncated response cannot fail a recovery."""
    failure = ""
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, headers={"Accept": "application/json, */*"})
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return bytes(response.read())
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise SystemExit(
                    f"could not fetch {url}: HTTP 404; is that version published?"
                ) from None
            failure = f"HTTP {error.code} {error.reason}"
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError) as error:
            failure = str(error) or type(error).__name__
        if attempt < attempts:
            time.sleep(2 * attempt)
    raise SystemExit(f"could not fetch {url} after {attempts} attempts: {failure}")


def expected_filenames(version: str) -> set[str]:
    """Return the archive names a complete release must contain."""
    return {f"git_muster-{version}-py3-none-any.whl", f"git_muster-{version}.tar.gz"}


def download_release(
    version: str,
    destination: pathlib.Path,
    read: Reader = read_url,
) -> list[str]:
    """Write PyPI's archives for ``version`` into ``destination``, verifying each digest."""
    payload = json.loads(read(RELEASE_API.format(project=PROJECT, version=version)))
    files = payload["urls"]
    published = {str(entry["filename"]) for entry in files}
    wanted = expected_filenames(version)
    if published != wanted:
        raise SystemExit(f"PyPI holds {sorted(published)} for {version}, expected {sorted(wanted)}")

    # Every archive is verified before any of them is written, so a release that
    # fails partway through leaves nothing behind to be attached by mistake.
    verified: list[tuple[str, bytes, str]] = []
    for entry in sorted(files, key=lambda item: str(item["filename"])):
        filename = str(entry["filename"])
        if entry.get("yanked"):
            raise SystemExit(f"{filename} is yanked on PyPI")
        archive = read(str(entry["url"]))
        digest = hashlib.sha256(archive).hexdigest()
        expected = str(entry["digests"]["sha256"])
        if digest != expected:
            raise SystemExit(f"{filename}: sha256 {digest} does not match PyPI's {expected}")
        verified.append((filename, archive, digest))

    destination.mkdir(parents=True, exist_ok=True)
    for filename, archive, _ in verified:
        (destination / filename).write_bytes(archive)
    return [f"{filename} sha256={digest}" for filename, _, digest in verified]


def main(argv: list[str]) -> int:
    """Download and verify one release, reporting each archive on standard output."""
    if len(argv) != 3:
        raise SystemExit("usage: download_release_distributions.py VERSION DESTINATION")
    for line in download_release(argv[1], pathlib.Path(argv[2])):
        print(f"verified {line}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through a subprocess
    raise SystemExit(main(sys.argv))
