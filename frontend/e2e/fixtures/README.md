# E2E runtime fixture image

Disposable runtime for browser tests. It extends the real hardened
`nukelab-environment-base` image, so it keeps `/start.sh`, nginx on port 8080,
`/health`, the auth sidecar, and the non-root runtime contract. It adds a tiny
protected static page under `/usr/share/nginx/html/fixture/` plus
`/etc/nginx/conf.d/fixture.conf`; no extra application process is needed.

## Build

The repository-root `.dockerignore` filters the default context, so this folder
carries `runtime.Dockerfile.dockerignore` to re-include only the fixture
artifacts. This relies on Dockerfile-specific ignore files (BuildKit, the
default in current Docker). Build from the repository root (the Dockerfile uses
repo-root-relative `COPY` paths) and make sure `nukelab-environment-base` is
already built:

```bash
docker build \
  -f frontend/e2e/fixtures/runtime.Dockerfile \
  --build-arg BASE_IMAGE=nukelab-environment-base:latest \
  --build-arg VARIANT=A \
  -t nukelab-e2e-runtime:a .

docker build \
  -f frontend/e2e/fixtures/runtime.Dockerfile \
  --build-arg BASE_IMAGE=nukelab-environment-base:latest \
  --build-arg VARIANT=B \
  -t nukelab-e2e-runtime:b .
```

## Contract

- `/` is protected by `auth_request /auth` and serves `index.html` from the
  fixture directory through the real auth sidecar.
- The page carries `data-nukelab-fixture="runtime"`; `/variant` returns the
  build's variant letter and is protected like the page.
- `/health` and `/auth/health` remain public, as in the base runtime.
- Browser tests select it with `E2E_RUNTIME_IMAGE=nukelab-e2e-runtime:a` and
  `E2E_RUNTIME_IMAGE_B=nukelab-e2e-runtime:b`.
