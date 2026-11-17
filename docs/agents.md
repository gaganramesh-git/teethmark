# Using Teethmark with your agent

Teethmark has four ways in. Use the one your agent supports; they all run the same check.

| You want | Use |
|---|---|
| The agent follows the rule on its own | An always-on rules file (below) |
| The agent can call Teethmark as a tool | The MCP server |
| The agent loads it as a skill | `skills/teethmark/` |
| A hard stop, no agent cooperation needed | `teethmark gate` in a hook, pre-push or CI |

## 1. Rules files (every agent)

`AGENTS.md` is read by most agents. Run `teethmark init` in your project to add the rule block to it, or copy
the file for your agent from this repo:

| Agent | File |
|---|---|
| Any agent that reads `AGENTS.md` | `AGENTS.md` |
| Cursor | `.cursor/rules/teethmark.mdc` |
| Windsurf | `.windsurf/rules/teethmark.md` |
| Cline | `.clinerules/teethmark.md` |
| Kiro | `.kiro/steering/teethmark.md` |
| GitHub Copilot | `.github/copilot-instructions.md` |
| Others using `.agents/` | `.agents/rules/teethmark.md` |
| Gemini CLI | `gemini-extension.json` (loads `AGENTS.md`) |

All copies come from one source, `scripts/sync_rules.py`, and a test fails if they drift.

## 2. MCP server

Any agent that supports MCP servers over stdio can use these tools: `teethmark_check`, `teethmark_show`,
`teethmark_record`. Add this to the agent's MCP settings:

```json
{ "mcpServers": { "teethmark": { "command": "uvx", "args": ["teethmark", "mcp"] } } }
```

Until the package is on PyPI, use the repo directly:

```json
{ "mcpServers": { "teethmark": { "command": "uvx",
  "args": ["--from", "git+https://github.com/gaganramesh-git/teethmark", "teethmark", "mcp"] } } }
```

Safety: `teethmark_record` refuses to overwrite an existing ledger unless `confirm_rerecord` is set, because
re-recording is how a weakened suite would be accepted. Set `TEETHMARK_MCP_READONLY=1` in the server's
environment to remove that ability entirely.

## 3. Skill

Copy `skills/teethmark/` into your agent's skills folder. It carries a single-file build of the tool, so
nothing else needs installing.

Plugin manifests for Codex (`.codex-plugin/`), GitHub Copilot CLI (`.github/plugin/`), Kimi (`.kimi-plugin/`) and
the `.agents/plugins/` marketplace point at the same skill folder. These manifests follow the layout other
published plugins use but have not been exercised against each agent's installer yet.

## 4. A hard stop: `teethmark gate`

`teethmark gate` prints nothing and exits 0 when the tests did not get weaker. On a BLOCK it prints the proof to
stderr and exits 2, the "block" code most agent hook systems use. It exits 0 when there is no ledger or when it
cannot run (add `--strict` to fail closed).

Wire it wherever your agent offers a "before stop" or "before commit" hook:

- Git: `teethmark init --git-hook` installs a pre-push hook.
- CI: `teethmark init` writes a workflow that uses the GitHub Action with `baseline-ref` set to the base branch.
- Agent hooks: point the "stop" or "task finished" hook at `teethmark gate`. Hook formats differ per agent and
  are not shipped here because they have not been tested against each one.

## Keep the baseline out of the agent's reach

An agent that can rewrite the ledger can accept its own weakening. In CI, read the ledger from the base branch
(`--baseline-ref origin/main`, which the generated workflow does). Locally, set `TEETHMARK_KEY` so the ledger is
sealed with a keyed hash the agent does not hold.
