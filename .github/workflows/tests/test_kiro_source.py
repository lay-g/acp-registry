"""Tests for custom_agent_sources/kiro.py."""

import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from custom_agent_sources import kiro
from update_versions import check_agent_version

MOCK_MANIFEST = {
    "version": "2.33.0",
    "packages": [
        {
            "targetTriple": "x86_64-unknown-linux-gnu",
            "fileType": "tarGz",
            "download": "2.33.0/kirocli-x86_64-linux.tar.gz",
            "sha256": "fdce2898458e23346e63c7a87959cf458290bc44c080951b099c03862056933b",
        },
        {
            "targetTriple": "aarch64-unknown-linux-gnu",
            "fileType": "tarGz",
            "download": "2.33.0/kirocli-aarch64-linux.tar.gz",
            "sha256": "0c2c765027ca8414fbce96ec484e7e92c80a341fadd854ab417007e9271634e2",
        },
    ],
}


def test_get_stable_release_success():
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(MOCK_MANIFEST).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        release, err = kiro.get_stable_release({"id": "kiro", "version": "2.32.0"})

    assert err is None
    assert release is not None
    assert release.version == "2.33.0"
    assert release.distribution_type == "binary"
    assert "linux-x86_64" in release.resolved_assets
    assert "linux-aarch64" in release.resolved_assets
    assert (
        release.resolved_assets["linux-x86_64"].archive_url
        == "https://prod.download.cli.kiro.dev/stable/2.33.0/kirocli-x86_64-linux.tar.gz"
    )
    assert (
        release.resolved_assets["linux-x86_64"].sha256
        == "fdce2898458e23346e63c7a87959cf458290bc44c080951b099c03862056933b"
    )


def test_get_stable_release_network_error():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        release, err = kiro.get_stable_release({"id": "kiro", "version": "2.32.0"})

    assert release is None
    assert err is not None
    assert "Failed to fetch manifest" in err.error


def test_check_agent_version_integration():
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(MOCK_MANIFEST).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    agent_data = {
        "id": "kiro",
        "version": "2.32.0",
        "distribution": {
            "binary": {
                "linux-x86_64": {"archive": "...", "cmd": "./kiro-cli"},
                "linux-aarch64": {"archive": "...", "cmd": "./kiro-cli"},
            }
        },
    }

    with patch("urllib.request.urlopen", return_value=mock_resp):
        update, err = check_agent_version(Path("kiro"), agent_data)

    assert err is None
    assert update is not None
    assert update.current_version == "2.32.0"
    assert update.latest_version == "2.33.0"
