# Conventions

## Layout

One plugin per skill: `plugins/<name>/` containing `.claude-plugin/plugin.json`, `README.md`, and `skills/<name>/SKILL.md` (plus optional `references/` and `scripts/`).

## Naming

Plugin and skill names are kebab-case, and the skill directory name equals the `name` in `SKILL.md` frontmatter.

## SKILL.md

- Frontmatter requires `name` and `description`.
- The description is a single line that starts with `Use when` and describes the triggering situation, not the workflow. It is what Claude and search engines see first.
- No branding footer; branding lives in READMEs and metadata so it costs no tokens when the skill loads.

## Metadata

`plugin.json` and `marketplace.json` set the author/owner to `Naren`. `plugin.json` also needs `version` and `description`.

## Per-skill README

Keyword-rich H1 ("<name>: a Claude Code skill by Naren"), a "When it triggers" section, install commands, and a before/after example.

## Generated files

The README skill table and `llms.txt` come from `python scripts/build_catalog.py`. `python scripts/validate.py` fails if they are stale.
