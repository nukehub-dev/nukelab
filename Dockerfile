# Copyright (c) NukeLab Development Team.
# Distributed under the terms of the BSD-2-Clause license.

# Use the Debian image as a base
ARG BASE_IMAGE=debian:12
FROM $BASE_IMAGE

# Define the virtual environment path
ARG VENV=/opt/jupyterhub-venv

# Install OS dependencies
RUN apt-get update && \ 
    apt-get install -y --no-install-recommends \
    python3-venv \
    nodejs \
    npm \
    libssl-dev \
    libcurl4-openssl-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install configurable-http-proxy for JupyterHub
RUN npm install -g configurable-http-proxy && \
    npm cache clean --force

# Create a virtual environment and install JupyterHub and other dependencies
RUN python3 -m venv $VENV && \
    $VENV/bin/pip install --upgrade pip && \
    $VENV/bin/pip install --no-cache-dir \
        "jupyterhub==5.3.0" \
        pycurl \
        jupyterhub-idle-culler \
        oauthenticator dockerspawner \
        jupyterhub-nativeauthenticator

# Add virtual environment to PATH
ENV PATH="$VENV/bin:$PATH"

# Copy nukelab logo into the root directory
COPY nukelab.png ./nukelab.png

# Copy the JupyterHub configuration file into the root directory
COPY jupyterhub/jupyterhub_config.py ./jupyterhub_config.py

# Copy favicon into the virtual environment
COPY jupyterhub/favicon.ico $VENV/share/jupyterhub/static/favicon.ico

# Copy logos into the virtual environment
COPY jupyterhub/logo.svg $VENV/share/jupyterhub/static/logo.svg
COPY jupyterhub/logo.png $VENV/share/jupyterhub/static/logo.png

# Copy manifest into the virtual environment
COPY jupyterhub/manifest.json $VENV/share/jupyterhub/static/manifest.json

# Copy service-worker into the virtual environment
COPY jupyterhub/service-worker.js $VENV/share/jupyterhub/static/service-worker.js

# Copy templates folder into the virtual environment
COPY jupyterhub/templates $VENV/share/jupyterhub/templates

# Start JupyterHub with the configuration file
CMD ["jupyterhub"]