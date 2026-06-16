# Changelog

## [0.1.1](https://github.com/duyet/claude-agent-runner/compare/v0.1.0...v0.1.1) (2026-06-16)


### Bug Fixes

* add skills directory to fix Docker build ([e15a846](https://github.com/duyet/claude-agent-runner/commit/e15a84608999c84168912ba98563ce6178f09d51))
* keep dynamic IMAGE_NAME in workflows ([a4a8466](https://github.com/duyet/claude-agent-runner/commit/a4a84668e6f6c06f3d63ad0f5213ad2f8e1debe9))


### Refactoring

* cleanup app code - remove hardcoded duyetbot, add AnyRouter/cloud auth ([31c248c](https://github.com/duyet/claude-agent-runner/commit/31c248cdcf6fcfc418b20df8964544a2cecff03c))
* forward env vars by prefix, add CLI args --model/--max-turns/--append-system-prompt ([e9c3afc](https://github.com/duyet/claude-agent-runner/commit/e9c3afcae7dc9d5de273f59453605542dfa1ff28))
* make all config env-driven, add API key auth, custom webhooks, MCP/skills support ([1fdf802](https://github.com/duyet/claude-agent-runner/commit/1fdf8027c1a2f62a7e7d603becb4a3aa93c08041))
* simplify to SDK-driven agent ([f708ea8](https://github.com/duyet/claude-agent-runner/commit/f708ea8ec53107a8ae28f809f16d752171dd30a4))
