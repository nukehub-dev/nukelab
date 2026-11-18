# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause
#
# Disposable browser-test runtime. Extends the real hardened NukeLab base
# runtime (nginx, /start.sh, port 8080, /health, auth sidecar) with a tiny
# protected static page. Build from the repository root so the COPY paths
# below resolve:
#
#   docker build \
#     -f frontend/e2e/fixtures/runtime.Dockerfile \
#     --build-arg BASE_IMAGE=nukelab-environment-base:latest \
#     --build-arg VARIANT=A \
#     -t nukelab-e2e-runtime:a .
#
ARG BASE_IMAGE=nukelab-environment-base:latest

FROM ${BASE_IMAGE}

ARG VARIANT=A

LABEL maintainer="NukeLab <nukehub.org>" \
      org.nukelab.e2e.fixture="runtime" \
      org.nukelab.e2e.variant="${VARIANT}"

# All fixture artifacts live under /usr/share/nginx/html/fixture. The nginx
# drop-in protects the whole prefix with the real auth sidecar.
COPY frontend/e2e/fixtures/html/ /usr/share/nginx/html/fixture/
COPY frontend/e2e/fixtures/fixture.conf /etc/nginx/conf.d/fixture.conf

# The variant letter is part of the image identity so multi-variant scenarios
# can prove which artifact actually launched.
RUN printf '%s\n' "${VARIANT}" > /usr/share/nginx/html/fixture/variant \
    && chmod -R a+rX /usr/share/nginx/html/fixture

# No NUKELAB_START_COMMAND: nginx serves the fixture directly, while /start.sh
# still launches the auth sidecar exactly as production runtimes do.
