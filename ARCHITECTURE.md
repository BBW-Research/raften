# Architecture

`repo-context` separates a reusable policy engine from repository-owned policy. The engine inventories Git-visible paths, classifies files, builds documentation and context graphs, compares the working tree with a base revision, and emits deterministic diagnostics. Each consuming repository owns its TOML policy, wrapper script, CI gate, and explicit exceptions.

The scene-maker checker in `tools/` is a frozen source fixture, not the production architecture. The standalone package lives under `src/repo_context/` and must not import repository-specific code or assume its own checkout layout.

See the [architecture documentation](docs/architecture/index.md) for module boundaries, dependency direction, and the policy model.
