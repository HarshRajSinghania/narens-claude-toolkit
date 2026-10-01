# Contributing

Thanks for helping improve Naren's Claude Skills. Bug reports and skill ideas are welcome via issues.

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
