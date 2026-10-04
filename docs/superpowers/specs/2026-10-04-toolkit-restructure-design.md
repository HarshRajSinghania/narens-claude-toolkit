# narens-claude-toolkit: restructure design

Date: 2026-10-04

## Purpose

Rebrand the repo from `narens-claude-skills` to `narens-claude-toolkit` and make its tooling understand three kinds of things it will hold: skills, mods (Claude Code plugins whose behavior is a hooks module) and MCP servers. No mod or server is built in this change; this is the rename plus the structure and tooling that can hold them.

## Success criteria

- The repo, marketplace, install commands and docs say `narens-claude-toolkit`; the five existing skills still install under the new marketplace name.
- `validate.py` and `build_catalog.py` accept skills, mods and servers, and fail with a clear message on a malformed one.
- The README and `llms.txt` catalog have three sections, with a "Coming soon" line for an empty one.
- One honest migration note tells existing users how to move.

## Decisions already made

- **Rename style (option 2, rename with a bridge):** the marketplace name changes outright; the old name is not kept alive anywhere. A migration note in the README and CHANGELOG is the only bridge.
- **Scope (option 1):** rename plus type-aware tooling and conventions. No scaffold scripts or templates for mods or servers until the first one exists.
- **Layout:** skills and mods are both plugins and live in `plugins/<name>/`. MCP servers live in `servers/<name>/`. They are not plugins and are not listed in `marketplace.json`.
- **Type detection is by contents**, never by a declared field. An unknown field in `plugin.json` risks Claude Code refusing the manifest.
- **History is not rewritten:** everything under `docs/superpowers/` keeps its original wording.

## Constraints and assumptions

- Python 3.9+ standard library only for the repo tooling; LF line endings; the repo's existing test style (`unittest`, helpers in `tests/helpers.py`).
- GitHub redirects the old web and git URLs after a repo rename. Plugin and skill names, issue numbers and labels, and git history are unchanged.
- The exact Claude Code commands for removing a marketplace must be confirmed against current docs before the migration note is published. Until then the note names the sequence (remove the old marketplace, add the new one, reinstall each plugin with the new suffix) without quoting syntax that has not been checked.
- `assets/social-preview.png` is a binary export of the SVG. It cannot be regenerated here, so it stays stale until it is re-exported by hand.
- Renaming the GitHub repo and editing its description and topics are outward-facing and happen last, only after explicit confirmation.

## Rename: what changes

- `scripts/common.py`: `MARKETPLACE` and `REPO_URL` become `narens-claude-toolkit` (the repo name equals the marketplace name, as now). `OWNER_NAME` and `GITHUB_USER` are unchanged.
- `.claude-plugin/marketplace.json`: `name` and `metadata.description`.
- Every plugin's `.claude-plugin/plugin.json`: `homepage` and `repository`; the template's too.
- Generated files: the README catalog install lines and `llms.txt` (regenerated, never hand-edited).
- Hand-edited docs: `README.md` (title, badges, intro, install, migration block), `CONTRIBUTING.md`, `docs/conventions.md`, `docs/launch-checklist.md`, each plugin README's install lines, `template/README.md`.
- `assets/banner.svg` and `assets/social-preview.svg`: the text is re-lettered.
- `CHANGELOG.md`: a `### Changed` entry under Unreleased naming the rename and the migration steps.
- Tests that hard-code the name are updated.
- Not touched: `docs/superpowers/**`, plugin and skill names, folder paths under `plugins/`.

## Structure and tooling

### Layout

```
plugins/<name>/     skills and mods (both are plugins)
servers/<name>/     MCP servers: README.md plus one package manifest
template/           the skill template (unchanged)
```

### Type detection

`common.plugin_kinds(pdir)` returns the set of kinds a plugin has:

- `skill` when `skills/` contains at least one directory (so a directory missing its `SKILL.md` is reported with that specific error);
- `mod` when `hooks/hooks.json` exists.

A plugin may be both. A plugin with neither is an error: `needs skills/ or hooks/hooks.json`. This replaces today's "needs at least one skill directory".

### Validator (`validate.py`)

- Plugin checks (name equals directory, `version`, `description`, author `Naren`, README present) are unchanged, as are the skill checks for any plugin with `skills/`.
- A plugin with `hooks/hooks.json` gets mod checks: the file is valid JSON; `modules` is a non-empty list of non-empty strings; each listed path, resolved relative to `hooks/`, exists as a file. A failure names the plugin, the file and the problem.
- `servers/<name>/` checks: the name is kebab-case; `README.md` exists; at least one of `package.json` or `pyproject.toml` exists; the README has a first `> ` line (the description source).
- `marketplace.json` checks are unchanged: every plugin in `plugins/` is listed, no entry is missing a directory. Servers are not listed and not required to be.

### Catalog (`build_catalog.py`)

- One generated block between the existing `CATALOG` markers, containing three subsections in this order: `### Skills`, `### Mods`, `### MCP servers`. The hand-written `## Skills` heading above the marker in the README becomes `## What is inside`.
- Skills and mods are tables with the existing columns (name linking to the plugin README, description, install command). A plugin that is both appears in both. Servers are a table with name (linking to the server README), description (first `> ` line of the README) and a link to the folder; there is no install command until a server has a plugin wrapper.
- An empty section prints `_Coming soon._` instead of an empty table.
- `llms.txt` mirrors the same three sections.
- `--check` fails on a stale README or `llms.txt` exactly as today.

### CI

`validate.yml` is unchanged: it already runs the unit tests and `validate.py`. Per-type jobs (for example building a server) are added with the first server.

### Docs

- `docs/conventions.md` describes all three types, the layout, and the detection rules.
- `CONTRIBUTING.md` gains "Adding a skill", "Adding a mod" and "Adding an MCP server", the last two stating what the validator requires and that there is no scaffold yet.
- `new_skill.py` is unchanged and stays skills-only.

## Migration note

The README block "Moving from narens-claude-skills" and the CHANGELOG entry say:

1. Existing installs of any plugin from `@narens-claude-skills` must be re-added once.
2. The steps: remove the old marketplace, add `NarenDawar/narens-claude-toolkit`, reinstall each plugin with `@narens-claude-toolkit`.
3. Plugin names, versions and behavior are unchanged.

The exact command syntax in step 2 is verified against current Claude Code docs before this text is committed.

## Testing

Written first, in the repo's `unittest` style:

- Type detection: skill only, mod only, both, neither (error).
- Mod validation: missing `hooks.json` file contents, invalid JSON, `modules` not a list of strings, a `modules` path that does not exist, and a valid mod passing.
- Server validation: missing README, no manifest, a bad name, a README with no `> ` line, and a valid server passing.
- Catalog: three sections in order, "Coming soon" for each empty one, a plugin that is both appearing twice, server rows built from the README, and `--check` failing when stale.
- Existing tests are updated for the new name; the existing five plugins still validate.
- Temporary fixture plugins and servers inside the tests prove the new paths. No real mod or server is added to the repo.

## Order of work and the outward-facing steps

1. All repo changes on a branch, test-first, with the suite and `validate.py` green.
2. Final review of the branch.
3. Merge to `main` locally. Nothing is pushed or renamed without explicit confirmation.
4. With explicit confirmation, rename first and then push, so the new README badge and links resolve the moment they are public: `gh repo rename narens-claude-toolkit`, update the local `origin`, push `main`, and update the repo description and topics (adding mod and MCP topics). Re-export `social-preview.png` by hand and upload it.
5. Verify in Claude Code that `/plugin marketplace add NarenDawar/narens-claude-toolkit` loads and one plugin installs.

## Out of scope

- Building any mod or MCP server.
- Scaffold scripts or templates for mods or servers.
- A plugin wrapper that bundles a server's MCP config.
- Per-type CI jobs.
- Rewriting `docs/superpowers/**`.
- Keeping the old marketplace name alive.
