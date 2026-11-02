"""The only publishing job must depend on the checked candidate commit."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_release_workflow_is_fail_closed_and_pr_safe():
    text = (ROOT / ".github/workflows/release-from-changelog.yml").read_text(
        encoding="utf-8"
    )
    workflow = yaml.safe_load(text)
    # PyYAML's YAML 1.1 loader treats the unquoted GitHub key `on` as True.
    events = workflow.get("on", workflow.get(True))
    assert events["pull_request"]["branches"] == ["main"]
    assert events["push"]["branches"] == ["main"]
    assert "pull_request_target" not in events
    dispatch = events["workflow_dispatch"]
    assert dispatch["inputs"]["publish"]["default"] is False
    assert dispatch["inputs"]["publish"]["type"] == "boolean"
    assert workflow["permissions"] == {"contents": "read"}
    check = workflow["jobs"]["check"]
    release = workflow["jobs"]["release"]
    assert release["needs"] == "check"
    assert "refs/heads/main" in release["if"]
    assert "should_release" in release["if"]
    assert release["permissions"] == {"contents": "write"}
    assert any("scripts/check.py" in step.get("run", "") for step in check["steps"])
    assert not any("GH_TOKEN" in step.get("env", {}) for step in check["steps"])
    assert any(
        "scripts/release.py publish" in step.get("run", "") for step in release["steps"]
    )
    assert "--clobber" not in text and "tag_prefix" not in text
    for job in (check, release):
        checkout = next(
            step
            for step in job["steps"]
            if step.get("uses", "").startswith("actions/checkout@")
        )
        assert checkout["with"]["persist-credentials"] is False
        assert job["timeout-minutes"] <= 30


def test_manual_dispatch_does_not_publish_by_default():
    text = (ROOT / ".github/workflows/release-from-changelog.yml").read_text(
        encoding="utf-8"
    )
    candidate = text.split("id: candidate", 1)[1].split(
        "name: Publish verified commit", 1
    )[0]
    assert "PUBLISH_INPUT: ${{ inputs.publish }}" in candidate
    assert 'if [ "$PUBLISH_INPUT" = true ]' in candidate
