# The MCP server: a thin front door for AI assistants. CPU only, no SDK, no GPU.
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml requirements.txt ./
COPY vdu_mcp ./vdu_mcp
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir --no-deps . \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin vdu
# An unprivileged user. The server writes nothing to disk.
USER 10001
EXPOSE 8080
CMD ["python", "-m", "vdu_mcp", "--transport", "http", "--host", "0.0.0.0", "--port", "8080"]
