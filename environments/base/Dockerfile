FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV NODE_VERSION=22

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    python3 \
    python3-pip \
    nginx \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 22
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g yarn

# Create app directory
WORKDIR /opt/nukelab

# Create non-root user used by hardened container runtime. Use a high UID/GID
# to avoid collisions with distro default users (e.g. ubuntu:1000).
RUN groupadd -r nukelab -g 65532 && \
    useradd -r -g nukelab -u 65532 -m -s /bin/bash -d /home/nukelab nukelab

# Default command
CMD ["bash"]
