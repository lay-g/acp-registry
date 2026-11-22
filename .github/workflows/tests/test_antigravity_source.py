"""Tests for the Antigravity CLI source and its version updater integration."""

import hashlib
import io
import json
import urllib.request
from email.message import Message
from pathlib import Path
from urllib.response import addinfourl

import pytest

from custom_agent_sources import antigravity
from update_versions import apply_update, check_agent_version

PLATFORMS = {
    "darwin-aarch64": "darwin_arm64",
    "darwin-x86_64": "darwin_amd64",
    "linux-aarch64": "linux_arm64",
    "linux-x86_64": "linux_amd64",
    "windows-aarch64": "windows_arm64",
    "windows-x86_64": "windows_amd64",
}
VERSION = "1.5.14"


@pytest.fixture
def feed(monkeypatch):
    requests = []
    manifests = {}
    archives = {}
    responses = {}
    redirects = {}
    for platform, slug in PLATFORMS.items():
        suffix = ".exe" if platform.startswith("windows-") else ".tar.gz"
        url = antigravity.ARCHIVE_PREFIX + VERSION + "/" + slug + suffix
        body = f"CLI for {platform}".encode()
        manifest = {"version": VERSION, "url": url, "sha512": hashlib.sha512(body).hexdigest()}
        manifests[platform] = manifest
        archives[platform] = url
        responses[f"{antigravity.MANIFEST_BASE}/{slug}.json"] = manifest
        responses[url] = body

    def fake_https_open(_handler, request):
        url = request.full_url
        requests.append(url)
        headers = Message()
        status = 200
        if url in redirects:
            headers["Location"] = redirects[url]
            status = 302
            body = b""
        else:
            body = responses[url]
            if isinstance(body, dict):
                body = json.dumps(body).encode()
        response = addinfourl(io.BytesIO(body), headers, url, status)
        response.msg = "OK" if status == 200 else "Found"
        return response

    monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", fake_https_open)
    return manifests, archives, responses, requests, redirects


def test_updater_preserves_launch_configuration(tmp_path, feed):
    _, archives, responses, requests, _ = feed
    path = tmp_path / "antigravity-acp" / "agent.json"
    path.parent.mkdir()
    current = json.loads((Path(__file__).parents[3] / "antigravity-acp/agent.json").read_text())
    current["version"] = "1.5.13"
    targets = current["distribution"]["binary"]
    for target in targets.values():
        target["archive"] = "https://example.com/previous"
        target["sha256"] = "0" * 64
    path.write_text(json.dumps(current))

    update, error = check_agent_version(path, current)

    assert error is None
    assert update.latest_version == VERSION
    assert apply_update(update)
    expected = current
    expected["version"] = VERSION
    for platform, target in targets.items():
        url = archives[platform]
        target["archive"] = url
        target["sha256"] = hashlib.sha256(responses[url]).hexdigest()
    assert json.loads(path.read_text()) == expected
    assert set(requests[:6]) == {
        f"{antigravity.MANIFEST_BASE}/{slug}.json" for slug in PLATFORMS.values()
    }
    assert set(requests[6:]) == set(archives.values())


@pytest.mark.parametrize("current", [VERSION, "1.5.100"])
def test_equal_or_older_releases_are_not_downloaded(feed, current):
    _, _, _, requests, _ = feed

    assert antigravity.get_stable_release({"version": current}) == (None, None)
    assert len(requests) == 6


def test_inconsistent_versions_are_rejected_before_download(feed):
    manifests, _, _, requests, _ = feed
    manifests["windows-aarch64"]["version"] = "1.5.15"

    release, error = antigravity.get_stable_release({"version": "1.5.13"})

    assert release is None
    assert "versions disagree" in error.error
    assert "windows-aarch64=1.5.15" in error.error
    assert len(requests) == 6


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("url", "https://storage.googleapis.com/antigravity-public/other/cli.tar.gz", "allowlist"),
        ("sha512", "bad", "128 hex characters"),
        ("version", None, "Unsupported version"),
    ],
)
def test_invalid_manifest_is_rejected(feed, field, value, message):
    manifests, _, _, requests, _ = feed
    manifests["linux-x86_64"][field] = value

    release, error = antigravity.get_stable_release({"version": "1.5.13"})

    assert release is None
    assert "linux-x86_64 manifest:" in error.error
    assert message in error.error
    assert all(url.startswith(antigravity.MANIFEST_BASE) for url in requests)


def test_checksum_mismatch_discards_release(feed):
    _, archives, responses, _, _ = feed
    responses[archives["windows-x86_64"]] = b"invalid binary"

    release, error = antigravity.get_stable_release({"version": "1.5.13"})

    assert release is None
    assert "windows-x86_64 archive: sha512 mismatch" in error.error


@pytest.mark.parametrize("kind", ["manifest", "archive"])
def test_redirects_are_rejected(feed, kind):
    _, archives, _, requests, redirects = feed
    url = (
        f"{antigravity.MANIFEST_BASE}/darwin_arm64.json"
        if kind == "manifest"
        else archives["darwin-aarch64"]
    )
    redirect = "https://example.test/redirected"
    redirects[url] = redirect

    release, error = antigravity.get_stable_release({"version": "1.5.13"})

    assert release is None
    assert f"darwin-aarch64 {kind}: HTTP Error 302" in error.error
    assert redirect not in requests
