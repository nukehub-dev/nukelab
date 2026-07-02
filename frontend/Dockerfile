# Build stage
FROM node:24-alpine@sha256:4ba75f835bb8802193e4c114572113d4b26f95f6f094f4b5229d2a77773e0afc AS builder

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
FROM docker.io/library/nginx:alpine@sha256:1a8724a52d432501548a8d8681bb1554c2d09778f8b9ed0882fc3442549980b7

# Copy built assets
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
