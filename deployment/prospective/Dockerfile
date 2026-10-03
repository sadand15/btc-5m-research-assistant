FROM python:3.12-slim
ARG COLLECTOR_SHA
ENV PYTHONPATH=/app/src:/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=UTC
WORKDIR /app
RUN pip install --no-cache-dir 'requests>=2.32,<3' && useradd --uid 10001 --create-home collector
COPY src /app/src
COPY docs/architecture /app/docs/architecture
COPY btc5/__init__.py btc5/predictfun.py /app/btc5/
COPY deployment/prospective/build_stamp.py /app/build_stamp.py
RUN python /app/build_stamp.py "$COLLECTOR_SHA" && mkdir -p /app/runtime/v3 && chown -R collector:collector /app/runtime
USER collector
STOPSIGNAL SIGTERM
CMD ["python", "-m", "btc5_v3.prospective", "--help"]
