# Contributing to NukeLab

Thank you for contributing to NukeLab. This document describes the workflow, conventions, and checks expected for code changes.

## Before you start

1. Read the root `AGENTS.md` and the `AGENTS.md` in every directory you plan to touch.
2. Open an issue or discussion if your change is large, architectural, or introduces new dependencies.
3. Make sure you can run the local development stack: see [LOCAL-DEV.md](LOCAL-DEV.md).

## Development workflow

1. Create a feature branch from `develop`:

   ```bash
   git checkout develop
   git pull
   git checkout -b feature/your-feature-name
   ```

2. Make your changes following the conventions below.

3. Add or update tests for new behavior.

4. Run the canonical checks:

   ```bash
   ./nukelabctl lint all
   ./nukelabctl test all
   ./nukelabctl selftest
   ```

5. Commit with a clear message explaining what changed and why.

6. Push and open a pull request against `develop`.

## Code conventions

### Backend (Python)

- Python 3.13
- Format with `ruff format`
- Lint with `ruff check`
- Use type hints where practical
- Prefer async/await for I/O-bound operations
- Keep FastAPI route handlers thin; delegate to services
- Add tests under `backend/tests/` mirroring the structure of `backend/app/`

### Frontend (TypeScript / React)

- Node.js 22+
- Format and lint with the project's `npm run lint` and `npm run format:check`
- Use TanStack Router for routes and TanStack Query for server state
- Keep components focused; lift shared logic into hooks
- Add tests alongside changed components when possible

### Shell scripts

- Run `shellcheck` and `shfmt`
- Prefer `#!/usr/bin/env bash`
- Use `set -euo pipefail` and `IFS=$'\n\t'`
- Source shared helpers from `scripts/lib.sh`
- Add new `nukelabctl` commands as files under `scripts/manage.d/`

## Documentation

Documentation is a first-class deliverable. Update docs when your change affects:

- Architecture, component boundaries, or request flows → `docs/architecture/`
- Deployment, operations, or backup procedures → `docs/operations/`
- Security controls or test scope → `docs/security/`
- Environment variables or CLI commands → `docs/reference/`
- Developer workflow → `docs/development/`

Do not duplicate information that already lives in `.env.example`, generated API docs, or `./nukelabctl --help`. Link instead.

## Testing

### Backend tests

```bash
./nukelabctl test all
./nukelabctl test backend tests/path/to/test_file.py -x -v
```

### Frontend tests

```bash
cd frontend
npm run test
```

### Security regression tests

```bash
./nukelabctl test backend tests/security/test_container_isolation.py --confcutdir=tests/security
```

## Commit messages

Use clear, imperative commit messages:

```
Add support for custom server idle timeouts

- Adds idle_timeout override field to Server model
- Updates spawn dialog with idle timeout selector
- Adds test for idle timeout enforcement
```

## Pull request checklist

- [ ] Branch is based on the latest `develop`
- [ ] `lint all` passes
- [ ] `test all` passes (or failing tests are unrelated and noted)
- [ ] `selftest` passes
- [ ] Documentation updated for user-facing or architectural changes
- [ ] No secrets, credentials, or personal data committed
- [ ] Commit messages explain the change

## Getting help

- Open a discussion for questions
- Open an issue for bugs or feature requests
- Tag maintainers on security-related changes

## License

By contributing, you agree that your contributions will be licensed under the BSD-2-Clause license.
