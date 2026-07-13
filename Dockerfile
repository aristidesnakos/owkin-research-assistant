# CPU-only: all inference is remote via OpenRouter, so there is no GPU dependency and
# the image runs unchanged on macOS (Apple Silicon or Intel) and Windows 11.
FROM python:3.11-slim

WORKDIR /app

# Without this, Python block-buffers stdout when it is a pipe, so `docker compose logs`
# and the CLI's output arrive late or not at all.
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# .dockerignore keeps .env, .git and the virtualenv out of the build context, so a
# developer's API key is never baked into a readable image layer. The key is injected
# at runtime by docker-compose.yml.
COPY . .

EXPOSE 8501

# The web app is the default surface: `docker compose up` serves it on :8501.
# headless=true stops Streamlit prompting for an email address on first run.
# The CLI is one command away:
#   docker compose run --rm web python cli.py "What are the main genes in lung cancer?"
CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
