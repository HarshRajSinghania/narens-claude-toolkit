# Monorepo

- Never edit `packages/shared/**` from a feature branch task; shared is owned by the platform team.
- Do not use `rm -rf` on anything outside of `node_modules/` or `dist/`.
- Don't add `TODO` comments to files under `packages/api/src/`.
- Run `pnpm typecheck` before finishing.
- Use `pnpm`, never `npm install` or `yarn add`.
- Each package needs its own README.
- Review your own diff before saying you are done.
