"""Tests for fork_tools.py. Run: uv run --with pytest pytest .github/fork -q"""

import fork_tools
from fork_tools import resolve_agent_conflict


def agent(version, preview=None, args=None):
    data = {
        "id": "demo",
        "version": version,
        "distribution": {"npx": {"package": f"demo@{version}", "args": args or ["--acp"]}},
    }
    if preview:
        data["preview"] = {"version": preview}
    return data


def test_upstream_newer_wins():
    base, ours, theirs = agent("1.0.0"), agent("1.1.0"), agent("1.2.0")
    assert resolve_agent_conflict(base, ours, theirs) is theirs


def test_fork_newer_wins_when_upstream_changed_only_versions():
    base, ours, theirs = agent("1.0.0"), agent("1.3.0"), agent("1.2.0")
    assert resolve_agent_conflict(base, ours, theirs) is ours


def test_fork_newer_but_upstream_structural_change_needs_human():
    base, ours, theirs = agent("1.0.0"), agent("1.3.0"), agent("1.2.0", args=["acp"])
    assert resolve_agent_conflict(base, ours, theirs) is None


def test_mixed_channels_need_human():
    base = agent("1.0.0", "1.1.0-preview.1")
    ours = agent("1.2.0", "1.1.0-preview.1")
    theirs = agent("1.1.0", "1.3.0-preview.1")
    assert resolve_agent_conflict(base, ours, theirs) is None


def test_fork_quarantine_filters_unquarantined(tmp_path):
    (tmp_path / "quarantine.json").write_text('{"a": "x", "b": "y"}')
    load = fork_tools.fork_quarantine({"unquarantine": {"a"}})
    assert load(tmp_path) == {"b": "y"}
