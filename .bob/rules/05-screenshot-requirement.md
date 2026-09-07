# Screenshot requirement

**Every step must end in evidence Alami can look at.**

Default: run the thing locally and include CLI output or a screenshot in the report.

Reach for a Playwright test only when a step lands a **significant UI surface**:
- The pipeline timeline view
- The player
- The upload screen in its final form

For those steps, the Playwright test:
- Drives the real UI (not mocks)
- Captures a screenshot to `docs/steps/NN-<name>.png`
- Is named in the report under "Test:"

Everywhere else: skip Playwright, say you skipped it, and show CLI output instead.
Do not run a Playwright test for a step that is purely backend.

**Run it locally before you report.** Do not hand Alami a step you haven't executed.
