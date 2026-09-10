# Bootstrap source snapshot

This directory records the source of the frozen checker. The verbatim Python snapshot is [`tools/check_repository_policy.py`](../../tools/check_repository_policy.py), because characterization CLI fixtures preserve its original repository-root calculation.

`SOURCE.json` identifies the project-owned bootstrap snapshot and records source paths and blob hashes. Do not edit the Python snapshot; it is retained only for source characterization and paired compatibility checks.

The bootstrap policy JSON is not copied verbatim because it contains a large project-specific migration inventory. [`tests/fixtures/seed/clean-policy.json`](../../tests/fixtures/seed/clean-policy.json) contains adapted clean defaults for oracle comparisons only. The authoritative repository policy is [`repo-context.toml`](../../repo-context.toml).
