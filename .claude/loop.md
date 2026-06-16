# Claude Agent Runner - Autonomous Maintenance Loop

## Purpose
Continuously improve the claude-agent-runner codebase by analyzing logs, identifying issues, and implementing fixes.

## Schedule
Runs every 30 minutes: `0,30 * * * *`

## Loop Instructions

On each iteration, perform these tasks in order:

1. **Log Analysis** (5 min)
   - Check recent GitHub Actions builds for failures
   - Analyze k8s pod logs for errors and warnings
   - Look for patterns: crashes, timeouts, API errors, rate limits
   - Identify recurring issues that need fixing

2. **Code Review** (10 min)
   - Review recent code changes in context of found issues
   - Check for potential bugs, race conditions, error handling gaps
   - Look for security vulnerabilities or edge cases
   - Identify areas needing improvement (performance, reliability, logging)

3. **Prioritization** (2 min)
   - Rank issues by severity and impact
   - P0: Crashes, data loss, security issues
   - P1: Functionality broken, performance degradation
   - P2: Improvements, optimizations, better error messages
   - P3: Nice-to-haves, documentation

4. **Implementation** (10 min)
   - Fix highest-priority issue that can be completed in remaining time
   - Add proper error handling and logging
   - Include tests for new functionality
   - Update documentation if behavior changes
   - Follow semantic commit format: `fix(area):`, `feat(area):`, `refactor(area):`

5. **Validation** (3 min)
   - Run linters and type checkers
   - Ensure all tests pass
   - Verify build succeeds
   - Check for regressions

6. **Documentation** (optional, if time permits)
   - Update README.md with new features or behavior changes
   - Document any new configuration options
   - Add examples for common use cases

## Focus Areas

### High Priority
- **Crash prevention**: Fix any crashes or unhandled exceptions
- **Reliability**: Improve error handling, retry logic, timeout handling
- **Performance**: Optimize slow operations, reduce resource usage
- **Security**: Fix any security issues, improve input validation

### Medium Priority
- **Logging**: Add structured logging for debugging
- **Monitoring**: Improve observability and metrics
- **Testing**: Add tests for uncovered edge cases
- **Documentation**: Improve code comments and README

### Low Priority
- **Code quality**: Refactor for clarity, reduce duplication
- **Features**: Add helpful new features
- **Developer experience**: Improve setup, tooling

## Success Criteria

Each iteration should:
- Fix at least one P0 or P1 issue if any exist
- Not introduce new crashes or regressions
- Improve code quality or reliability
- Leave the codebase better than it was found

## Exit Conditions

Stop the loop if:
- No issues found for 3 consecutive iterations
- All P0 and P1 issues are resolved
- Current iteration completed successfully

## Notes

- Always commit with semantic messages
- Never commit secrets or sensitive data
- Test changes before committing
- If unsure about a change, document it in comments
- Keep iterations focused - one major fix per cycle
