Feature: PR Mapping to Branches

    Runs against a local git repo standing in for a PR's fork, and the same
    mock GraphQL API used by archive.feature - no network access required.

    Scenario: Branch Creation
        Given the known-good baseline output is available
        When the current script is called on the mock repo
        And pr-branches is executed against the local git fixture
        Then a branch named "pulls/102" pointing to the fixture's head commit is created
