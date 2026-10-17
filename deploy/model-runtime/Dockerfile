# Maintainer/reference recipe, not a published turnkey runtime image.
# Prepared artifacts must match the target CPU, ABI, and model layout.
FROM debian:bookworm-slim

ARG LLAMA_SWAP_VERSION=228
ARG TARGETARCH
ARG LLAMA_SWAP_SHA256
ARG DOKOCR_IK_RUNTIME_TARBALL_URL
ARG DOKOCR_IK_RUNTIME_TARBALL_SHA256

ENV DEBIAN_FRONTEND=noninteractive \
    DOKOCR_MODEL_RUNTIME_CONFIG=/etc/dokocr/llama-swap.config.yaml \
    DOKOCR_MODEL_RUNTIME_LISTEN=0.0.0.0:8092

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tar xz-utils libgomp1 libstdc++6 libgcc-s1 \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    : "${LLAMA_SWAP_SHA256:?Supply the official checksum for the selected llama-swap release asset}"; \
    arch="${TARGETARCH:-amd64}"; \
    case "$arch" in amd64|arm64) ;; *) echo "unsupported arch: $arch" >&2; exit 1 ;; esac; \
    curl -L --fail --retry 3 -o /tmp/llama-swap.tar.gz \
      "https://github.com/mostlygeek/llama-swap/releases/download/v${LLAMA_SWAP_VERSION}/llama-swap_${LLAMA_SWAP_VERSION}_linux_${arch}.tar.gz"; \
    printf '%s  %s\n' "$LLAMA_SWAP_SHA256" /tmp/llama-swap.tar.gz | sha256sum -c -; \
    tar -xzf /tmp/llama-swap.tar.gz -C /usr/local/bin llama-swap; \
    chmod +x /usr/local/bin/llama-swap; \
    rm /tmp/llama-swap.tar.gz

RUN set -eux; \
    : "${DOKOCR_IK_RUNTIME_TARBALL_URL:?Supply the prepared runtime artifact URL}"; \
    : "${DOKOCR_IK_RUNTIME_TARBALL_SHA256:?Supply the runtime artifact checksum}"; \
    curl -L --fail --retry 3 -o /tmp/dokocr-runtime.tar.gz "$DOKOCR_IK_RUNTIME_TARBALL_URL"; \
    printf '%s  %s\n' "$DOKOCR_IK_RUNTIME_TARBALL_SHA256" /tmp/dokocr-runtime.tar.gz | sha256sum -c -; \
    mkdir -p /opt/dokocr; \
    tar -xzf /tmp/dokocr-runtime.tar.gz -C /opt/dokocr; \
    rm /tmp/dokocr-runtime.tar.gz

COPY llama-swap.config.yaml /etc/dokocr/llama-swap.config.yaml
COPY entrypoint.sh /usr/local/bin/dokocr-model-runtime-entrypoint
RUN chmod +x /usr/local/bin/dokocr-model-runtime-entrypoint \
    && mkdir -p /models /var/log/dokocr

VOLUME ["/models", "/var/log/dokocr"]
EXPOSE 8092
# Discovery/availability only. Maintainers must also exercise real inference.
HEALTHCHECK --interval=10s --timeout=5s --retries=60 --start-period=30s \
  CMD curl -fsS http://127.0.0.1:8092/health >/dev/null || exit 1
ENTRYPOINT ["/usr/local/bin/dokocr-model-runtime-entrypoint"]
