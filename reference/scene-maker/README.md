# Scene-maker source snapshot

This directory records the source of the frozen checker. The verbatim Python snapshot is [`tools/check_repository_policy.py`](../../tools/check_repository_policy.py), because characterization CLI fixtures preserve its original repository-root calculation.

The source commit is `9e792124bc61f55150416b8bf803862c6c634c78`. `SOURCE.json` records source paths and blob hashes. Do not edit the Python snapshot; it is retained only for source characterization and paired compatibility checks.

The scene-maker policy JSON is not copied verbatim because it contains a large project-specific migration inventory. [`tests/fixtures/seed/clean-policy.json`](../../tests/fixtures/seed/clean-policy.json) contains adapted clean defaults for oracle comparisons only. The authoritative repository policy is [`repo-context.toml`](../../repo-context.toml).
