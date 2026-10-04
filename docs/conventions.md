# Conventions

## Layout

Three kinds of things live here, told apart by their contents (`plugin.json` has no type field):

- **Skill:** a plugin in `plugins/<name>/` with `skills/<name>/SKILL.md` (plus optional `references/` and `scripts/`).
- **Mod:** a plugin in `plugins/<name>/` whose behavior is a hooks module: `hooks/hooks.json` with a non-empty `modules` list of file paths (relative to `hooks/`) that exist.
- **MCP server:** a folder `servers/<name>/` with a `README.md` whose first `> ` line is its one-line description, and a `package.json` or `pyproject.toml`. Servers are not plugins and are not listed in `.claude-plugin/marketplace.json`.

A plugin can be a skill and a mod at once; it then appears in both catalog sections. Every plugin has `.claude-plugin/plugin.json` and a `README.md`, and needs `skills/` or `hooks/hooks.json`.

## Naming

Plugin, skill and server names are kebab-case, and a skill's directory name equals the `name` in its `SKILL.md` frontmatter.

## SKILL.md

- Frontmatter requires `name` and `description`.
- The description is a single line that starts with `Use when` and describes the triggering situation, not the workflow. It is what Claude and search engines see first.
- No branding footer; branding lives in READMEs and metadata so it costs no tokens when the skill loads.

## Metadata

`plugin.json` and `marketplace.json` set the author/owner to `Naren`. `plugin.json` also needs `version` and `description`.

## Per-plugin README

Keyword-rich H1 ("<name>: a Claude Code skill by Naren"), a "When it triggers" section, install commands, and a before/after example. A server README's first `> ` line is its description in the catalog.

## Generated files

The README catalog (skills, mods, MCP servers) and `llms.txt` come from `python scripts/build_catalog.py`. `python scripts/validate.py` fails if they are stale.
