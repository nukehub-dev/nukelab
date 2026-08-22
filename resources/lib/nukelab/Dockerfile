# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Build the LD_PRELOAD library that gives containers a container-scoped CPU
# view (sysconf CPU count + synthesized /proc/stat).
#
# The resulting image is consumed by environments/base/Dockerfile via
# COPY --from=nukelab-cpu-lib:latest. It is built locally by
# scripts/resources/build-cpu-lib.sh and does not need to be published.
FROM debian:13@sha256:3a953985c225a97dfb5a8f1ddc6a3ecefefc35ef51f537075e08941305045a1e

RUN apt-get update && apt-get install -y \
    gcc \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY libnukelab_cpu.c /src/libnukelab_cpu.c
RUN gcc -shared -fPIC -o /libnukelab_cpu.so /src/libnukelab_cpu.c -ldl
