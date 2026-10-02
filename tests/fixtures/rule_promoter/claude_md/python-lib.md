# Python library

- Don't edit generated files in `src/pkg/_generated/`.
- Never use `print(` for logging in `src/pkg/`; use the logging module.
- Do not run `pip install` directly; use `uv add` instead.
- Always run `pytest -q` before stopping.
- Use type hints everywhere.
- Keep public APIs backwards compatible.
- Docstrings should explain why, not what.
