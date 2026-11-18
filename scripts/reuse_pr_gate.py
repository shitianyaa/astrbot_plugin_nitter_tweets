"""Reuse a passing PR gate only when it checked the same Git tree."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

try:
    from .release import GitHub, git
except ImportError:
    from release import GitHub, git


WORKFLOW = "release-from-changelog.yml"


def passing_pr_gate(github: GitHub, sha: str, tree: str) -> int | None:
    """Return a matching run ID, using GitHub metadata without downloading artifacts."""
    for pull in github.api(f"commits/{sha}/pulls"):
        if (
            not pull["merged_at"]
            or pull["base"]["ref"] != "main"
            or pull["merge_commit_sha"] != sha
        ):
            continue
        head = pull["head"]
        if not head["repo"]:
            continue
        runs = github.api(
            f"actions/workflows/{WORKFLOW}/runs"
            f"?head_sha={head['sha']}&event=pull_request&status=success&per_page=100"
        )["workflow_runs"]
        for run in runs:
            if (
                run["event"] != "pull_request"
                or run["conclusion"] != "success"
                or run["head_sha"] != head["sha"]
                or run["head_branch"] != head["ref"]
                or (run["head_repository"] or {}).get("id") != head["repo"]["id"]
            ):
                continue
            run_id = run["id"]
            name = f"quality-gate-{pull['number']}-{tree}-{run['run_attempt']}"
            records = github.api(f"actions/runs/{run_id}/artifacts?name={name}")
            if any(
                record["name"] == name and not record["expired"]
                for record in records["artifacts"]
            ):
                return run_id
    return None


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    sha = os.environ["GITHUB_SHA"]
    if git(root, "rev-parse", "HEAD").decode().strip() != sha:
        raise ValueError("Checkout SHA differs from event SHA")
    tree = git(root, "rev-parse", "HEAD^{tree}").decode().strip()
    try:
        run_id = passing_pr_gate(GitHub(os.environ["GITHUB_REPOSITORY"]), sha, tree)
    except (
        KeyError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        subprocess.TimeoutExpired,
    ):
        print("Could not verify a passing PR gate. Running the full gate.")
        run_id = None
    if run_id is None:
        print("No matching PR gate for this tree.")
    else:
        print(f"Reusing the passing gate from PR workflow run {run_id}.")
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"reused={str(run_id is not None).lower()}\n")


if __name__ == "__main__":
    main()
