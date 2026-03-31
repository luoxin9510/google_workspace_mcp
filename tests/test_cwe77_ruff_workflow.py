"""
Test that the ruff.yml GitHub Actions workflow does NOT check out
attacker-controlled code from fork PRs (CWE-77).

The vulnerability: the workflow uses pull_request trigger with
  repository: ${{ github.event.pull_request.head.repo.full_name }}
which checks out the fork's code directly. An attacker can poison
pyproject.toml or inject malicious ruff plugins to achieve code execution
with the workflow's contents:write GITHUB_TOKEN.

The fix: remove the explicit repository/ref override so `actions/checkout`
uses the default merge commit ref (github.sha) for pull_request events.
"""

import sys
import os
import yaml

# Resolve the repo root (one level up from tests/)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_PATH = os.path.join(REPO_ROOT, ".github", "workflows", "ruff.yml")



def load_workflow(path):
    with open(path, "r") as f:
        return yaml.safe_load(f), f.read()


def test_no_fork_repo_checkout():
    """Checkout step must NOT reference github.event.pull_request.head.repo.full_name
    as the repository parameter, which would check out attacker-controlled fork code."""
    wf, raw = load_workflow(WORKFLOW_PATH)

    jobs = wf.get("jobs", {})
    for job_name, job in jobs.items():
        steps = job.get("steps", [])
        for step in steps:
            uses = step.get("uses", "")
            if "actions/checkout" in uses:
                with_params = step.get("with", {})
                repo_param = str(with_params.get("repository", ""))

                # Must NOT reference the fork's repo
                assert "pull_request.head.repo" not in repo_param, (
                    f"Job '{job_name}' checkout uses fork repository: {repo_param}. "
                    "This allows attacker-controlled code execution."
                )


def test_uv_sync_not_on_fork_prs():
    """uv sync (which installs from pyproject.toml) should not run on fork PRs,
    or the checkout should not contain fork code."""
    wf, raw = load_workflow(WORKFLOW_PATH)

    jobs = wf.get("jobs", {})
    for job_name, job in jobs.items():
        steps = job.get("steps", [])

        # Check if checkout references fork repo
        checkout_uses_fork = False
        for step in steps:
            uses = step.get("uses", "")
            if "actions/checkout" in uses:
                with_params = step.get("with", {})
                repo_param = str(with_params.get("repository", ""))
                if "pull_request.head.repo" in repo_param:
                    checkout_uses_fork = True

        if checkout_uses_fork:
            # If checking out fork code, uv sync must be guarded
            for step in steps:
                run_cmd = str(step.get("run", ""))
                if "uv sync" in run_cmd:
                    step_if = str(step.get("if", ""))
                    assert "head.repo.full_name == github.repository" in step_if or \
                           "head.repo.full_name ==" in step_if, (
                        f"Job '{job_name}' runs 'uv sync' on fork checkout without fork guard. "
                        "Attacker's pyproject.toml will be installed."
                    )


def test_no_write_permissions_or_fork_guarded():
    """If the workflow has write permissions, it must not execute fork code,
    or execution steps must be guarded against fork PRs."""
    wf, raw = load_workflow(WORKFLOW_PATH)

    # Check top-level permissions
    perms = wf.get("permissions", {})
    has_write = False
    if isinstance(perms, str):
        has_write = perms == "write-all"
    elif isinstance(perms, dict):
        has_write = any(v == "write" for v in perms.values())

    if not has_write:
        return  # No write permissions, lower risk

    # If write permissions exist, checkout must not use fork repo
    jobs = wf.get("jobs", {})
    for job_name, job in jobs.items():
        steps = job.get("steps", [])
        for step in steps:
            uses = step.get("uses", "")
            if "actions/checkout" in uses:
                with_params = step.get("with", {})
                repo_param = str(with_params.get("repository", ""))
                assert "pull_request.head.repo" not in repo_param, (
                    f"Job '{job_name}' has write permissions AND checks out fork code. "
                    "This is a critical security issue (CWE-77)."
                )


if __name__ == "__main__":
    tests = [
        test_no_fork_repo_checkout,
        test_uv_sync_not_on_fork_prs,
        test_no_write_permissions_or_fork_guarded,
    ]

    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS: {test.__name__}")
        except AssertionError as e:
            print(f"  FAIL: {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {test.__name__}: {e}")
            failed += 1

    if failed:
        print(f"\n{failed} test(s) failed")
        sys.exit(1)
    else:
        print("\nAll tests passed")
        sys.exit(0)
