# FlaVR Promo image. Built by Portainer from this repo (docker-compose.yml), or by hand:
#   docker build -t flavr-promo .
# bookworm (Debian 12): Playwright 1.49 installs Chromium's system libraries only on Debian 12 /
# Ubuntu; the plain "3.12-slim" tag moved to Debian 13, where "playwright install --with-deps" fails.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Chromium for the calendar picture (+ its system libraries), and fonts for stream titles in
# other scripts (Japanese, Korean, Chinese) and emoji. About 600 MB; built once per update.
RUN playwright install --with-deps chromium \
 && apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-noto-cjk fonts-noto-color-emoji \
 && rm -rf /var/lib/apt/lists/*
COPY flavrpromo ./flavrpromo

# the bot's database lives here (a named volume in docker-compose.yml, so redeploys keep it);
# /import is where FlaVR Bot's old data folder can be mounted read-only for the first start
# (flavrpromo/import_old.py)
VOLUME ["/data"]
# not root inside the container (uid 1000, the same as FlaVR Bot's image, so its files are readable)
RUN useradd --system --uid 1000 flavr && mkdir -p /data /import && chown flavr /data
USER flavr

# the calendar pages, OBS source, .ics feed and /live.json (home network only; never forward it on
# the router). FlaVR Bot uses 3870 on the same PC.
EXPOSE 3871
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('LISTEN_PORT','3871'),timeout=4)"

CMD ["python", "-m", "flavrpromo"]
