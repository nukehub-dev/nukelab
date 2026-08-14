# Copyright (c) NukeLab Development Team.
# Distributed under the terms of the BSD-2-Clause license.

ARG BASE_TAG=v1.0.0
ARG BASE_IMAGE=ghcr.io/nukelab/conda-base:${BASE_TAG}

FROM $BASE_IMAGE

# Install IDE-specific system dependencies.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        libx11-dev \
        libxkbfile-dev \
        libsecret-1-dev \
        xvfb && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Node.js and Yarn from conda-forge instead of NodeSource apt,
# because the NodeSource package hard-depends on system python3.
ARG NODE_VERSION=24
RUN conda install -y -c conda-forge nodejs=${NODE_VERSION} yarn=1.22.22 && \
    conda clean -afy

# Install and build the nuke-ide extension.
# NUKE_EXTENSIONS=all opts into nukelab-integration, which nuke-ide excludes
# from builds by default (it is NukeLab-only; see scripts/with-extension-set.js).
RUN cd /opt && \
    git clone https://github.com/nukehub-dev/nuke-ide.git && \
    cd nuke-ide && \
    export PUPPETEER_SKIP_DOWNLOAD=true && \
    yarn && \
    yarn download:plugins && \
    NUKE_EXTENSIONS=all yarn build:browser

# Set the Theia webview endpoint for rendering notebook outputs
ENV THEIA_WEBVIEW_EXTERNAL_ENDPOINT={{hostname}}

# Add the ide location block; the base nginx.conf includes conf.d/*.conf.
COPY ide.conf /etc/nginx/conf.d/ide.conf

# Start nginx and proxy authenticated requests to the IDE.
# --hostname :: makes Theia listen on the IPv6 any-address (which also
# accepts IPv4 connections), so nginx can reach it via localhost even when
# the container resolver prefers ::1 for localhost.
# start-ide.sh first launches Xvfb on $DISPLAY: conda-forge ParaView/VTK
# (used by the nuke-ide visualizer) are X11/GLX-only builds and abort with
# "bad X server connection" when creating a render window without an X
# connection, even offscreen. The IDE backend passes DISPLAY through to the
# visualizer server process.
COPY --chmod=755 start-ide.sh /opt/nukelab/start-ide.sh
ENV DISPLAY=:99
ENV NUKELAB_START_COMMAND="/opt/nukelab/start-ide.sh"

# App probe for the runtime-injected healthcheck (see base/healthcheck.sh):
# IDE liveness on :3000. Domain-specific toolchain images in nukelab-environments
# mount scientific software into this runtime image.
ENV NUKELAB_HEALTH_PROBE_URLS="http://localhost:3000/"
