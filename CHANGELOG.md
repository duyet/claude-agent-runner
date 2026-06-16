# Changelog

## [0.1.1](https://github.com/duyet/claude-agent-runner/compare/v0.1.0...v0.1.1) (2026-06-16)


### Bug Fixes

* add skills directory to fix Docker build ([5372238](https://github.com/duyet/claude-agent-runner/commit/5372238c44ee68bb4850e9db17eb2cbd5d7baf6e))
* keep dynamic IMAGE_NAME in workflows ([23bbc4e](https://github.com/duyet/claude-agent-runner/commit/23bbc4eb8ec864d2c575ce534884326ed5001c55))


### Refactoring

* cleanup app code - remove hardcoded duyetbot, add AnyRouter/cloud auth ([31ae2c3](https://github.com/duyet/claude-agent-runner/commit/31ae2c3c3f90defa6aad50c31742425b78afabc0))
* forward env vars by prefix, add CLI args --model/--max-turns/--append-system-prompt ([e45babd](https://github.com/duyet/claude-agent-runner/commit/e45babd7c8331b0a278f1c4bc36e57021b1ba852))
* make all config env-driven, add API key auth, custom webhooks, MCP/skills support ([0febd13](https://github.com/duyet/claude-agent-runner/commit/0febd133af95664b1c500031548a19f8238794ca))
* simplify to SDK-driven agent ([9456357](https://github.com/duyet/claude-agent-runner/commit/94563577686ef410c420f10101bd19d6d3c6e547))
