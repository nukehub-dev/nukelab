# Copyright (c) NukeLab Development Team.
# Distributed under the terms of the BSD-2-Clause license.

FROM nukelab-base:latest

# Install build tools and runtimes needed by the IDE and Python packages.
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        build-essential \
        pkg-config \
        git \
        wget \
        locales \
        ffmpeg \
        libx11-dev \
        libxkbfile-dev \
        && \
    # Remove downloaded package files to reduce the final image size.
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    # Configure the system's locale to en_US.UTF-8.
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    locale-gen

# Install Node.js
ARG NODE_VERSION=24
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g yarn

# Configure core environment variables for Conda and the user
ENV CONDA_DIR=/opt/conda \
    SHELL=/bin/bash \
    LC_ALL=en_US.UTF-8 \
    LANG=en_US.UTF-8 \
    LANGUAGE=en_US.UTF-8
ENV PATH=${CONDA_DIR}/bin:${PATH}

# Install Miniforge to manage Python environments
RUN wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -O Miniforge3.sh && \
    bash Miniforge3.sh -b -p $CONDA_DIR && \
    echo ". $CONDA_DIR/etc/profile.d/conda.sh" >> /etc/profile.d/conda.sh && \
    rm Miniforge3.sh

# Install and build the nuke-ide extension
RUN cd /opt && \
    git clone https://github.com/nukehub-dev/nuke-ide.git && \
    cd nuke-ide && \
    export PUPPETEER_SKIP_DOWNLOAD=true && \
    yarn && \
    yarn download:plugins && \
    yarn build:browser

# Set the Theia webview endpoint for rendering notebook outputs
ENV THEIA_WEBVIEW_EXTERNAL_ENDPOINT={{hostname}}

# Add the ide location block; the base nginx.conf includes conf.d/*.conf.
COPY ide.conf /etc/nginx/conf.d/ide.conf

# Start nginx and proxy authenticated requests to the IDE.
ENV NUKELAB_START_COMMAND="yarn --cwd /opt/nuke-ide start:browser"
