from behave import *
from contextlib import contextmanager
import tempfile
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "steps"))
import mock_github


@contextmanager
def cd(newdir):
    prevdir = os.getcwd()
    os.chdir(os.path.expanduser(newdir))
    try:
        yield
    finally:
        os.chdir(prevdir)


def before_all(context):
    context.tempdir = tempfile.TemporaryDirectory()
    context.repo = mock_github.REPO

    # A local git repo standing in for the fork PR 102's branch lives on, so
    # pr_branches.py can fetch a real commit without touching the network.
    # Author/committer identity and dates are pinned so the resulting commit
    # hash is reproducible - tests/content/mock_known_good.json bakes in the
    # exact SHA this produces.
    origin_dir = os.path.join(context.tempdir.name, "origin", context.repo)
    git_env = dict(
        os.environ,
        GIT_AUTHOR_NAME="Test User",
        GIT_AUTHOR_EMAIL="test@example.invalid",
        GIT_AUTHOR_DATE="2020-01-01T00:00:00+00:00",
        GIT_COMMITTER_NAME="Test User",
        GIT_COMMITTER_EMAIL="test@example.invalid",
        GIT_COMMITTER_DATE="2020-01-01T00:00:00+00:00",
    )
    subprocess.run(["git", "init", "-q", origin_dir], check=True, env=git_env)
    with open(os.path.join(origin_dir, "file.txt"), "w") as f:
        f.write("hello\n")
    subprocess.run(
        ["git", "-C", origin_dir, "add", "file.txt"], check=True, env=git_env
    )
    subprocess.run(
        ["git", "-C", origin_dir, "commit", "-q", "-m", "PR 102 head"],
        check=True,
        env=git_env,
    )
    context.pr_102_sha = subprocess.run(
        ["git", "-C", origin_dir, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    context.mock_server = mock_github.MockGitHubServer(
        head_ref_oid_102=context.pr_102_sha
    )
    context.mock_server.__enter__()

    os.environ["GITHUB_GRAPHQL_URL"] = context.mock_server.url
    os.environ["GITHUB_BASE_URL"] = os.path.join(context.tempdir.name, "origin")
    # Nothing here calls the real API, so a leftover real token must not leak in.
    os.environ.pop("GITHUB_API_TOKEN", None)


def after_all(context):
    context.mock_server.__exit__(None, None, None)
