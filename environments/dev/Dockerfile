FROM nukelab-base:latest

# Install nginx and ttyd (web terminal)
RUN apt-get update && apt-get install -y nginx ttyd \
    && rm -rf /var/lib/apt/lists/*

# Copy nginx config
COPY nginx.conf /etc/nginx/nginx.conf

# Expose port 80 (nginx proxies to ttyd internally)
EXPOSE 80

# Start nginx and ttyd (writable)
COPY start.sh /start.sh
RUN chmod +x /start.sh
CMD ["/start.sh"]
