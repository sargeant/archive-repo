#!/usr/bin/env python3

import os
import sys
import json
import requests
import argparse
from datetime import datetime, timezone
import time
import re
import dateutil.parser as dp
import shutil
import warnings
from .shared import archive_reference


def init(cmdline):
    global quiet

    parser = argparse.ArgumentParser(
        prog="archive", description="Archive repo issues and PRs."
    )
    parser.add_argument("repo", help="GitHub repo to archive (e.g. quicwg/base-drafts)")
    parser.add_argument("githubToken", help="GitHub OAuth token")
    parser.add_argument(
        "outFile", default=None, nargs="?", help="destination for output"
    )
    parser.add_argument(
        "--reference",
        dest="refFile",
        nargs="?",
        help="older file produced by this tool for reference",
    )
    parser.add_argument(
        "--issues-only",
        dest="issuesOnly",
        default=False,
        action="store_true",
        help="download issues, but not pull requests",
    )
    parser.add_argument(
        "--quiet",
        dest="quiet",
        default=False,
        action="store_true",
        help="do not output HTTP requests",
    )
    args = parser.parse_args(cmdline)

    if not args.githubToken and "GITHUB_API_TOKEN" in os.environ.keys():
        args.githubToken = os.environ["GITHUB_API_TOKEN"]

    if args.repo[-1] == "/":
        args.repo = args.repo[:-1]

    quiet = args.quiet

    do_archive(args.repo, args.githubToken, args.refFile, args.outFile, args.issuesOnly)


#######################
## Query definitions ##
#######################

# Query fragments

gql_LabelFields = """
fragment labels on Labelable {
    labels(first: 5) {
        nodes { name }
    }
}
"""

gql_AssigneeFields = """
fragment assignees on Assignable {
    assignees(first: 5) {
        nodes { login }
    }
}
"""

gql_AuthorFields = """
fragment author on Comment {
    author { login }
    authorAssociation
}
"""

gql_Comment_Fields = """
fragment commentFields on Comment {
    body
    createdAt
    updatedAt
}
"""

gql_RateLimit = """
fragment rateLimit on Query {
    rateLimit {
        cost
        remaining
        resetAt
    }
}
"""

gql_Paged = """
pageInfo {
    endCursor
    hasNextPage
}
"""

# Issues

gql_Issue_Fields = (
    """
fragment issueFields on Issue {
    number
    id
    title
    url
    state
    ...author
    ...assignees
    ...labels
    ...commentFields
    closedAt
    comments(first: 100) {
        nodes {
            ...author
            ...commentFields
        }
        """
    + gql_Paged
    + """
    }
}
"""
    + gql_AuthorFields
    + gql_AssigneeFields
    + gql_Comment_Fields
    + gql_LabelFields
)

gql_Issues_Query = (
    "nodes { ...issueFields }"
    + gql_Paged
    + """
    }
  }
  ...rateLimit
}
"""
    + gql_RateLimit
)

gql_AllIssues_First = (
    """
query($owner: String!, $repo: String!){
  repository(owner: $owner, name: $repo) {
    issues(first: 100) {
"""
    + gql_Issues_Query
)

gql_AllIssues_Subsequent = (
    """
query($owner: String!, $repo: String!, $cursor: String!){
  repository(owner: $owner, name: $repo) {
    issues(first: 100, after: $cursor) {
"""
    + gql_Issues_Query
)

gql_UpdatedIssues_First = (
    """
query($owner: String!, $repo: String!, $filters: IssueFilters){
  repository(owner: $owner, name: $repo) {
    issues(first: 100, filterBy: $filters) {
"""
    + gql_Issues_Query
)

gql_UpdatedIssues_Subsequent = (
    """
query($owner: String!, $repo: String!, $filters: IssueFilters, $cursor: String!){
  repository(owner: $owner, name: $repo) {
    issues(first: 100, filterBy: $filters, after: $cursor) {
"""
    + gql_Issues_Query
)

gql_Issue_Comments_Query = (
    """
query($id: ID!, $cursor: String!){
    node(id: $id) {
        ...on Issue {
            comments(first:100, after:$cursor) {
                nodes {
                    ...author
                    ...commentFields
                }
        """
    + gql_Paged
    + """
            }
        }
    }
    ...rateLimit
}
"""
    + gql_Comment_Fields
    + gql_AuthorFields
    + gql_RateLimit
)

# Pull Requests

gql_Review_Fields = (
    """
fragment reviewFields on PullRequestReview {
    id
    commit { abbreviatedOid }
    ...author
    state
    ...commentFields
    comments(first: 50) {
        nodes {
            originalPosition
            ...commentFields
        }
        """
    + gql_Paged
    + """
    }
}
"""
    + gql_Comment_Fields
    + gql_AuthorFields
)

gql_PullRequest_Fields = (
    """
fragment prFields on PullRequest {
    number
    id
    title
    url
    state
    ...author
    ...assignees
    ...labels
    ...commentFields
    baseRepository { nameWithOwner }
    baseRefName
    baseRefOid
    headRepository { nameWithOwner }
    headRefName
    headRefOid
    closedAt
    mergedAt
    mergedBy { login }
    mergeCommit { oid }
    comments(first: 100) {
        nodes {
            ...author
            ...commentFields
        }
        """
    + gql_Paged
    + """
    }
    reviews(first: 50) {
        nodes {
            ...reviewFields
        }
        """
    + gql_Paged
    + """
    }
}
"""
    + gql_AssigneeFields
    + gql_LabelFields
    + gql_Review_Fields
)
# ...reviewFields definition includes ...commentFields and ...author

gql_PullRequest_Query = (
    "nodes { ...prFields }"
    + gql_Paged
    + """
    }
  }
  ...rateLimit
}
"""
    + gql_RateLimit
)

gql_AllPRs_Initial = (
    """
query($owner: String!, $repo: String!){
  repository(owner: $owner, name: $repo) {
    pullRequests(first: 10, orderBy: {field: UPDATED_AT, direction:DESC}) {
"""
    + gql_PullRequest_Query
)

gql_AllPRs_Subsequent = (
    """
query($owner: String!, $repo: String!, $cursor: String!){
  repository(owner: $owner, name: $repo) {
    pullRequests(first: 25, after: $cursor, orderBy: {field: UPDATED_AT, direction:DESC}) {
"""
    + gql_PullRequest_Query
)

gql_PR_Comments_Query = (
    """
query($id: ID!, $cursor: String!){
    node(id: $id) {
        ...on PullRequest {
            comments(first:100, after:$cursor) {
                nodes { ...commentFields }
        """
    + gql_Paged
    + """
            }
        }
    }
}
"""
    + gql_Comment_Fields
    + gql_RateLimit
)

gql_PR_Review_Query = (
    """
query($id: ID!, $cursor: String!){
    node(id: $id) {
        ...on PullRequest {
            reviews(first:100, after:$cursor) {
                nodes { ...reviewFields }
        """
    + gql_Paged
    + """
            }
        }
    }
    ...rateLimit
}
"""
    + gql_Review_Fields
    + gql_RateLimit
)

gql_PR_ReviewComments_Query = (
    """
query($id: ID!, $cursor: String!){
    node(id: $id) {
        ...on PullRequestReview {
            comments(first: 50, after:$cursor) {
                nodes {
                    originalPosition
                    ...commentFields
                }
        """
    + gql_Paged
    + """
            }
        }
    }
    ...rateLimit
}
"""
    + gql_Comment_Fields
    + gql_RateLimit
)

# Labels

gql_Labels_Query = (
    """
query($owner: String!, $repo: String!){
    repository(owner: $owner, name: $repo) {
        labels(first:100) {
            nodes {
                name
                description
                color
            }
        """
    + gql_Paged
    + """
        }
    }
    ...rateLimit
}
"""
    + gql_RateLimit
)

gql_MoreLabels_Query = (
    """
query($owner: String!, $repo: String!, $cursor: String!) {
    repository(owner: $owner, name: $repo) {
        labels(first:100, after:$cursor) {
            nodes {
                name
                description
                color
            }
            """
    + gql_Paged
    + """
        }
    }
    ...rateLimit
}
"""
    + gql_RateLimit
)


##########################
## Function definitions ##
##########################


last_request_limit = 5000
next_reset_time = datetime.now(timezone.utc)


def stall_until(reset_time):
    time_to_sleep = (reset_time - datetime.now(timezone.utc)).total_seconds() + 1
    print(f"GitHub API rate-limited; waiting for {time_to_sleep} seconds")
    time.sleep(time_to_sleep)


def submit_query(query, variables, display):
    global last_request_limit
    global next_reset_time

    url = "https://api.github.com/graphql"

    bodyjson = {"query": re.sub(r"\s+", " ", query).strip()}
    if variables:
        bodyjson["variables"] = variables
    body = json.dumps(bodyjson)

    output = f"Submitting query for {display} with "
    output += str(variables) if variables else "no parameters"
    log(output)
    result = dict()

    for _attempt in range(3):
        try:
            response = s.post(url, body)
            response.raise_for_status()
            result = response.json()
        except:
            time.sleep(5)
            pass

        if (
            "errors" in result
            and "type" in result["errors"]
            and result["errors"]["type"] == "RATE_LIMITED"
        ):
            # We're rate-limited; STALL
            if next_reset_time > datetime.now(timezone.utc):
                stall_until(next_reset_time)
            else:
                # We haven't made a successful request, so we don't know how long to sleep.
                # Guesstimate 10 minutes and try again.
                time.sleep(600)
            continue

        break

    if "data" in result.keys() and result["data"] is not None:
        if "rateLimit" in result["data"]:
            cost = result["data"]["rateLimit"]["cost"]
            last_request_limit = result["data"]["rateLimit"]["remaining"]
            next_reset_time = dp.parse(result["data"]["rateLimit"]["resetAt"])
            log(f"Used {cost} points; {last_request_limit} remaining")
            if last_request_limit < cost:
                # We're about to be rate-limited; STALL
                stall_until(next_reset_time)
                last_request_limit = 5000

            del result["data"]["rateLimit"]
        return result["data"]

    raise RuntimeError(result.get("errors", "Empty response"))


def followPagination(node, key, query, display):
    if key not in node:
        return

    get_more = node[key]["pageInfo"]["hasNextPage"]
    cursor = node[key]["pageInfo"]["endCursor"]
    while get_more:
        # Need to paginate
        query_variables = {"id": node["id"], "cursor": cursor}
        more = submit_query(query, query_variables, display)

        node[key]["nodes"] += more["node"][key]["nodes"]

        get_more = more["node"][key]["pageInfo"]["hasNextPage"]
        cursor = more["node"][key]["pageInfo"]["endCursor"]
    del node[key]["pageInfo"]


def collapse_single(thing, key, name):
    "Collapse something in the form of { x: nodes [ { $name: 'stuff' }] }"
    if key in thing:
        thing[key] = [item[name] for item in thing[key]["nodes"]]


def collapse(thing, key):
    "Collapse something in the form of { x: nodes [] }"
    if key in thing:
        thing[key] = thing[key]["nodes"]


def collapse_map(thing, key, name):
    """Collapse something in the form of { x: {$name: $value} } into {x: $value}

    Where the {$name:...} can be null instead."""
    if key in thing and thing[key] is not None:
        thing[key] = thing[key][name]


def eprint(*str, **kwargs):
    print(*str, file=sys.stderr, **kwargs)


def log(*str, **kwargs):
    if quiet:
        pass
    else:
        eprint(*str, **kwargs)


def getIssues(owner, repo, refFile, fields=gql_Issue_Fields, updateOld=False):
    issue_cursor = None
    get_more_issues = True

    while get_more_issues:
        if issue_cursor is None:
            # Initial issue fetch
            query = gql_AllIssues_First
            variables = {"owner": owner, "repo": repo}
            if not updateOld and refFile.lastSuccess:
                variables["filters"] = {"since": refFile.lastSuccess.isoformat()}
                query = gql_UpdatedIssues_First
        else:
            # Fetching more issues
            query = gql_AllIssues_Subsequent
            variables = {"owner": owner, "repo": repo, "cursor": issue_cursor}
            if refFile.lastSuccess and not updateOld:
                variables["filters"] = {"since": refFile.lastSuccess.isoformat()}
                query = gql_UpdatedIssues_Subsequent

        data = submit_query(query + fields, variables, "issues")

        # Iterate through the issues
        issues = data["repository"]["issues"]

        for issue in issues["nodes"]:
            number = issue["number"]

            if updateOld and number not in refFile.issues:
                continue

            # Are the comments on this issue complete?
            followPagination(
                issue,
                "comments",
                gql_Issue_Comments_Query,
                f"additional comments on issue #{number}",
            )

            # Collapse some nodes
            collapse_map(issue, "author", "login")
            collapse_single(issue, "labels", "name")
            collapse_single(issue, "assignees", "login")
            collapse(issue, "comments")
            for comment in issue.get("comments", []):
                collapse_map(comment, "author", "login")

            # Delete the old instance; add this instance
            if not updateOld and number in refFile.issues:
                del refFile.issues[number]

            if number in refFile.issues:
                refFile.issues[number].update(issue)
            else:
                refFile.issues[number] = issue

            refFile.canCopy = False

        get_more_issues = issues["pageInfo"]["hasNextPage"]
        issue_cursor = issues["pageInfo"]["endCursor"]


def getPRs(owner, repo, refFile, fields=gql_PullRequest_Fields, updateOld=False):
    issue_cursor = None
    get_more_issues = True

    # Since PRs can't be filtered by their update time, we retrieve
    # them in update-time order and cut off pagination once we're
    # older than the reference file.

    while get_more_issues:
        query = gql_AllPRs_Initial
        variables = {"owner": owner, "repo": repo}
        if issue_cursor is not None:
            query = gql_AllPRs_Subsequent
            variables["cursor"] = issue_cursor

        data = submit_query(query + fields, variables, "pull requests")

        # Iterate through the PRs
        prs = data["repository"]["pullRequests"]

        for pr in prs["nodes"]:
            number = pr["number"]

            # Since we can't filter, check if we already have this one.
            if not updateOld:
                if number in refFile.prs:
                    ref_updatedAt = dp.parse(refFile.prs[number]["updatedAt"])
                    dl_updatedAt = dp.parse(pr["updatedAt"])
                    if ref_updatedAt >= dl_updatedAt:
                        continue
            elif number not in refFile.prs:
                continue

            # Issues only have comments; PRs have both comments and reviews,
            # and reviews themselves have comments.
            followPagination(
                pr,
                "comments",
                gql_PR_Comments_Query,
                f"additional comments on PR#{number}",
            )
            followPagination(
                pr, "reviews", gql_PR_Review_Query, f"additional reviews on PR#{number}"
            )

            for review in pr.get("reviews", {}).get("nodes", {}):
                followPagination(
                    review,
                    "comments",
                    gql_PR_ReviewComments_Query,
                    f"additional review comments on PR#{number}",
                )

            # Collapse some nodes
            collapse_map(pr, "author", "login")
            collapse_map(pr, "mergedBy", "login")
            collapse_single(pr, "labels", "name")
            collapse_map(pr, "baseRepository", "nameWithOwner")
            collapse_map(pr, "headRepository", "nameWithOwner")
            collapse_single(pr, "assignees", "login")
            collapse(pr, "comments")
            for comment in pr.get("comments", []):
                collapse_map(comment, "author", "login")
            collapse(pr, "reviews")
            for review in pr.get("reviews", []):
                collapse_map(review, "author", "login")
                collapse(review, "comments")

            # Delete the old instance; add this instance
            if not updateOld and number in refFile.prs.keys():
                del refFile.prs[number]

            if number in refFile.prs.keys():
                refFile.prs[number].update(pr)
            else:
                refFile.prs[number] = pr
            refFile.canCopy = False

        get_more_issues = prs["pageInfo"]["hasNextPage"]
        issue_cursor = prs["pageInfo"]["endCursor"]

        # Stop paginating if we've caught up to the last download
        if not updateOld and prs["nodes"] and refFile.lastSuccess:
            oldestRetrieved = dp.parse(prs["nodes"][-1]["updatedAt"])
            if oldestRetrieved < refFile.lastSuccess:
                get_more_issues = False


def upgradeReference(reference):
    try:
        while archive_reference.is_legacy_magic(reference.magic):
            instructions = archive_reference.get_upgrade_instructions(reference.magic)
            if instructions.issues:
                getIssues(reference, instructions.issues, True)
            if instructions.prs:
                getPRs(reference, instructions.prs, True)
            reference.magic = instructions.result
    except:
        pass

    if not archive_reference.is_current_magic(reference.magic):
        warnings.warn(
            "Unable to upgrade input file to current version; proceeding without it"
        )
        return archive_reference.newReferenceFile()

    return reference


#####################
## Body of program ##
#####################

s = requests.Session()
quiet = False


def do_archive(full_repo, token, refFile, outFile=None, issuesOnly=False):
    API_headers = {
        "user-agent": "mikebishop/archive-repo/archive.py",
        "authorization": "bearer " + token,
    }

    s.headers.update(API_headers)

    now = datetime.now(timezone.utc)

    (owner, repo) = full_repo.split("/", 1)

    ## Read in the reference files, if any
    reference = upgradeReference(archive_reference.loadReference(refFile, full_repo))
    reference.canCopy = bool(reference.issues) and bool(reference.prs or issuesOnly)

    ## Download from GitHub the full issues list (if no reference) or the updated issues list (if reference)
    getIssues(owner, repo, reference)

    ## Similar process with PRs, except they don't have a filter
    if not issuesOnly:
        getPRs(owner, repo, reference)

    # Fetch the Labels fresh each time
    labels_ref = list()
    issue_cursor = None
    get_more_issues = True
    while get_more_issues:
        query = gql_Labels_Query
        variables = {"owner": owner, "repo": repo}
        if issue_cursor is not None:
            query = gql_MoreLabels_Query
            variables["cursor"] = issue_cursor

        labels = submit_query(query, variables, "labels")
        labels_ref += labels["repository"]["labels"]["nodes"]

        get_more_issues = labels["repository"]["labels"]["pageInfo"]["hasNextPage"]
        issue_cursor = labels["repository"]["labels"]["pageInfo"]["endCursor"]

    ## Ready to output

    ## Pick up everything in the reference if nothing new was downloaded
    if reference.canCopy and outFile:
        shutil.copyfile(refFile, outFile)
    else:
        output = {
            "magic": archive_reference.get_current_magic(),
            "timestamp": now.isoformat(),
            "repo": full_repo,
            "labels": labels_ref,
            "issues": [issue for (id, issue) in sorted(reference.issues.items())],
        }
        if not issuesOnly:
            output["pulls"] = [pr for (id, pr) in sorted(reference.prs.items())]

        if outFile:
            with open(outFile, "w") as output_file:
                json.dump(output, output_file, indent=2)
        else:
            json.dump(output, sys.stdout, indent=2)


if __name__ == "__main__":
    init(sys.argv)
