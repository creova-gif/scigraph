FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --system scigraph && useradd --system --gid scigraph --create-home scigraph

COPY . .

RUN pip install --no-cache-dir .

EXPOSE 8765

USER scigraph

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=3)"

ENTRYPOINT ["scigraph"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8765"]
