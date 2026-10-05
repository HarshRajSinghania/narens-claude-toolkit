# Contributing

Thanks for helping improve Naren's Claude Toolkit. Bug reports and skill, mod and server ideas are welcome via issues.

## Adding a skill

```bash
python scripts/new_skill.py my-skill "Use when ..."
```

This copies `template/` into `plugins/my-skill/`, registers it in `.claude-plugin/marketplace.json`, and refreshes the README catalog. Then edit `SKILL.md` and the plugin `README.md`.

## Adding a mod

A mod is a plugin whose behavior is a hooks module. There is no scaffold script yet: copy the structure of an existing plugin (`.claude-plugin/plugin.json`, `README.md`) and add `hooks/hooks.json` with a `modules` list pointing at your module file, then list the plugin in `.claude-plugin/marketplace.json`. `python scripts/validate.py` checks that `hooks.json` is valid, names exactly one module, and that the module is a relative path inside the plugin that exists and has a suffix Claude Code loads. Run `claude plugin validate plugins/<name>` for the full check that the module loads.

## Adding an MCP server

Create `servers/<name>/` with a `README.md` (the first line starting with `> ` is the one-line description shown in the catalog) and a `package.json` or `pyproject.toml`. Servers are not plugins and are not listed in `marketplace.json`. Run `python scripts/build_catalog.py` to add it to the README and `llms.txt`.

## Before opening a PR

```bash
python -m unittest discover -s tests -v
python scripts/validate.py
```

CI runs the same two commands. Conventions are in [docs/conventions.md](docs/conventions.md). Never edit the README catalog by hand; run `python scripts/build_catalog.py`.

## Known issues and deferred work

Every skill gets a final review before it is merged. Anything the review finds that is small and not worth blocking the release becomes a GitHub issue labelled `deferred-minor` (plus the skill's name, and `good first issue` when it is a self-contained change), instead of living only in someone's notes. Look there first if you want to help: [open deferred minors](https://github.com/NarenDawar/narens-claude-toolkit/issues?q=is%3Aissue+is%3Aopen+label%3Adeferred-minor).

Each issue says what is wrong, where in the code, a failing scenario or evidence, and an idea for the fix. To pick one up, comment on it, then follow "Before opening a PR" above. Fixes start with a test that fails for the reason the issue describes.
