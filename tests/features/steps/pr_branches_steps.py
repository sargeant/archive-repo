from behave import *
import subprocess
import os


@when("pr-branches is executed against the local git fixture")
def step_impl(context):
    filename = context.tempdir.name + "/current.json"
    context.working_dir = context.tempdir.name + "/working_repo"
    subprocess.run(["git", "init", "-q", context.working_dir], check=True)

    result = subprocess.run(
        [
            "python3",
            "-m",
            "archive-repo",
            "pr_branches",
            filename,
            context.repo,
            context.working_dir,
        ]
    )
    result.check_returncode()


@then('a branch named "{branch}" pointing to the fixture\'s head commit is created')
def step_impl(context, branch):
    result = subprocess.run(
        ["git", "-C", context.working_dir, "show-ref", "-s", f"refs/heads/{branch}"],
        capture_output=True,
        text=True,
    )
    result.check_returncode()
    assert context.pr_102_sha in result.stdout
