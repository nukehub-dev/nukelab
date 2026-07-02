FROM debian:13@sha256:3a953985c225a97dfb5a8f1ddc6a3ecefefc35ef51f537075e08941305045a1e

LABEL maintainer="NukeLab <nukehub.org>"

ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    nginx \
    libnss-wrapper \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user used by hardened container runtime. Use a high UID/GID
# to avoid collisions with distro default users. Do not create /home/nukelab;
# the runtime mounts the real user's home at /home/<username>.
RUN groupadd -r nukelab -g 65532 && \
    useradd -r -g nukelab -u 65532 -M -s /bin/bash nukelab && \
    mkdir -p /home && chown nukelab:nukelab /home && chmod 755 /home && \
    # Some base packages or tools create a /home/nukelab directory; remove it so
    # the runtime-mounted /home/<username> is the only home users see.
    rm -rf /home/nukelab

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

# Make login and interactive shells show the human username instead of the
# fixed hardened-runtime account in the prompt and $USER/$HOME.
COPY nukelab-prompt.sh /etc/profile.d/nukelab-prompt.sh
COPY skel-bashrc-snippet.sh /tmp/skel-bashrc-snippet.sh
RUN chmod 644 /etc/profile.d/nukelab-prompt.sh && \
    cat /tmp/skel-bashrc-snippet.sh >> /etc/skel/.bashrc && \
    rm /tmp/skel-bashrc-snippet.sh

# Start nginx and the configured application command
COPY --chmod=755 start.sh /start.sh
CMD ["/start.sh"]
