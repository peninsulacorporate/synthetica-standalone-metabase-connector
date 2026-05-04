FROM python:3.12-slim

WORKDIR /app

# Build deps only for hatchling
RUN pip install --no-cache-dir hatchling

# Install package (editable so volume-mounted source updates on reload)
COPY pyproject.toml README.md /app/
COPY src /app/src
RUN pip install --no-cache-dir /app

EXPOSE 8092

ENV PYTHONUNBUFFERED=1 \
    LOG_LEVEL=INFO \
    METABASE_MCP_HOST=0.0.0.0 \
    METABASE_MCP_PORT=8092

CMD ["metabase-mcp"]
