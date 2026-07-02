# Multi-stage build for production-ready auth sidecar
FROM golang:1.25-alpine@sha256:523c3effe300580ed375e43f43b1c9b091b68e935a7c3a92bfcc4e7ed55b18c2 AS builder

# Install git and ca-certificates for fetching dependencies
RUN apk add --no-cache git ca-certificates

WORKDIR /build

# Copy source code and go.mod
COPY go.mod main.go ./

# Download dependencies and generate go.sum
RUN go mod tidy

# Build the binary with optimizations
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build \
    -ldflags='-w -s -extldflags "-static"' \
    -a -installsuffix cgo \
    -o auth-sidecar \
    main.go

# Final stage - minimal scratch image
FROM scratch

# Copy ca-certificates for HTTPS
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/

# Copy the binary
COPY --from=builder /build/auth-sidecar /auth-sidecar

# Use non-root user (nobody)
USER 65534:65534

# Expose the default port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["/auth-sidecar", "-health-check"] || exit 1

ENTRYPOINT ["/auth-sidecar"]
