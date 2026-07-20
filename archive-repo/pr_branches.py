#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys
from .shared import archive_reference


def init(cmdline):
    parser = argparse.ArgumentParser(
        prog="pr_branches",
        description="Identify the source repos and forks of PRs from an archive",
    )
    parser.add_argument("input", help="GitHub archive file")
    parser.add_argument("repo", help="target GitHub repo")
    parser.add_argument("git_dir", help="Local directory with git repo", default=".")
    parser.add_argument(
        "--include-merged",
        dest="merged",
        default=False,
        action="store_true",
        help="include merged PRs in analysis",
    )
    parser.add_argument(
        "--dry-run",
        dest="dryRun",
        default=False,
        action="store_true",
        help="Show what would be done, without making any changes",
    )
    args = parser.parse_args(cmdline)

    generate_branches(args.input, args.repo, args.merged, args.git_dir, args.dryRun)


def generate_branches(input, repo, merged, git_dir=".", dryRun=False):
    reference = archive_reference.loadReference(input, repo)

    target_prs = (
        reference.prs.values()
        if merged
        else (pr for pr in reference.prs.values() if pr["state"] != "MERGED")
    )
    refspecs = {pr["headRefOid"] + ":pulls/" + str(pr["number"]) for pr in target_prs}

    if not refspecs:
        print("Nothing to do")
        return

    base_url = os.environ.get("GITHUB_BASE_URL", "https://github.com")
    command = ["git", "-C", git_dir, "fetch"]
    if dryRun:
        command.append("--dry-run")
    command.append(base_url + "/" + repo)
    command.extend(refspecs)

    subprocess.run(command).check_returncode()


if __name__ == "__main__":
    init(sys.argv)
