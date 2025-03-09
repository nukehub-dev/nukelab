# Copyright (c) NukeLab Development Team.
# Distributed under the terms of the BSD-2-Clause license.

# Use the Debian image as a base
ARG BASE_IMAGE=debian:12
FROM $BASE_IMAGE

# Install dependencies
RUN apt-get update && \ 
    apt-get install -y \
    python3 \
    python3-venv \
    nodejs \
    npm \
    libssl-dev \
    libcurl4-openssl-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install configurable-http-proxy
RUN npm install -g configurable-http-proxy

# Create a virtual environment and install JupyterHub dependencies
RUN python3 -m venv /opt/jupyterhub-venv && \
    /opt/jupyterhub-venv/bin/pip install --upgrade pip && \
    /opt/jupyterhub-venv/bin/pip install \
        jupyterhub \
        pycurl \
        jupyterhub-idle-culler \
        oauthenticator dockerspawner \
        jupyterhub-nativeauthenticator

# Add virtual environment to PATH
ENV PATH="/opt/jupyterhub-venv/bin:$PATH"

# Copy nukelab into the image
COPY nukelab.png ./nukelab.png

# Copy the JupyterHub configuration file into the image
COPY jupyterhub/jupyterhub_config.py /jupyterhub_config.py

#Copy favicon into the image
COPY jupyterhub/favicon.ico /usr/local/share/jupyterhub/static/favicon.ico

# Copy logo into the image
COPY jupyterhub/logo.svg /usr/local/share/jupyterhub/static/logo.svg
COPY jupyterhub/logo.png /usr/local/share/jupyterhub/static/logo.png

# Copy manifest into the image
COPY jupyterhub/manifest.json /usr/local/share/jupyterhub/static/manifest.json

# Copy service-worker into the image
COPY jupyterhub/service-worker.js /usr/local/share/jupyterhub/static/service-worker.js

# Copy NukeLab templates file into the image
COPY jupyterhub/templates /usr/local/share/jupyterhub/templates

# Start JupyterHub with the configuration file
CMD ["jupyterhub"]