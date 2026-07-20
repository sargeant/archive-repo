Feature: Legacy reference file upgrades

    Upgrading a reference file written by an older schema version must not
    depend on the network or a live GitHub API. It re-fetches only the
    fields that were added since the file was written, for entries it
    already knows about, and merges them in place without disturbing
    anything else already in the file.

    If the upgrade can't complete for any reason, it must fall back to a
    blank reference (forcing a full re-download) rather than leave the
    reference in a partially-upgraded, ambiguous state.

    Scenario: A legacy PR gains the fields added since it was archived
        Given the legacy reference file "tests/content/h2c_legacy.json" for "MikeBishop/http2-certs"
        And the GitHub API is stubbed to backfill the missing PR fields
        When the reference file is upgraded
        Then the reference magic is current
        And PR 11 has a baseRefOid
        And PR 11 still has its original title
        And PR 11 still has its reviews

    Scenario: A failure during upgrade safely falls back to a blank reference
        Given the legacy reference file "tests/content/h2c_legacy.json" for "MikeBishop/http2-certs"
        And the GitHub API is stubbed to fail
        When the reference file is upgraded
        Then the reference magic is current
        And the reference has no issues or pull requests
        And the reference still remembers its repo as "MikeBishop/http2-certs"
