# TODO

## Open issues

- [ ] #10 Dependency Dashboard
- [ ] #1 Review SQL security

## Gaps

- [ ] Two near-duplicate CI surfaces: shared `build-tests.yml` (gh-automations) plus repo-local `tests.yml` run the same suite — consolidate or document why both exist.
- [ ] `opm-check` / `skill-check` not present — acceptable, this is a `hivemind.database` plugin, not an OVOS/OPM plugin or skill, so those checks do not apply.
- [ ] No typecheck (mypy) configured; only ruff lint.
- [ ] Coverage gate is `min_coverage: 0` — effectively disabled despite a 787-line test file; consider raising once stable.

## Code TODOs

None found.
