"""Single source of truth for every path the harness resolves at runtime.

Nothing outside this module should derive a repo path from ``__file__``. Call
the accessors here instead so a layout change never turns into a guess.
"""
from __future__ import annotations

from pathlib import Path

# vera_cycle/paths.py -> vera_cycle/ -> repository root.
PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent

VERSION_FILE = REPO_ROOT / "VERSION"
CAMPAIGNS_DIR = REPO_ROOT / "campaigns"
CONFIG_DIR = REPO_ROOT / "config"
PROJECTS_DIR = REPO_ROOT / "projects"
SCRIPTS_DIR = REPO_ROOT / "scripts"

ISSUE_POLICY = CONFIG_DIR / "issue_policy.md"

# Operator-supplied logins. Kept per project, because each project has its own
# machines and its own passwords, and out of git (see .gitignore). Loaded
# automatically so a campaign does not need the operator to export anything.
CREDENTIALS_FILE = REPO_ROOT / ".env.credentials"


def credentials_path(project: str) -> Path:
    """Per-project login file, falling back to the repository-wide one."""
    local = project_dir(project) / ".env.credentials"
    return local if local.exists() else CREDENTIALS_FILE

REPORTING_ASSETS = PACKAGE_ROOT / "reporting" / "assets"
REPORT_CSS = REPORTING_ASSETS / "report.css"
REPORT_JS = REPORTING_ASSETS / "report.js"
WISTRON_LOGO = REPORTING_ASSETS / "wistron-logo.svg"


def project_dir(project: str) -> Path:
    """Directory owned by one project's hardware definition."""
    return PROJECTS_DIR / project


def project_config_path(project: str) -> Path:
    """Return the project-owned hardware configuration script."""
    return project_dir(project) / f"{project}_config.sh"


def inventory_path(project: str) -> Path:
    """Checked-in inventory template for one project."""
    return project_dir(project) / f"cycle_inventory_{project}.csv"


def mctp_stressor_path() -> Path:
    """Repository copy of the P5032 MCTP stressor pushed to the BMC."""
    return project_dir("neutrino") / "mctp-stressor-p5032.sh"


def hwfw_script_path() -> Path:
    """Repository copy of the OS-side hardware/firmware inventory script."""
    return project_dir("neutrino") / "hwfw" / "vera_hwfw_inventory.sh"
