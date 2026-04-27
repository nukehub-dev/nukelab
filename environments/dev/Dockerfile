FROM nukelab-base:latest

# Clone and build NukeIDE
RUN git clone https://github.com/nukehub-dev/nuke-ide.git /opt/nuke-ide \
    && cd /opt/nuke-ide \
    && yarn install \
    && yarn build:browser

# Copy nginx configuration
COPY nginx.conf /etc/nginx/nginx.conf

# Copy startup script
COPY startup.sh /opt/nukelab/startup.sh
RUN chmod +x /opt/nukelab/startup.sh

# Expose port
EXPOSE 80

# Start services
CMD ["/opt/nukelab/startup.sh"]
