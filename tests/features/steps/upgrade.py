from behave import *
import importlib
import warnings

# The package directory is named "archive-repo", which isn't a valid
# identifier, so it can't be imported with a normal `import` statement.
archive = importlib.import_module("archive-repo.archive")
archive_reference = importlib.import_module("archive-repo.shared.archive_reference")

archive.quiet = True


@given('the legacy reference file "{path}" for "{repo}"')
def step_impl(context, path, repo):
    context.repo = repo
    context.reference = archive_reference.loadReference(path, repo)


@given("the GitHub API is stubbed to backfill the missing PR fields")
def step_impl(context):
    pr_numbers = list(context.reference.prs.keys())
    owner, name = context.repo.split("/", 1)

    def fake_submit_query(query, variables, display):
        assert variables["owner"] == owner and variables["repo"] == name
        nodes = [
            {
                "number": number,
                "updatedAt": "2016-10-31T23:36:06Z",
                "baseRepository": {"nameWithOwner": context.repo},
                "baseRefName": "master",
                "baseRefOid": "a" * 40,
                "headRepository": {"nameWithOwner": "someone/" + name},
                "headRefName": "feature",
                "headRefOid": "b" * 40,
                "mergeCommit": None,
            }
            for number in pr_numbers
        ]
        return {
            "repository": {
                "pullRequests": {
                    "nodes": nodes,
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }

    archive.submit_query = fake_submit_query


@given("the GitHub API is stubbed to fail")
def step_impl(context):
    def failing_submit_query(query, variables, display):
        raise RuntimeError("simulated API failure")

    archive.submit_query = failing_submit_query


@when("the reference file is upgraded")
def step_impl(context):
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        context.upgraded = archive.upgradeReference(context.reference)


@then("the reference magic is current")
def step_impl(context):
    assert context.upgraded.magic == archive_reference.get_current_magic()


@then("PR {number:d} has a baseRefOid")
def step_impl(context, number):
    pr = context.upgraded.prs[number]
    assert pr.get("baseRefOid"), pr


@then("PR {number:d} still has its original title")
def step_impl(context, number):
    pr = context.upgraded.prs[number]
    assert pr.get("title"), pr


@then("PR {number:d} still has its reviews")
def step_impl(context, number):
    pr = context.upgraded.prs[number]
    assert pr.get("reviews"), pr


@then("the reference has no issues or pull requests")
def step_impl(context):
    assert context.upgraded.issues == {}
    assert context.upgraded.prs == {}


@then('the reference still remembers its repo as "{repo}"')
def step_impl(context, repo):
    assert context.upgraded.repo == repo
