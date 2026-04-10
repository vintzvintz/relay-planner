"""
relay._dirs

Package-level directory constants and utilities.
"""

from pathlib import Path

if False:
    from .solution import Solution


# Directory constants
PLANNING_DIR = "plannings"


def latest_solution_path() -> str:
    """Return the path to the most recently saved solution JSON file.

    Scans PLANNING_DIR for subdirectories named <timestamp>_<action>/
    and returns the path to planning.json in the most recent one.

    Returns
    -------
    str
        Path to the latest planning.json file.

    Raises
    ------
    FileNotFoundError
        If PLANNING_DIR does not exist or contains no solution files.
    """
    planning_path = Path(PLANNING_DIR)
    if not planning_path.exists():
        raise FileNotFoundError(f"Planning directory not found: {PLANNING_DIR}")

    json_files = sorted(planning_path.glob("????????_??????_*/planning.json"), reverse=True)
    if not json_files:
        raise FileNotFoundError(f"No solution files found in {PLANNING_DIR}")

    return str(json_files[0])


def latest_solution() -> "Solution":
    """Load and return the most recently saved solution.

    Returns
    -------
    Solution
        The deserialized solution object from the latest solution JSON file.

    Raises
    ------
    FileNotFoundError
        If PLANNING_DIR does not exist or contains no solution files.
    """
    from .solution import Solution

    sol, _path = Solution.from_latest()
    return sol
