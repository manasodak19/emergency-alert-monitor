# ==============================================================================
# Phase 11 — Docker Containerization
# Emergency Alert Monitor: Automated Log Monitoring and Anomaly Detection
# ==============================================================================

FROM python:3.11-slim

# Prevent generation of .pyc bytecode and ensure immediate unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_RUN_HOST=0.0.0.0 \
    FLASK_RUN_PORT=5000 \
    FLASK_DEBUG=0 \
    ALERT_DB_PATH=/app/data/alerts.db \
    ALERT_LOG_PATH=/app/logs/app.log \
    ENABLE_LOG_WATCHER=0

# Working directory
WORKDIR /app

# Create unprivileged system user and runtime directories with proper permissions
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin -c "Docker container user" appuser \
    && mkdir -p /app/data /app/logs \
    && chown -R appuser:appuser /app

# Install Python dependencies first for efficient layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application modules and runtime assets
COPY --chown=appuser:appuser app.py .
COPY --chown=appuser:appuser config/ config/
COPY --chown=appuser:appuser database/ database/
COPY --chown=appuser:appuser logging_system/ logging_system/
COPY --chown=appuser:appuser anomaly_detection/ anomaly_detection/
COPY --chown=appuser:appuser dashboard/ dashboard/
COPY --chown=appuser:appuser routes/ routes/
COPY --chown=appuser:appuser tests/ tests/

# Drop privileges to non-root user
USER appuser

# Expose HTTP port
EXPOSE 5000

# Container healthcheck using standard library urllib (no extra OS utilities needed)
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health').read()" || exit 1

# Start the application
CMD ["python", "app.py"]
