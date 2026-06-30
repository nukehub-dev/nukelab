FROM debian:13@sha256:3a953985c225a97dfb5a8f1ddc6a3ecefefc35ef51f537075e08941305045a1e

ENV DEBIAN_FRONTEND=noninteractive
ENV NODE_VERSION=24

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
# to avoid collisions with distro default users.
RUN groupadd -r nukelab -g 65532 && \
    useradd -r -g nukelab -u 65532 -m -s /bin/bash -d /home/nukelab nukelab

# Copy auth sidecar binary from services build and make it executable by all
# users so the hardened non-root runtime can still launch it.
COPY --from=nukelab-auth-sidecar:latest --chmod=755 /auth-sidecar /usr/local/bin/auth-sidecar

# Copy shared nginx config
COPY nginx.conf /etc/nginx/nginx.conf

# Prepare directories so nginx can run as the non-root nukelab user.
# When the backend enables ReadonlyRootfs, these paths are mounted as tmpfs.
# Drop-in config directory lets child environments add location blocks without
# duplicating the shared auth/sidecar boilerplate.
RUN mkdir -p /var/cache/nginx /var/log/nginx /var/run /etc/nginx/conf.d \
    && chown -R nukelab:nukelab /var/cache/nginx /var/log/nginx /var/run /etc/nginx \
    && chmod 755 /var/cache/nginx /var/log/nginx /var/run /etc/nginx /etc/nginx/conf.d

# Expose the unprivileged port nginx listens on (matches nginx.conf)
EXPOSE 8080

# Default command
CMD ["bash"]
