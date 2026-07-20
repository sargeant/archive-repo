"""A minimal fake of GitHub's GraphQL API, used so the behave tests never
touch the network or a real repository.

Only handles the shapes of query this tool actually sends: it dispatches on
a few tell-tale substrings in the query text rather than parsing GraphQL, and
always returns full node objects regardless of which fields were technically
selected - the tool only reads keys it recognizes, so this is harmless and
keeps the fake trivial to maintain.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import dateutil.parser as dp

REPO = "mockorg/mockrepo"

LABELS = [
    {"name": "bug", "description": None, "color": "fc2929"},
    {"name": "enhancement", "description": None, "color": "84b6eb"},
]

ISSUES = [
    {
        "number": 1,
        "id": "issue-1",
        "title": "First issue",
        "url": "https://example.invalid/mockorg/mockrepo/issues/1",
        "state": "CLOSED",
        "author": {"login": "alice"},
        "authorAssociation": "OWNER",
        "assignees": {"nodes": []},
        "labels": {"nodes": []},
        "body": "First issue",
        "createdAt": "2020-01-01T00:00:00Z",
        "updatedAt": "2020-01-02T00:00:00Z",
        "closedAt": "2020-01-02T00:00:00Z",
        "comments": {
            "nodes": [
                {
                    "author": {"login": "bob"},
                    "authorAssociation": "CONTRIBUTOR",
                    "body": "Fixed.",
                    "createdAt": "2020-01-02T00:00:00Z",
                    "updatedAt": "2020-01-02T00:00:00Z",
                }
            ],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        },
    },
    {
        "number": 2,
        "id": "issue-2",
        "title": "Second issue",
        "url": "https://example.invalid/mockorg/mockrepo/issues/2",
        "state": "OPEN",
        "author": {"login": "bob"},
        "authorAssociation": "CONTRIBUTOR",
        "assignees": {"nodes": [{"login": "alice"}]},
        "labels": {"nodes": [{"name": "bug"}]},
        "body": "Second issue",
        "createdAt": "2020-01-03T00:00:00Z",
        "updatedAt": "2020-01-04T00:00:00Z",
        "closedAt": None,
        "comments": {
            "nodes": [],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        },
    },
    {
        "number": 3,
        "id": "issue-3",
        "title": "Third issue",
        "url": "https://example.invalid/mockorg/mockrepo/issues/3",
        "state": "CLOSED",
        "author": {"login": "alice"},
        "authorAssociation": "OWNER",
        "assignees": {"nodes": []},
        "labels": {"nodes": [{"name": "enhancement"}]},
        "body": "Third issue",
        "createdAt": "2020-01-05T00:00:00Z",
        "updatedAt": "2020-01-06T00:00:00Z",
        "closedAt": "2020-01-06T00:00:00Z",
        "comments": {
            "nodes": [],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        },
    },
    {
        # Added after STALE_SINCE, to exercise incremental "since" fetches.
        "number": 4,
        "id": "issue-4",
        "title": "Fourth issue",
        "url": "https://example.invalid/mockorg/mockrepo/issues/4",
        "state": "OPEN",
        "author": {"login": "carol"},
        "authorAssociation": "CONTRIBUTOR",
        "assignees": {"nodes": []},
        "labels": {"nodes": []},
        "body": "Fourth issue, added later",
        "createdAt": "2020-02-01T00:00:00Z",
        "updatedAt": "2020-02-01T00:00:00Z",
        "closedAt": None,
        "comments": {
            "nodes": [],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        },
    },
]

# The timestamp a "stale" reference file is captured at: after PR 101/issues
# 1-3 but before issue 4 / PR 102, so incremental fetches have something to do.
STALE_SINCE = "2020-01-15T00:00:00+00:00"

PR_101 = {
    "number": 101,
    "id": "pr-101",
    "title": "Merged change",
    "url": "https://example.invalid/mockorg/mockrepo/pull/101",
    "state": "MERGED",
    "author": {"login": "dave"},
    "authorAssociation": "CONTRIBUTOR",
    "assignees": {"nodes": []},
    "labels": {"nodes": []},
    "body": "A merged pull request.",
    "createdAt": "2020-01-10T00:00:00Z",
    "updatedAt": "2020-01-11T00:00:00Z",
    "baseRepository": {"nameWithOwner": REPO},
    "baseRefName": "master",
    "baseRefOid": "1111111111111111111111111111111111111111",
    "headRepository": {"nameWithOwner": "dave/mockrepo"},
    "headRefName": "feature",
    "headRefOid": "2222222222222222222222222222222222222222",
    "closedAt": "2020-01-11T00:00:00Z",
    "mergedAt": "2020-01-11T00:00:00Z",
    "mergedBy": {"login": "alice"},
    "mergeCommit": {"oid": "3333333333333333333333333333333333333333"},
    "comments": {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}},
    "reviews": {
        "nodes": [
            {
                "id": "review-1",
                "commit": {"abbreviatedOid": "2222222"},
                "author": {"login": "alice"},
                "authorAssociation": "OWNER",
                "state": "APPROVED",
                "body": "Looks good.",
                "createdAt": "2020-01-10T12:00:00Z",
                "updatedAt": "2020-01-10T12:00:00Z",
                "comments": {
                    "nodes": [],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                },
            }
        ],
        "pageInfo": {"hasNextPage": False, "endCursor": None},
    },
}

# Fields carried by the legacy PR schema, before baseRepository/baseRefOid/
# headRepository/headRefOid/mergeCommit etc. existed.
LEGACY_PR_FIELDS = {
    "baseRepository",
    "baseRefName",
    "baseRefOid",
    "headRepository",
    "headRefName",
    "headRefOid",
    "mergeCommit",
}


def make_pr_102(head_ref_oid):
    "PR 102 is open and its headRefOid points at a real local git fixture commit."
    return {
        "number": 102,
        "id": "pr-102",
        "title": "Open change",
        "url": "https://example.invalid/mockorg/mockrepo/pull/102",
        "state": "OPEN",
        "author": {"login": "erin"},
        "authorAssociation": "CONTRIBUTOR",
        "assignees": {"nodes": []},
        "labels": {"nodes": []},
        "body": "An open pull request.",
        "createdAt": "2020-02-05T00:00:00Z",
        "updatedAt": "2020-02-05T00:00:00Z",
        "baseRepository": {"nameWithOwner": REPO},
        "baseRefName": "master",
        "baseRefOid": "1111111111111111111111111111111111111111",
        "headRepository": {"nameWithOwner": "erin/mockrepo"},
        "headRefName": "feature",
        "headRefOid": head_ref_oid,
        "closedAt": None,
        "mergedAt": None,
        "mergedBy": None,
        "mergeCommit": None,
        "comments": {
            "nodes": [],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        },
        "reviews": {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}},
    }


def strip_legacy_fields(pr):
    "Simulate how this PR looked before the schema gained the newer fields."
    return {k: v for k, v in pr.items() if k not in LEGACY_PR_FIELDS}


RATE_LIMIT = {"cost": 1, "remaining": 5000, "resetAt": "2099-01-01T00:00:00Z"}


class MockGitHubHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # keep test output quiet

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        query = body.get("query", "")
        variables = body.get("variables") or {}

        # "labels(first:100" (no space) is the top-level labels query;
        # "labels(first: 5" (with a space) is the ...labels fragment
        # embedded in every issue/PR query, so a plain "labels(" substring
        # check would misclassify those as label queries.
        if "labels(first:100" in query:
            data = {
                "repository": {
                    "labels": {
                        "nodes": self.server.dataset["labels"],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        elif "issues(" in query:
            issues = self.server.dataset["issues"]
            since = variables.get("filters", {}).get("since")
            if since:
                cutoff = dp.parse(since)
                issues = [i for i in issues if dp.parse(i["updatedAt"]) >= cutoff]
            data = {
                "repository": {
                    "issues": {
                        "nodes": issues,
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        elif "pullRequests(" in query:
            prs = sorted(
                self.server.dataset["prs"],
                key=lambda pr: pr["updatedAt"],
                reverse=True,
            )
            data = {
                "repository": {
                    "pullRequests": {
                        "nodes": prs,
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"errors": [{"message": "unrecognized query"}]}')
            return

        data["rateLimit"] = RATE_LIMIT
        payload = json.dumps({"data": data}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class MockGitHubServer:
    """Serves a fixed dataset over HTTP, standing in for the GitHub GraphQL API.

    head_ref_oid_102 lets the caller point PR 102 at a real commit in a local
    git fixture, so pr_branches.py can actually fetch it.
    """

    def __init__(self, head_ref_oid_102):
        legacy_pr_101 = strip_legacy_fields(PR_101)
        pr_102 = make_pr_102(head_ref_oid_102)
        legacy_pr_102 = strip_legacy_fields(pr_102)

        self.dataset = {
            "labels": LABELS,
            "issues": ISSUES,
            "prs": [PR_101, pr_102],
        }
        # Kept for fixture generation: what a legacy-format PR looked like.
        self.legacy_prs = {101: legacy_pr_101, 102: legacy_pr_102}

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), MockGitHubHandler)
        self._httpd.dataset = self.dataset
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def url(self):
        host, port = self._httpd.server_address
        return f"http://{host}:{port}/graphql"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc_info):
        self._httpd.shutdown()
        self._httpd.server_close()
