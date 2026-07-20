from behave import *
import subprocess
import os
import json


def read_temp_file(context, name):
    filename = context.tempdir.name + "/" + name + ".json"
    with open(filename) as read:
        return json.load(read)


def run_archive(context, args, capture_output=False):
    command = [
        "python3",
        "-m",
        "archive-repo",
        "archive",
        context.repo,
        "fake-token",
    ] + args
    result = subprocess.run(command, capture_output=capture_output, text=capture_output)
    result.check_returncode()
    return result


@given("the known-good baseline output is available")
def step_impl(context):
    context.reference = "tests/content/mock_known_good.json"


@when("the current script is called on the mock repo")
def step_impl(context):
    filename = context.tempdir.name + "/current.json"
    if not os.path.exists(filename):
        run_archive(context, [filename])


# Checks that everything in first occurs in second, except for the top-level
# keys in exclude. If mutual is set, everything in second also occurs in
# first (i.e. the two are equivalent modulo the excluded keys).
def check_subset(first, second, exclude=[], mutual=False):
    if type(first) != type(second):
        return False

    elif isinstance(first, dict):
        if mutual and not check_subset(second.keys(), first.keys(), mutual=mutual):
            return False

        return all(
            key in second and check_subset(first[key], second[key], mutual=mutual)
            for key in first.keys()
            if key not in exclude
        )

    elif isinstance(first, list):
        if mutual and len(second) != len(first):
            return False
        return len(first) <= len(second) and all(
            check_subset(first[i], second[i], mutual=mutual) for i in range(len(first))
        )

    else:
        return first == second


@then("the output is a superset of the known-good baseline")
def step_impl(context):
    with open(context.reference) as f:
        known_good = json.load(f)
    # Everything in the frozen baseline must also appear in today's output,
    # except: timestamp always changes, and magic may too.
    assert check_subset(
        known_good,
        read_temp_file(context, "current"),
        exclude=["magic", "timestamp"],
    )


@given("the {ref_type} file is available")
def step_impl(context, ref_type):
    if ref_type == "Stale":
        context.reference = "tests/content/mock_stale.json"
    elif ref_type == "Legacy":
        context.reference = "tests/content/mock_legacy.json"
    elif ref_type == "Wrong repo":
        with open("tests/content/mock_stale.json") as f:
            data = json.load(f)
        data["repo"] = "someone-else/other-repo"
        context.reference = context.tempdir.name + "/wrong_repo.json"
        with open(context.reference, "w") as f:
            json.dump(data, f)
    elif ref_type == "Invalid magic":
        with open("tests/content/mock_legacy.json") as f:
            data = json.load(f)
        data["magic"] = "not-a-real-magic-value"
        context.reference = context.tempdir.name + "/invalid_magic.json"
        with open(context.reference, "w") as f:
            json.dump(data, f)


@when("the script is called on the mock repo with the reference file")
def step_impl(context):
    context.execute_steps("When the current script is called on the mock repo")
    assert os.path.exists(context.reference)
    result = run_archive(
        context, ["--reference", context.reference], capture_output=True
    )
    context.result = json.loads(result.stdout)
    context.output = result.stderr


@then("the output is the same")
def step_impl(context):
    assert check_subset(
        read_temp_file(context, "current"),
        context.result,
        exclude=["timestamp"],
        mutual=True,
    )


@then('the error "{error}" is found on stderr')
def step_impl(context, error):
    if error != "None":
        assert error in context.output
