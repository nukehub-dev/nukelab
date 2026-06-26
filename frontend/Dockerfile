# Build stage
FROM node:22-alpine AS builder

WORKDIR /app

# Build-time arg for the CDN base URL. Leave unset to serve assets from /.
ARG VITE_CDN_URL

# Copy package files
COPY package*.json ./
RUN npm ci

# Copy source and build
COPY . .
RUN npm run build

# Production stage
FROM docker.io/library/nginx:alpine

# Copy built assets
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
