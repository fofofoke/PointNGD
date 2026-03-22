"""GitHub update checker and updater for LC AB."""
import subprocess
import logging
import os

logger = logging.getLogger(__name__)

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GITHUB_REPO = "fofofoke/PointNGD"


def _run_git(*args):
    """Run a git command and return stdout."""
    cmd = ["git"] + list(args)
    result = subprocess.run(
        cmd, cwd=REPO_DIR, capture_output=True, text=True, timeout=30
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
