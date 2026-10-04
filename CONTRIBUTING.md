# Contributing

Thanks for helping improve Naren's Claude Toolkit. Bug reports and skill ideas are welcome via issues.

## Adding a skill

```bash
python scripts/new_skill.py my-skill "Use when ..."
```

This copies `template/` into `plugins/my-skill/`, registers it in `.claude-plugin/marketplace.json`, and refreshes the README catalog. Then edit `SKILL.md` and the plugin `README.md`.

## Before opening a PR

```bash
python -m unittest discover -s tests -v
python scripts/validate.py
```

CI runs the same two commands. Conventions are in [docs/conventions.md](docs/conventions.md). Never edit the README catalog by hand; run `python scripts/build_catalog.py`.

## Known issues and deferred work

Every skill gets a final review before it is merged. Anything the review finds that is small and not worth blocking the release becomes a GitHub issue labelled `deferred-minor` (plus the skill's name, and `good first issue` when it is a self-contained change), instead of living only in someone's notes. Look there first if you want to help: [open deferred minors](https://github.com/NarenDawar/narens-claude-toolkit/issues?q=is%3Aissue+is%3Aopen+label%3Adeferred-minor).

Each issue says what is wrong, where in the code, a failing scenario or evidence, and an idea for the fix. To pick one up, comment on it, then follow "Before opening a PR" above. Fixes start with a test that fails for the reason the issue describes.
