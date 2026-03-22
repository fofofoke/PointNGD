"""GitHub update checker and updater for LC AB."""
import subprocess
import logging
import os
import sys
import shutil

logger = logging.getLogger(__name__)

GITHUB_REPO = "fofofoke/PointNGD"


def _find_repo_dir():
    """Find the git repository root by walking up from several starting points."""
    # Starting candidates: parent of this file's dir, main script dir, cwd
    candidates = [
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv[0] else None,
        os.getcwd(),
    ]
    for start in candidates:
        if not start:
            continue
        d = os.path.abspath(start)
        # Walk up to filesystem root looking for .git
        for _ in range(20):
            if os.path.isdir(os.path.join(d, ".git")):
                return d
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


REPO_DIR = _find_repo_dir()

_git_path = None


def _find_git():
    """Find the git executable, searching common Windows paths if needed."""
    global _git_path
    if _git_path is not None:
        return _git_path

    # Try PATH first
    found = shutil.which("git")
    if found:
        _git_path = found
        return _git_path

    # Common Windows install locations
    if sys.platform == "win32":
        candidates = [
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                         "Git", "cmd", "git.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                         "Git", "cmd", "git.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""),
                         "Programs", "Git", "cmd", "git.exe"),
            r"C:\Git\cmd\git.exe",
        ]
        for path in candidates:
            if path and os.path.isfile(path):
                _git_path = path
                return _git_path

    raise FileNotFoundError(
        "git executable not found. Please install Git and ensure it is in PATH.\n"
        "Download: https://git-scm.com/download/win"
    )


def _run_git(*args):
    """Run a git command and return stdout."""
    git = _find_git()
    cmd = [git] + list(args)
    result = subprocess.run(
        cmd, cwd=REPO_DIR, capture_output=True, text=True, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {args[0]} failed")
    return result.stdout.strip()


def get_local_commit():
    """Get the current local HEAD commit hash."""
    return _run_git("rev-parse", "HEAD")


def get_local_branch():
    """Get the current local branch name."""
    return _run_git("rev-parse", "--abbrev-ref", "HEAD")


def fetch_remote():
    """Fetch updates from origin."""
    _run_git("fetch", "origin")


def get_remote_commit(branch=None):
    """Get the latest remote commit hash for the given branch."""
    if branch is None:
        branch = get_local_branch()
    return _run_git("rev-parse", f"origin/{branch}")


def get_update_log(branch=None):
    """Get log of commits between local HEAD and remote."""
    if branch is None:
        branch = get_local_branch()
    log = _run_git("log", "--oneline", f"HEAD..origin/{branch}")
    return log


def check_for_updates():
    """Check if there are updates available on the remote.

    Returns:
        dict with keys:
            - has_update (bool): True if updates are available
            - local_commit (str): local HEAD short hash
            - remote_commit (str): remote HEAD short hash
            - update_log (str): commit log of new changes
            - error (str or None): error message if check failed
    """
    try:
        fetch_remote()
        branch = get_local_branch()
        local = get_local_commit()
        remote = get_remote_commit(branch)

        if local == remote:
            return {
                "has_update": False,
                "local_commit": local[:8],
                "remote_commit": remote[:8],
                "update_log": "",
                "error": None,
            }

        log = get_update_log(branch)
        return {
            "has_update": True,
            "local_commit": local[:8],
            "remote_commit": remote[:8],
            "update_log": log,
            "error": None,
        }
    except Exception as e:
        logger.error("Update check failed: %s", e)
        return {
            "has_update": False,
            "local_commit": "",
            "remote_commit": "",
            "update_log": "",
            "error": str(e),
        }


def apply_update():
    """Pull the latest changes from origin.

    Returns:
        dict with keys:
            - success (bool): True if update was applied
            - message (str): result message
    """
    try:
        branch = get_local_branch()
        output = _run_git("pull", "origin", branch)
        logger.info("Update applied: %s", output)
        return {"success": True, "message": output}
    except Exception as e:
        logger.error("Update failed: %s", e)
        return {"success": False, "message": str(e)}
