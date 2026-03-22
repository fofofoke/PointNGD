"""GitHub update checker and updater for LC AB.

Works in two modes:
  1. Git mode  – if .git directory exists, uses git fetch/pull.
  2. API mode  – otherwise, uses GitHub REST API + zip download.
A local VERSION file stores the current commit SHA for API mode.
"""
import io
import logging
import os
import shutil
import subprocess
import sys
import zipfile

import requests

logger = logging.getLogger(__name__)

GITHUB_REPO = "fofofoke/PointNGD"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}"
GITHUB_BRANCH = "main"

# Project root – parent of the ``core/`` package directory.
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(PROJECT_DIR, "VERSION")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _has_git_repo():
    """Return True if the project lives inside a git repository."""
    d = PROJECT_DIR
    for _ in range(20):
        if os.path.isdir(os.path.join(d, ".git")):
            return True
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return False


def _find_git():
    """Find the git executable."""
    found = shutil.which("git")
    if found:
        return found
    if sys.platform == "win32":
        for base in (
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ):
            path = os.path.join(base, "Git", "cmd", "git.exe")
            if os.path.isfile(path):
                return path
    return None


def _run_git(*args):
    """Run a git command and return stdout."""
    git = _find_git()
    if git is None:
        raise FileNotFoundError("git not found")
    cmd = [git] + list(args)
    kw = dict(cwd=PROJECT_DIR, capture_output=True, text=True, timeout=30)
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    result = subprocess.run(cmd, **kw)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {args[0]} failed")
    return result.stdout.strip()


# ------------------------------------------------------------------
# Version tracking (for API mode)
# ------------------------------------------------------------------

def _read_local_version():
    """Read the locally stored commit SHA."""
    if os.path.isfile(VERSION_FILE):
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def _write_local_version(sha):
    """Save the current commit SHA."""
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        f.write(sha)


# ------------------------------------------------------------------
# Git-based workflow
# ------------------------------------------------------------------

def _check_git():
    branch = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    _run_git("fetch", "origin")
    local = _run_git("rev-parse", "HEAD")
    remote = _run_git("rev-parse", f"origin/{branch}")
    if local == remote:
        return {"has_update": False, "local_commit": local[:8],
                "remote_commit": remote[:8], "update_log": "", "error": None}
    log = _run_git("log", "--oneline", f"HEAD..origin/{branch}")
    return {"has_update": True, "local_commit": local[:8],
            "remote_commit": remote[:8], "update_log": log, "error": None}


def _apply_git():
    branch = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    output = _run_git("pull", "origin", branch)
    return {"success": True, "message": output}


# ------------------------------------------------------------------
# GitHub API-based workflow
# ------------------------------------------------------------------

def _check_api():
    resp = requests.get(
        f"{GITHUB_API}/commits/{GITHUB_BRANCH}",
        headers={"Accept": "application/vnd.github.v3+json"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    remote_sha = data["sha"]
    local_sha = _read_local_version()

    # First run: no VERSION file means the user just downloaded the latest.
    # Save the current remote SHA so future checks work correctly.
    if not local_sha:
        _write_local_version(remote_sha)
        return {"has_update": False, "local_commit": remote_sha[:8],
                "remote_commit": remote_sha[:8], "update_log": "", "error": None}

    if local_sha == remote_sha:
        return {"has_update": False, "local_commit": local_sha[:8],
                "remote_commit": remote_sha[:8], "update_log": "", "error": None}

    # Fetch recent commits for the changelog
    log_resp = requests.get(
        f"{GITHUB_API}/commits",
        params={"sha": GITHUB_BRANCH, "per_page": 10},
        headers={"Accept": "application/vnd.github.v3+json"},
        timeout=15,
    )
    log_lines = []
    if log_resp.ok:
        for c in log_resp.json():
            if c["sha"] == local_sha:
                break
            short = c["sha"][:8]
            msg = c["commit"]["message"].split("\n")[0]
            log_lines.append(f"{short} {msg}")

    return {
        "has_update": True,
        "local_commit": local_sha[:8],
        "remote_commit": remote_sha[:8],
        "update_log": "\n".join(log_lines) if log_lines else data["commit"]["message"].split("\n")[0],
        "error": None,
    }


def _apply_api():
    """Download the latest zip from GitHub and overwrite project files."""
    url = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/{GITHUB_BRANCH}.zip"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        # The zip contains a single top-level folder like "PointNGD-main/"
        prefix = zf.namelist()[0].split("/")[0] + "/"
        for member in zf.namelist():
            rel = member[len(prefix):]
            if not rel:
                continue
            dest = os.path.join(PROJECT_DIR, rel)
            if member.endswith("/"):
                os.makedirs(dest, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(member) as src, open(dest, "wb") as dst:
                    dst.write(src.read())

    # Save the new version
    ver_resp = requests.get(
        f"{GITHUB_API}/commits/{GITHUB_BRANCH}",
        headers={"Accept": "application/vnd.github.v3+json"},
        timeout=15,
    )
    if ver_resp.ok:
        _write_local_version(ver_resp.json()["sha"])

    return {"success": True, "message": "Downloaded and applied latest version."}


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def check_for_updates():
    """Check if there are updates available.

    Returns dict with keys: has_update, local_commit, remote_commit,
    update_log, error.
    """
    try:
        if _has_git_repo():
            return _check_git()
        return _check_api()
    except Exception as e:
        logger.error("Update check failed: %s", e)
        return {"has_update": False, "local_commit": "", "remote_commit": "",
                "update_log": "", "error": str(e)}


def apply_update():
    """Apply the latest update.

    Returns dict with keys: success, message.
    """
    try:
        if _has_git_repo():
            return _apply_git()
        return _apply_api()
    except Exception as e:
        logger.error("Update failed: %s", e)
        return {"success": False, "message": str(e)}
