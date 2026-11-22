"""Google Antigravity CLI's stable channel."""

import hashlib
import json
import re
import tempfile
import urllib.error
import urllib.request
from http.client import HTTPException
from typing import NamedTuple

from common import LatestRelease, ResolvedAsset, UpdateError
from registry_utils import version_tuple

AGENT_ID = "antigravity-acp"
MANIFEST_BASE = "https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests"
ARCHIVE_PREFIX = "https://storage.googleapis.com/antigravity-public/antigravity-cli/"
PLATFORMS = {
    "darwin-aarch64": "darwin_arm64",
    "darwin-x86_64": "darwin_amd64",
    "linux-x86_64": "linux_amd64",
    "linux-aarch64": "linux_arm64",
    "windows-x86_64": "windows_amd64",
    "windows-aarch64": "windows_arm64",
}
_SHA512 = re.compile(r"[0-9a-fA-F]{128}")


class _FeedError(Exception):
    pass


class _Manifest(NamedTuple):
    version: str
    url: str
    sha512: str


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _open(url: str):
    return _OPENER.open(url, timeout=30)


def _get_manifest(platform: str) -> _Manifest:
    url = f"{MANIFEST_BASE}/{PLATFORMS[platform]}.json"
    try:
        with _open(url) as response:
            data = json.load(response)
        version, archive, sha512 = data["version"], data["url"], data["sha512"]
        version_tuple(version)
        if not isinstance(archive, str) or not archive.startswith(ARCHIVE_PREFIX):
            raise _FeedError("archive outside allowlist")
        if not isinstance(sha512, str) or not _SHA512.fullmatch(sha512):
            raise _FeedError("sha512 must contain 128 hex characters")
    except (KeyError, ValueError, TypeError, OSError, HTTPException, _FeedError) as e:
        raise _FeedError(f"{platform} manifest: {e}") from e
    return _Manifest(version, archive, sha512.lower())


def _resolve_archive(platform: str, manifest: _Manifest) -> ResolvedAsset:
    try:
        with _open(manifest.url) as response, tempfile.TemporaryFile() as archive:
            sha512 = hashlib.sha512()
            while chunk := response.read(1024 * 1024):
                sha512.update(chunk)
                archive.write(chunk)
            if sha512.hexdigest() != manifest.sha512:
                raise _FeedError("sha512 mismatch")
            archive.seek(0)
            sha256 = hashlib.file_digest(archive, "sha256").hexdigest()
    except (OSError, HTTPException, _FeedError) as e:
        raise _FeedError(f"{platform} archive: {e}") from e
    return ResolvedAsset(archive_url=manifest.url, sha256=sha256)


def get_stable_release(agent_data: dict) -> tuple[LatestRelease | None, UpdateError | None]:
    try:
        manifests = {platform: _get_manifest(platform) for platform in PLATFORMS}
        version = next(iter(manifests.values())).version
        if any(manifest.version != version for manifest in manifests.values()):
            versions = ", ".join(f"{platform}={m.version}" for platform, m in manifests.items())
            raise _FeedError(f"CLI manifest versions disagree: {versions}")
        if version_tuple(version) <= version_tuple(agent_data["version"]):
            return None, None
        assets = {
            platform: _resolve_archive(platform, manifest)
            for platform, manifest in manifests.items()
        }
    except (_FeedError, KeyError, TypeError, ValueError) as e:
        return None, UpdateError(AGENT_ID, f"feed: {e}")

    return LatestRelease(
        version=version,
        distribution_type="binary",
        source_url=MANIFEST_BASE,
        repository="",
        resolved_assets=assets,
    ), None
