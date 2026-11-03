# Anchorless: a 24/7 text newscast for IPTV.
FROM python:3.12-slim

# ffmpeg, plus VA-API drivers for hardware encoding (Intel: iHD, AMD: Mesa).
# The Intel driver lives in Debian's non-free component, and only exists for amd64.
RUN sed -i 's/^Components: main$/Components: main non-free non-free-firmware/' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg mesa-va-drivers vainfo \
       $([ "$(dpkg --print-architecture)" = amd64 ] && echo intel-media-va-driver-non-free) \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.4 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock README.md LICENSE config.example.toml local.example.toml ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

RUN useradd --system --uid 10001 --home /data anchorless \
    && mkdir -p /data /config && chown anchorless /data /config
USER anchorless
ENV PATH="/app/.venv/bin:$PATH" ANCHORLESS_CONFIG=/config/config.toml ANCHORLESS__DATA__DIR=/data PYTHONUNBUFFERED=1
VOLUME /data /config
EXPOSE 9798
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9798/health', timeout=4)"
CMD ["anchorless", "serve", "--init"]
