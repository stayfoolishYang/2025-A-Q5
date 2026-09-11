FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    JAMMERS_HOST=0.0.0.0 JAMMERS_DATA_DIR=/data \
    JAMMERS_TOKEN_FILE=/run/secrets/jammers_token
RUN useradd --uid 10001 --create-home jammers && mkdir /data && chown jammers:jammers /data
COPY --chown=jammers:jammers . /app
USER jammers
VOLUME ["/data"]
EXPOSE 2026 2027
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 CMD ["python3", "healthcheck.py"]
CMD ["python3", "start.py"]
