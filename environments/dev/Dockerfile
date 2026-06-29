FROM nukelab-base:latest

# Install nginx and ttyd (web terminal)
RUN apt-get update && apt-get install -y nginx ttyd \
    && rm -rf /var/lib/apt/lists/*

# Copy auth sidecar binary from services build and make it executable by all
# users so the hardened non-root runtime can still launch it.
COPY --from=nukelab-auth-sidecar:latest --chmod=755 /auth-sidecar /usr/local/bin/auth-sidecar

# Copy nginx config
COPY nginx.conf /etc/nginx/nginx.conf

# Prepare directories so nginx can run as the non-root nukelab user.
# When the backend enables ReadonlyRootfs, these paths are mounted as tmpfs.
RUN mkdir -p /var/cache/nginx /var/log/nginx /var/run \
    && chown -R nukelab:nukelab /var/cache/nginx /var/log/nginx /var/run /etc/nginx \
    && chmod 755 /var/cache/nginx /var/log/nginx /var/run /etc/nginx

# Expose the unprivileged port nginx listens on (matches nginx.conf)
EXPOSE 8080

# Start nginx and ttyd (writable)
COPY --chmod=755 start.sh /start.sh
CMD ["/start.sh"]
