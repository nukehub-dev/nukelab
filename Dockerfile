# Copyright (c) NukeLab Development Team.
# Distributed under the terms of the Modified BSD License.

# Use the Ubuntu 22.04 image as a base
ARG BASE_IMAGE=ubuntu:22.04
FROM $BASE_IMAGE

# Install dependencies
RUN apt-get update && \ 
    apt-get install -y \
    python3 \
    python3-pip \
    nodejs \
    npm \
    libssl-dev \
    libcurl4-openssl-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install configurable-http-proxy
RUN npm install -g configurable-http-proxy

# Install JupyterHub and its dependencies
RUN pip3 install jupyterhub pycurl

# Install authenticators and spawners
RUN pip3 install oauthenticator dockerspawner jupyterhub-nativeauthenticator

# Copy nukelab into the image
COPY nukelab.png ./nukelab.png

# Copy the JupyterHub configuration file into the image
COPY jupyterhub/jupyterhub_config.py /jupyterhub_config.py

#Copy favicon into the image
COPY jupyterhub/favicon.ico /usr/local/share/jupyterhub/static/favicon.ico

# Copy NukeLab templates file into the image
COPY jupyterhub/templates /usr/local/share/jupyterhub/templates

# Start JupyterHub with the configuration file
CMD ["jupyterhub"]