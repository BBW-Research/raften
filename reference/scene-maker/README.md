# Scene-maker source snapshot

This directory records the source of the bootstrap checker. The active verbatim Python snapshot is [`tools/check_repository_policy.py`](../../tools/check_repository_policy.py), because its original repository-root calculation requires it to remain directly below the repository root.

The source commit is `9e792124bc61f55150416b8bf803862c6c634c78`. `SOURCE.json` records source paths and blob hashes. Do not edit the Python snapshot during the extraction phases. Replace it only after the standalone implementation passes the parity and self-hosting gates in the active plan.

The scene-maker policy JSON is not copied verbatim because it contains a large project-specific migration inventory. `config/repository_policy.v1.json` retains only the clean defaults needed to validate this starter repository.
