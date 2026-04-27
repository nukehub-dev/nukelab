FROM nukelab-base:latest

# Install nginx
RUN apt-get update && apt-get install -y nginx \
    && rm -rf /var/lib/apt/lists/*

# Create simple test page
RUN echo '<!DOCTYPE html><html><head><title>NukeLab</title></head><body><h1>NukeIDE Test Environment</h1><p>Server is running!</p></body></html>' > /var/www/html/index.html

# Copy nginx config
COPY nginx.conf /etc/nginx/nginx.conf

# Expose port
EXPOSE 80

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
