# Changelog

## 0.2.0

- Bare `teethmark` does the right thing: records a quick first ledger, then checks on every later run.
- `--fast` (one planted bug per function) and `--budget SECONDS` for a first recording in minutes, not tens of minutes.
- `teethmark gate`: quiet pass/block for hooks, pre-push and CI (exit 2 only on a real BLOCK, fails open on errors).
- `teethmark init`: writes the CI workflow, the agent rules and, optionally, a pre-push hook. Safe to re-run.
- `teethmark mcp` / `teethmark-mcp`: an MCP server (check, show, record). Record refuses to overwrite a ledger
  without an explicit flag and can be disabled with `TEETHMARK_MCP_READONLY=1`.
- Always-on rule files and manifests for Codex, Copilot, Cursor, Windsurf, Cline, Kiro, Gemini, Kimi and any agent that
  reads `AGENTS.md`.
- A test that hollows a test out with an always-true assertion now needs REVIEW.
- Relative `--python` paths now work.
- Each planted bug runs in a pristine copy, so tests that write files cannot leak state between bugs.

## 0.1.0

First release: `record`, `check`, `show`, the skill, and the GitHub Action.
