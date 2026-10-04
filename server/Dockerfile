FROM vllm/vllm-openai:v0.30.0

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir -r requirements.txt

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin vdu

# The base image runs as root. This one runs as an unprivileged user, with every
# cache under /tmp so the root filesystem can be mounted read-only.
ENV HOME=/tmp \
    HF_HOME=/tmp/hf \
    XDG_CACHE_HOME=/tmp/cache
USER 10001

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
