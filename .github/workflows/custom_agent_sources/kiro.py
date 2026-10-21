"""Kiro's stable release channel.

Kiro CLI releases are published via an AWS CDN manifest at
https://prod.download.cli.kiro.dev/stable/latest/manifest.json.
This module extracts the version, downloads, and sha256 digests for
the Linux targets.
"""

import json
import urllib.error
import urllib.request

from common import LatestRelease, ResolvedAsset, UpdateError

MANIFEST_URL = "https://prod.download.cli.kiro.dev/stable/latest/manifest.json"
BASE_URL = "https://prod.download.cli.kiro.dev/stable"

_TARGET_MAP = {
    "x86_64-unknown-linux-gnu": "linux-x86_64",
    "aarch64-unknown-linux-gnu": "linux-aarch64",
}


def get_stable_release(agent_data: dict) -> tuple[LatestRelease | None, UpdateError | None]:
    """Fetch the latest Kiro CLI release from the official manifest."""
    agent_id = agent_data.get("id", "kiro")
    req = urllib.request.Request(
        MANIFEST_URL,
        headers={"User-Agent": "ACP-Registry-Version-Checker/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        return None, UpdateError(agent_id, f"Failed to fetch manifest {MANIFEST_URL}: {e}")

    version = data.get("version")
    if not version:
        return None, UpdateError(agent_id, f"Manifest missing 'version' field: {MANIFEST_URL}")

    resolved_assets: dict[str, ResolvedAsset] = {}
    for pkg in data.get("packages", []):
        triple = pkg.get("targetTriple")
        if triple in _TARGET_MAP and pkg.get("fileType") == "tarGz":
            platform = _TARGET_MAP[triple]
            download = pkg.get("download")
            sha256 = pkg.get("sha256")
            if download and sha256:
                archive_url = f"{BASE_URL}/{download}"
                resolved_assets[platform] = ResolvedAsset(archive_url=archive_url, sha256=sha256)

    return LatestRelease(
        version=version,
        distribution_type="binary",
        source_url=MANIFEST_URL,
        repository="https://github.com/kirodotdev/Kiro",
        resolved_assets=resolved_assets,
    ), None
