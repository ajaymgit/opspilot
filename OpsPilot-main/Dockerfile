FROM python:3.10-slim

WORKDIR /app

# Install system utilities and lightweight Java runtime for verification
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    default-jre-headless \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy project specification and install dependencies
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -e ".[dev,extension-plots]" openai

# Copy application source code and configurations
COPY src/ ./src/
COPY config/ ./config/
COPY examples/ ./examples/

EXPOSE 8080

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "opspilot.cli", "serve", "--host", "0.0.0.0", "--port", "8080"]
