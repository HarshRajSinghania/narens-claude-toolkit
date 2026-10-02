# Data pipeline

- Never run `DROP TABLE` or `TRUNCATE` in any command.
- Do not modify files in `data/raw/`; raw data is immutable.
- Never write credentials or API keys into code (the strings `AKIA` or `api_key =` must not appear in written files).
- Run `make lint` before finishing.
- Be careful with the production database.
- Think about performance when joining large tables.
