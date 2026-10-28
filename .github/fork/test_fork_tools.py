"""Tests for fork_tools.py. Run: uv run --with pytest pytest .github/fork -q"""

import fork_tools
from fork_tools import (
    merge_conflict_hunks,
    merge_import_hunk,
    merge_registry_urls_hunk,
    merge_source_entries_hunk,
    resolve_agent_conflict,
)


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


def test_import_hunk_unions_both_sides():
    ours = "from custom_agent_sources import CustomSourceFn, antigravity, junie, kiro\n"
    theirs = "from custom_agent_sources import CustomSourceFn, antigravity, junie, opencode_v2\n"
    merged = merge_import_hunk(ours, theirs)
    assert merged == (
        "from custom_agent_sources import CustomSourceFn, antigravity, junie, kiro, opencode_v2"
    )


def test_source_entries_hunk_unions_both_sides():
    ours = '    ("kiro", "stable"): kiro.get_stable_release,\n'
    theirs = '    ("opencode-v2", "stable"): opencode_v2.get_stable_release,\n'
    merged = merge_source_entries_hunk(ours, theirs)
    assert merged == (
        '    ("kiro", "stable"): kiro.get_stable_release,\n'
        '    ("opencode-v2", "stable"): opencode_v2.get_stable_release,'
    )


def test_source_entries_hunk_same_key_different_source_needs_human():
    ours = '    ("junie", "preview"): junie.get_preview_release,\n'
    theirs = '    ("junie", "preview"): junie.get_other_release,\n'
    assert merge_source_entries_hunk(ours, theirs) is None


def test_registry_urls_hunk_keeps_fork_base():
    ours = (
        "https://lay-g.github.io/acp-registry/registry-for-jetbrains.json\n"
        "https://lay-g.github.io/acp-registry/registry-for-jetbrains-preview.json\n"
    )
    theirs = (
        "https://cdn.agentclientprotocol.com/registry/v1/latest/registry-for-jetbrains.json\n"
        "https://cdn.agentclientprotocol.com/registry/v1/latest/"
        "registry-for-jetbrains-preview.json\n"
        "https://cdn.agentclientprotocol.com/registry/v1/latest/registry-for-jetbrains-air.json\n"
    )
    merged = merge_registry_urls_hunk(ours, theirs)
    assert merged == (
        "https://lay-g.github.io/acp-registry/registry-for-jetbrains.json\n"
        "https://lay-g.github.io/acp-registry/registry-for-jetbrains-preview.json\n"
        "https://lay-g.github.io/acp-registry/registry-for-jetbrains-air.json"
    )


def test_registry_urls_hunk_keeps_badges_around_fork_link():
    ours = "https://github.com/lay-g/acp-registry\n"
    theirs = (
        "[![Check License URLs](https://example.com/badge.svg)](https://example.com)\n"
        "\n"
        "https://agentclientprotocol.com/registry\n"
    )
    merged = merge_registry_urls_hunk(ours, theirs)
    assert merged == (
        "[![Check License URLs](https://example.com/badge.svg)](https://example.com)\n"
        "\n"
        "https://github.com/lay-g/acp-registry"
    )


def test_merge_conflict_hunks_resolves_both_hunks():
    text = (
        "head\n"
        "<<<<<<< HEAD\n"
        "from custom_agent_sources import CustomSourceFn, junie, kiro\n"
        "=======\n"
        "from custom_agent_sources import CustomSourceFn, junie, opencode_v2\n"
        ">>>>>>> upstream/main\n"
        "tail\n"
    )
    merged = merge_conflict_hunks(
        text, (merge_import_hunk, merge_source_entries_hunk)
    )
    assert merged == (
        "head\n"
        "from custom_agent_sources import CustomSourceFn, junie, kiro, opencode_v2\n"
        "tail\n"
    )


def test_merge_conflict_hunks_keeps_unresolvable_hunk():
    text = (
        "<<<<<<< HEAD\n"
        "ours only\n"
        "=======\n"
        "theirs only\n"
        ">>>>>>> upstream/main\n"
    )
    assert merge_conflict_hunks(text, (merge_import_hunk,)) is None
