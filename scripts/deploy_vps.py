#!/usr/bin/env python3
"""VPS deployment script for the grocery price tracker (spec §4.11).

Copies EXACTLY the files created/edited by implementation Tasks 1–11 to
the VPS with scp (argument-list invocations only — no shell), then
restarts the openclaw-core container once and runs an in-container
smoke check (`searched-items show`).

    python scripts/deploy_vps.py --dry-run    # print the plan (D-1)
    python scripts/deploy_vps.py              # scp mode (default)
    python scripts/deploy_vps.py --git-mode   # git push instead of scp

Runtime data (queues, cookies, snapshots), `.env`, and `.docx` files are
NEVER deployed (D-1). Any failed copy -> non-zero exit + retry hint
(D-3); `--git-mode` without a configured remote falls back to scp mode
wholesale — never a half-deploy (D-4).

Exit codes: 0 = success (or planned dry-run), 1 = at least one failure.
"""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent          # scripts/
_TRACKER = _HERE.parent                          # grocery-price-tracker/
_ROOT = _TRACKER.parent                          # AI related/

# Mirrors grocery_price_cli.py (kept literal so deploy never imports the
# CLI just to learn the destination).
VPS_HOST = "ubuntu@169.58.107.0"
VPS_BASE = "/home/ubuntu/openclaw/tasks/ai-tools"
VPS_SKILLS = "/home/ubuntu/openclaw/skills/grocery-price"
CONTAINER = "openclaw-core"
CLI_IN_CONTAINER = f"{VPS_BASE}/grocery_price_cli.py"

# FILE_MANIFEST (D-1): every file created/edited by Tasks 1–11 — local
# path relative to the workspace root, remote absolute directory.
# NOTHING else may appear here: no .env, no data/, no .docx.
_FILE_MANIFEST: list[tuple[str, str]] = [
    # Parent repo
    ("grocery_price_cli.py", VPS_BASE),
    ("claw-skills/grocery-price/SKILL.md", VPS_SKILLS),
    # Tracker core (Tasks 1-6)
    ("grocery-price-tracker/core/uom.py",
     f"{VPS_BASE}/grocery-price-tracker/core"),
    ("grocery-price-tracker/core/searched_items.py",
     f"{VPS_BASE}/grocery-price-tracker/core"),
    ("grocery-price-tracker/core/lookup.py",
     f"{VPS_BASE}/grocery-price-tracker/core"),
    ("grocery-price-tracker/core/price_comparator.py",
     f"{VPS_BASE}/grocery-price-tracker/core"),
    # Tracker extractors (Tasks 3/7/8)
    ("grocery-price-tracker/extractors/models.py",
     f"{VPS_BASE}/grocery-price-tracker/extractors"),
    ("grocery-price-tracker/extractors/coles_extractor.py",
     f"{VPS_BASE}/grocery-price-tracker/extractors"),
    ("grocery-price-tracker/extractors/woolworths_extractor.py",
     f"{VPS_BASE}/grocery-price-tracker/extractors"),
    ("grocery-price-tracker/extractors/live_list_fetch.py",
     f"{VPS_BASE}/grocery-price-tracker/extractors"),
    ("grocery-price-tracker/extractors/session_refresh.py",
     f"{VPS_BASE}/grocery-price-tracker/extractors"),
    # Tracker tests (Tasks 1-9)
    ("grocery-price-tracker/tests/test_uom.py",
     f"{VPS_BASE}/grocery-price-tracker/tests"),
    ("grocery-price-tracker/tests/test_searched_items.py",
     f"{VPS_BASE}/grocery-price-tracker/tests"),
    ("grocery-price-tracker/tests/test_coles_recipe.py",
     f"{VPS_BASE}/grocery-price-tracker/tests"),
    ("grocery-price-tracker/tests/test_lookup_uom.py",
     f"{VPS_BASE}/grocery-price-tracker/tests"),
    ("grocery-price-tracker/tests/test_lookup.py",
     f"{VPS_BASE}/grocery-price-tracker/tests"),
    ("grocery-price-tracker/tests/test_comparator.py",
     f"{VPS_BASE}/grocery-price-tracker/tests"),
    ("grocery-price-tracker/tests/test_cli.py",
     f"{VPS_BASE}/grocery-price-tracker/tests"),
    ("grocery-price-tracker/tests/test_live_window.py",
     f"{VPS_BASE}/grocery-price-tracker/tests"),
    # Automation assets (Task 11)
    ("grocery-price-tracker/scripts/deploy_vps.py",
     f"{VPS_BASE}/grocery-price-tracker/scripts"),
    ("grocery-price-tracker/scripts/session_heartbeat_entry.py",
     f"{VPS_BASE}/grocery-price-tracker/scripts"),
    ("grocery-price-tracker/scripts/trial_check.py",
     f"{VPS_BASE}/grocery-price-tracker/scripts"),
    # Docs (Task 10/11)
    ("grocery-price-tracker/README.md",
     f"{VPS_BASE}/grocery-price-tracker"),
    ("grocery-price-tracker/.gitignore",
     f"{VPS_BASE}/grocery-price-tracker"),
]

FORBIDDEN_MARKERS = (".env", "data/", ".docx")


def build_plan(root: Path = _ROOT) -> list:
    """Materialise FILE_MANIFEST into existing (local, remote) pairs.

    Args:
        root (Path): workspace root the manifest paths resolve against.

    Returns:
        list[tuple[Path, str]]: (local file, remote directory).
    """
    plan = []
    for rel, remote in _FILE_MANIFEST:
        local = root / rel
        if local.is_file():
            plan.append((local, remote))
    return plan


def _run(cmd: list) -> subprocess.CompletedProcess:
    """Run a command with an ARGUMENT LIST (never via a shell)."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def _has_git_remote(root: Path = _ROOT) -> bool:
    """Whether the parent repo has a configured `origin` remote."""
    try:
        result = _run(["git", "-C", str(root), "remote"])
        return "origin" in (result.stdout or "")
    except Exception:
        return False


def _deploy_scp(plan: list, host: str = VPS_HOST) -> list:
    """scp every manifest file (one invocation per file, arg list).

    Args:
        plan (list): (local, remote) pairs.
        host (str): scp destination host.

    Returns:
        list[tuple]: the failed (local, remote) pairs (empty on success).
    """
    failed = []
    for local, remote in plan:
        print(f"  scp {local.name} -> {host}:{remote}/")
        result = _run(["scp", "-o", "ConnectTimeout=10", str(local),
                       f"{host}:{remote}/{local.name}"])
        if result.returncode != 0:
            print(f"    FAILED: {(result.stderr or '').strip()}")
            failed.append((local, remote))
        else:
            print("    OK")
    return failed


def _deploy_git(plan: list, root: Path = _ROOT,
                host: str = VPS_HOST) -> list:
    """Deploy via git (add manifest -> commit -> push). Never partial:
    the commit contains the whole manifest or nothing is pushed."""
    rels = [str(local.relative_to(root)) for local, _remote in plan]
    for rel in rels:
        add = _run(["git", "-C", str(root), "add", rel])
        if add.returncode != 0:
            print(f"    git add FAILED for {rel}: {add.stderr.strip()}")
            return list(plan)
    commit = _run(["git", "-C", str(root), "commit", "-m",
                   "deploy: live-window artefacts"])
    if commit.returncode != 0 and "nothing to commit" not in (
            commit.stdout or ""):
        print(f"    git commit FAILED: {(commit.stderr or '').strip()}")
        return list(plan)
    push = _run(["git", "-C", str(root), "push"])
    if push.returncode != 0:
        print(f"    git push FAILED: {(push.stderr or '').strip()}")
        return list(plan)
    print("    git push OK")
    return []


def main() -> int:
    """Entry point (D-1..D-4)."""
    parser = argparse.ArgumentParser(
        description="Deploy grocery tracker artefacts to the VPS")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the plan; copy nothing")
    parser.add_argument("--git-mode", action="store_true",
                        help="Deploy via git push (falls back to scp "
                             "when no origin remote is configured)")
    args = parser.parse_args()

    plan = build_plan()
    if not plan:
        print("Nothing to deploy — plan is empty.", file=sys.stderr)
        return 1
    missing = [rel for rel, _ in _FILE_MANIFEST
               if not (_ROOT / rel).is_file()]
    if missing:
        print("Manifest file(s) missing on disk — refusing a partial "
              f"deploy: {missing}", file=sys.stderr)
        return 1

    print(f"Deploy target: {VPS_HOST}")
    print(f"{'DRY RUN' if args.dry_run else 'Deploying'} "
          f"({len(plan)} file(s)):")
    for local, remote in plan:
        print(f"  {local.relative_to(_ROOT)} -> {remote}/")
    if args.dry_run:
        print("Dry run complete — nothing copied.")
        return 0

    if args.git_mode and not _has_git_remote():
        print("--git-mode requested but no origin remote configured — "
              "falling back to scp mode (no half-deploy).")
        args = argparse.Namespace(dry_run=False, git_mode=False)

    if args.git_mode:
        failed = _deploy_git(plan)
    else:
        failed = _deploy_scp(plan)
    if failed:
        print(f"{len(failed)} copy(ies) FAILED. Re-run the deploy to "
              f"retry: python scripts/deploy_vps.py"
              + (" --git-mode" if args.git_mode else ""),
              file=sys.stderr)
        return 1

    # Container restart (exactly once) + in-container smoke check.
    print(f"Restarting container {CONTAINER}…")
    restart = _run(["docker", "restart", CONTAINER])
    if restart.returncode != 0:
        print(f"docker restart FAILED: {(restart.stderr or '').strip()}",
              file=sys.stderr)
        return 1
    print("    OK")
    smoke = _run(["docker", "exec", CONTAINER, "python3",
                  CLI_IN_CONTAINER, "searched-items", "show"])
    if smoke.returncode != 0:
        print(f"Container smoke check FAILED: "
              f"{(smoke.stderr or smoke.stdout).strip()}", file=sys.stderr)
        return 1
    print("Container smoke check (searched-items show): OK")
    print("Deploy complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
