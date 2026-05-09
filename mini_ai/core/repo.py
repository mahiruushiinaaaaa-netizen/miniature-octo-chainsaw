import subprocess
from pathlib import Path
import logging

logger = logging.getLogger("repo")

def get_git_root(path: str) -> str:
    """Returns the git root directory or empty string if not a git repo."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            capture_output=True,
            text=True,
            check=True
        )
        return res.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""

def is_git_repo(path: str) -> bool:
    return bool(get_git_root(path))

def git_commit(path: str, message: str, stage_all: bool = True) -> bool:
    """Commits changes in the repo."""
    if not is_git_repo(path):
        return False
        
    try:
        if stage_all:
            subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
            
        # Check if there are actually changes to commit
        status = subprocess.run(["git", "status", "--porcelain"], cwd=path, capture_output=True, text=True)
        if not status.stdout.strip():
            return True # Nothing to commit
            
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=path,
            check=True,
            capture_output=True
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Git commit failed: {e.stderr}")
        return False
        
def pre_edit_commit(path: str) -> None:
    """Called before AI makes an edit to save the user's uncommitted work."""
    git_commit(path, "mini-ai: uncommitted changes before AI edit", stage_all=True)

def post_edit_commit(path: str, action_name: str) -> None:
    """Called after AI makes an edit to snapshot the changes."""
    git_commit(path, f"mini-ai: applied {action_name}", stage_all=True)

def git_undo(path: str) -> tuple[bool, str]:
    """Revert the last commit."""
    if not is_git_repo(path):
        return False, "Not a git repository."
        
    try:
        res = subprocess.run(["git", "reset", "--hard", "HEAD~1"], cwd=path, capture_output=True, text=True, check=True)
        return True, "Reverted last change."
    except subprocess.CalledProcessError as e:
        return False, f"Failed to undo: {e.stderr}"

