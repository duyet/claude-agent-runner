# Changelog

## [0.1.1](https://github.com/duyet/claude-agent-runner/compare/v0.1.0...v0.1.1) (2026-06-17)


### Features

* add issues.opened trigger with ISSUE_LABEL support ([744b417](https://github.com/duyet/claude-agent-runner/commit/744b417d4ac60e03fc26df325fd658f76686a300))
* **agent-runner:** add comprehensive state management system ([bfb55ef](https://github.com/duyet/claude-agent-runner/commit/bfb55ef07a86b52d7435352ddebf91eadbeed1ad))
* **agent:** post fallback diagnostic comment when run takes no action ([1d2483f](https://github.com/duyet/claude-agent-runner/commit/1d2483f2f66f3bae3565513dba8ab6f1081dc0bf))
* AnyRouter gateway, LRU cache, pull mode improvements ([8d07d8f](https://github.com/duyet/claude-agent-runner/commit/8d07d8f088b1261f0dcbf92d498cbb5e1afb59f1))
* **poller:** add detailed per-cycle and per-repo logging ([6e4594f](https://github.com/duyet/claude-agent-runner/commit/6e4594ff3bd3c3a5be1f2d374648bc5788e3af03))
* **poller:** add pull mode for homelab deployments without public endpoints ([056422f](https://github.com/duyet/claude-agent-runner/commit/056422fea9879d19405797b4976e2078fcfe1223))


### Bug Fixes

* add skills directory to fix Docker build ([40bd0b6](https://github.com/duyet/claude-agent-runner/commit/40bd0b6338d8f73c52091c52197936c8f4d747b7))
* **agent:** add message content logging and smart prompt routing ([23ab381](https://github.com/duyet/claude-agent-runner/commit/23ab381b8a56dab1091db60bbb822d0741bee916))
* **agent:** always comment on the issue, PR only when code changes ([4769577](https://github.com/duyet/claude-agent-runner/commit/4769577015c9088518d019c71dc7731b5b607b6b))
* **Dockerfile:** install deps from pyproject.toml instead of hardcoded list ([52d1c4f](https://github.com/duyet/claude-agent-runner/commit/52d1c4fa58aa11d6783aef9bdfc5a660654d3633))
* **Dockerfile:** switch to pip install . (non-editable) + disable build provenance ([25b1dc5](https://github.com/duyet/claude-agent-runner/commit/25b1dc5836f76af99fb8ae3206c342b7f6b36a15))
* **k8shelper:** match default SA/secret names to deployed manifest ([70a31de](https://github.com/duyet/claude-agent-runner/commit/70a31dee29c99c20905facd2639dcc9bc047f143))
* **k8shelper:** override state path in agent pods to use /tmp ([98f5bae](https://github.com/duyet/claude-agent-runner/commit/98f5bae7f374bf629a307526474f799d511634e7))
* keep dynamic IMAGE_NAME in workflows ([9125d5c](https://github.com/duyet/claude-agent-runner/commit/9125d5c4346e5b1e52d363d81fa82e17a4530e0d))
* **poller:** iss must be str for PyJWT, list_runs is sync not async ([d383de8](https://github.com/duyet/claude-agent-runner/commit/d383de8242aa95e2e1185696b7e4eeb6c6129307))
* **poller:** lazy initialize StateManager to avoid read-only filesystem error ([9d08d7e](https://github.com/duyet/claude-agent-runner/commit/9d08d7e068e6ecdbbfaee7e544d1e33623077724))
* **poller:** pass datetime object to get_issues(since=), fix get_pulls() since ([62430dd](https://github.com/duyet/claude-agent-runner/commit/62430dd52a0009c8a58b09a1a4b8c756104b37c8))
* **poller:** pass repo to _process_new_issue, use core rate limit ([bda2b0f](https://github.com/duyet/claude-agent-runner/commit/bda2b0f4ec5e36cb3bab7e3bcc2d6f2ca5bab340))
* **poller:** persist processed items so dedup survives restarts ([75901ae](https://github.com/duyet/claude-agent-runner/commit/75901ae8c5bbe433d6b3bfe4a044b9db806d6a8b))
* **poller:** refresh GitHub App installation token before each poll ([e8583d9](https://github.com/duyet/claude-agent-runner/commit/e8583d9909c1f888f5bf21ad7434b71291968d5b))
* **poller:** use GithubIntegration directly for JWT, not manual jwt.encode ([c3d4aac](https://github.com/duyet/claude-agent-runner/commit/c3d4aacfcb0c5a90069817d1091095a6bfffa821))
* **receiver:** add /api/v1 prefix to webhook routes for ingress compatibility ([0da2498](https://github.com/duyet/claude-agent-runner/commit/0da2498ce4b87793650b2b45436e2154b567f05b))
* **release-please:** remove manifest-file — version read from pyproject.toml ([02aa6fe](https://github.com/duyet/claude-agent-runner/commit/02aa6fe83784aad5227e7637b44554ed1c92eee8))
* **release-please:** restore manifest file — required by release-please-action@v4 ([da6ab74](https://github.com/duyet/claude-agent-runner/commit/da6ab74f46f1a3f3c7c588fa07f3439776eaad1d))


### Refactoring

* cleanup app code - remove hardcoded duyetbot, add AnyRouter/cloud auth ([ad50d13](https://github.com/duyet/claude-agent-runner/commit/ad50d138fc7e40bf485fde03cc78c00e8690725b))
* configure logging once, add poller token-rotation tests ([23b8d7b](https://github.com/duyet/claude-agent-runner/commit/23b8d7ba21a219384c86a832749622f1570cb19c))
* embed system prompt in code, enable auto mode, add skills/plugins via env ([f9f49b8](https://github.com/duyet/claude-agent-runner/commit/f9f49b8b5a3b37c65162da8e16b25ff6727f2cd2))
* forward env vars by prefix, add CLI args --model/--max-turns/--append-system-prompt ([9e2d608](https://github.com/duyet/claude-agent-runner/commit/9e2d6087723d5eb01ea58469404fe5481c981aaf))
* make all config env-driven, add API key auth, custom webhooks, MCP/skills support ([9173ef0](https://github.com/duyet/claude-agent-runner/commit/9173ef0a7322e1a96fb9498c84a658b4d6105a10))
* migrate from pip/requirements.txt to uv/pyproject.toml ([64009af](https://github.com/duyet/claude-agent-runner/commit/64009af9ccb85e5bf983b2a00892558be2892a59))
* **poller:** use PyGithub SDK and listen to all new issues ([06de4d3](https://github.com/duyet/claude-agent-runner/commit/06de4d34ed9b7421ca4fb39a074646f8a573206d))
* simplify to SDK-driven agent ([e94b63a](https://github.com/duyet/claude-agent-runner/commit/e94b63a5d45d8f3da21c30620ce80eea298548ad))
