FROM nukelab-base:latest

# Install ttyd (web terminal) used by the dev/test environment.
# ttyd is not packaged in Debian trixie, so fetch the upstream static binary.
ARG TTYD_VERSION=1.7.7
ARG TTYD_SHA256=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55
RUN curl -fsSL "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.x86_64" -o /tmp/ttyd \
    && echo "${TTYD_SHA256}  /tmp/ttyd" | sha256sum -c - \
    && install -m 755 /tmp/ttyd /usr/local/bin/ttyd \
    && rm -f /tmp/ttyd

# Add the terminal location block; the base nginx.conf includes conf.d/*.conf.
COPY terminal.conf /etc/nginx/conf.d/terminal.conf

# Start nginx and ttyd (writable)
COPY --chmod=755 start.sh /start.sh
CMD ["/start.sh"]
