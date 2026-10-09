# The legal host: one generic image for every deployment.
#
# It holds the renderer, the templates and the example deployment, and no deployment's data.
# A deployment mounts its data:
#
#   docker run -p 8080:8080 -e LEGAL_REVISION=$(git -C my-data rev-parse HEAD) \
#     -v "$PWD/my-data:/data:ro" ghcr.io/celine-eu/celine-legal
#
# The root serves the published releases only (a slot with none: "not yet available"); with
# LEGAL_REVISION, the draft is served at /draft/<revision>/ and nowhere else. Everything is
# laid out once at startup, in memory; nothing is written at runtime, so the root filesystem
# can be read-only.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /bin/

ARG LEGAL_REVISION=unknown
LABEL org.opencontainers.image.title="celine-legal" \
      org.opencontainers.image.description="The legal host: an energy-community platform's legal documents, rendered from mounted data" \
      org.opencontainers.image.source="https://github.com/celine-eu/celine-legal" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.revision="${LEGAL_REVISION}"

WORKDIR /app
ENV UV_FROZEN=1 UV_NO_CACHE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# The lock as it is: an image carries the versions the tests ran against.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --no-dev --no-install-project
COPY src/ src/
COPY templates/ templates/
RUN uv sync --no-dev
# The example deployment, to try the image: LEGAL_DATA=/app/data/example.
COPY data/example/ data/example/

ENV LEGAL_DATA=/data
USER 1000:1000
EXPOSE 8080
CMD ["/app/.venv/bin/uvicorn", "--factory", "celine.legal.app:create_app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
