#!/usr/bin/env python3
"""Fork-only maintenance on top of the upstream scripts, without editing upstream files.

Subcommands:
    update [update_versions.py args]   Run upstream update_versions with fork config applied
    verify [verify_agents.py args]     Run upstream verify_agents with fork config applied
    set ID=VERSION[@preview] ...       Force agents to a version (manual override)
    verify-changed [--exclude IDS]     Auth-check changed agents; revert those that fail
    summary                            Print a commit message for the working-tree changes
    resolve-conflicts                  Resolve agent.json merge conflicts after an upstream merge
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

sys.path.insert(0, str(WORKFLOWS_DIR))

from common import VersionUpdate  # noqa: E402
from registry_utils import load_quarantine, semver_sort_key  # noqa: E402

# Fields that change on every release; differences elsewhere count as structural.
VOLATILE_KEYS = {"version", "package", "archive", "sha256"}


def load_config() -> dict:
    config = json.loads(CONFIG_PATH.read_text())
    return {
        "unquarantine": set(config.get("unquarantine", [])),
        "skip_verify": set(config.get("skip_verify", [])),
        "pin": dict(config.get("pin", {})),
    }


def fork_quarantine(config: dict):
    def load(registry_dir: Path) -> dict[str, str]:
        quarantine = load_quarantine(registry_dir)
        return {k: v for k, v in quarantine.items() if k not in config["unquarantine"]}

    return load


def git(*args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=check, capture_output=True, text=True
    ).stdout


def cmd_update(argv: list[str]) -> None:
    import update_versions

    config = load_config()
    update_versions.load_quarantine = fork_quarantine(config)
    find_all_agents = update_versions.find_all_agents

    def find_unpinned(registry_dir: Path):
        agents = find_all_agents(registry_dir)
        for agent_id in config["pin"]:
            print(f"  ⊘ Pinned {agent_id}: {config['pin'][agent_id]}", file=sys.stderr)
        return [(p, d) for p, d in agents if d.get("id") not in config["pin"]]

    update_versions.find_all_agents = find_unpinned
    sys.argv = ["update_versions.py", *argv]
    update_versions.main()


def cmd_verify(argv: list[str]) -> None:
    import verify_agents

    verify_agents.load_quarantine = fork_quarantine(load_config())
    sys.argv = ["verify_agents.py", *argv]
    verify_agents.main()


def cmd_set(argv: list[str]) -> None:
    from update_versions import apply_update

    if not argv:
        sys.exit("usage: fork_tools.py set ID=VERSION[@preview] ...")
    failed = False
    for entry in argv:
        spec, _, channel = entry.partition("@")
        agent_id, _, version = spec.partition("=")
        channel = channel or "stable"
        agent_path = REPO_ROOT / agent_id / "agent.json"
        if not agent_id or not version or channel not in ("stable", "preview"):
            sys.exit(f"Invalid entry: {entry!r}")
        if not agent_path.is_file():
            sys.exit(f"Unknown agent: {agent_id}")
        agent = json.loads(agent_path.read_text())
        current = (
            (agent.get("preview") or {}).get("version")
            if channel == "preview"
            else agent.get("version")
        )
        if current == version:
            print(f"{agent_id} ({channel}) already at {version}")
            continue
        update = VersionUpdate(
            agent_id=agent_id,
            agent_path=agent_path,
            current_version=current or "0.0.0",
            latest_version=version,
            distribution_type="manual",
            source_url="manual",
            repository=agent.get("repository", ""),
            channel=channel,
        )
        ok = apply_update(update)
        failed |= not ok
        print(f"{agent_id} ({channel}): {current} -> {version} {'OK' if ok else 'FAILED'}")
    if failed:
        sys.exit(1)


def changed_agents() -> dict[str, dict[str, tuple[str | None, str | None]]]:
    """Map agent id -> {channel: (old, new)} for agent.json files changed vs HEAD."""
    result: dict[str, dict[str, tuple[str | None, str | None]]] = {}
    for rel_path in git("diff", "--name-only", "HEAD").splitlines():
        parts = Path(rel_path).parts
        if len(parts) != 2 or parts[1] != "agent.json":
            continue
        old = json.loads(git("show", f"HEAD:{rel_path}"))
        new = json.loads((REPO_ROOT / rel_path).read_text())
        channels = {}
        if old.get("version") != new.get("version"):
            channels["stable"] = (old.get("version"), new.get("version"))
        old_preview = (old.get("preview") or {}).get("version")
        new_preview = (new.get("preview") or {}).get("version")
        if old_preview != new_preview:
            channels["preview"] = (old_preview, new_preview)
        result[parts[0]] = channels
    return result


def revert_agent(agent_id: str, reason: str) -> None:
    rel_path = f"{agent_id}/agent.json"
    (REPO_ROOT / rel_path).write_text(git("show", f"HEAD:{rel_path}"))
    print(f"::warning title=Fork update reverted::{agent_id}: {reason}")


def registry_errors(agent_id: str) -> list[str]:
    """Run the upstream per-agent build checks (schema, versions, URLs, icon)."""
    import build_registry

    _, errors = build_registry.process_entry(
        REPO_ROOT / agent_id,
        "agent.json",
        "agent",
        build_registry.load_schema(REPO_ROOT),
        build_registry.get_base_url(),
        {},
    )
    return errors


def cmd_verify_changed(argv: list[str]) -> None:
    exclude: set[str] = set()
    if argv[:1] == ["--exclude"] and len(argv) > 1:
        exclude = {a for a in argv[1].split(",") if a}
    config = load_config()
    for agent_id, channels in sorted(changed_agents().items()):
        # One broken agent must not block the whole batch from committing.
        errors = registry_errors(agent_id)
        if errors:
            print("\n".join(errors))
            revert_agent(agent_id, "registry validation failed")
            continue
        # Preview distributions are never launched upstream either.
        if "stable" not in channels:
            continue
        if agent_id in config["skip_verify"] or agent_id in exclude:
            print(f"Skip verification for {agent_id}")
            continue
        print(f"::group::Verify {agent_id}", flush=True)
        proc = subprocess.run(
            [sys.executable, __file__, "verify", "--auth-check", "--agent", agent_id],
            cwd=REPO_ROOT,
        )
        print("::endgroup::", flush=True)
        if proc.returncode != 0:
            revert_agent(agent_id, "auth verification failed")


def cmd_summary(_argv: list[str]) -> None:
    lines = []
    for agent_id, channels in sorted(changed_agents().items()):
        for channel, (old, new) in channels.items():
            label = f"{agent_id} (preview)" if channel == "preview" else agent_id
            lines.append(f"{label}: {old} -> {new}")
    if not lines:
        return
    if len(lines) == 1:
        print(f"fork: update {lines[0]}")
    else:
        print(f"fork: update {len(lines)} agent versions\n")
        print("\n".join(f"- {line}" for line in lines))


def strip_volatile(value):
    if isinstance(value, dict):
        return {k: strip_volatile(v) for k, v in value.items() if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [strip_volatile(v) for v in value]
    return value


def version_keys(agent: dict) -> tuple[tuple, tuple]:
    preview = (agent.get("preview") or {}).get("version") or "0.0.0"
    return semver_sort_key(agent.get("version") or "0.0.0"), semver_sort_key(preview)


def resolve_agent_conflict(base: dict, ours: dict, theirs: dict) -> dict | None:
    """Pick the side with the newer versions; None when it needs a human."""
    ours_keys, theirs_keys = version_keys(ours), version_keys(theirs)
    if all(t >= o for t, o in zip(theirs_keys, ours_keys, strict=True)):
        return theirs
    # Keeping ours must not silently drop upstream's non-version changes.
    ours_newer = all(o >= t for o, t in zip(ours_keys, theirs_keys, strict=True))
    if ours_newer and strip_volatile(base) == strip_volatile(theirs):
        return ours
    return None


def cmd_resolve_conflicts(_argv: list[str]) -> None:
    conflicted = git("diff", "--name-only", "--diff-filter=U").splitlines()
    unresolved = []
    for rel_path in conflicted:
        parts = Path(rel_path).parts
        if len(parts) != 2 or parts[1] != "agent.json":
            unresolved.append(rel_path)
            continue
        try:
            base, ours, theirs = (
                json.loads(git("show", f":{stage}:{rel_path}")) for stage in (1, 2, 3)
            )
        except subprocess.CalledProcessError:
            unresolved.append(rel_path)
            continue
        chosen = resolve_agent_conflict(base, ours, theirs)
        if chosen is None:
            unresolved.append(rel_path)
            continue
        side = "upstream" if chosen is theirs else "fork"
        (REPO_ROOT / rel_path).write_text(json.dumps(chosen, indent=2) + "\n")
        git("add", rel_path)
        print(f"Resolved {rel_path} using {side} version")
    if unresolved:
        print("Unresolved conflicts:", file=sys.stderr)
        for rel_path in unresolved:
            print(f"  {rel_path}", file=sys.stderr)
        sys.exit(1)


COMMANDS = {
    "update": cmd_update,
    "verify": cmd_verify,
    "set": cmd_set,
    "verify-changed": cmd_verify_changed,
    "summary": cmd_summary,
    "resolve-conflicts": cmd_resolve_conflicts,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(f"usage: fork_tools.py {{{','.join(COMMANDS)}}} ...")
    COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
