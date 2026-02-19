FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create attachments directory
RUN mkdir -p /app/data/attachments

# Make start script executable
RUN chmod +x start.sh

# Expose port
EXPOSE 8000

# Run migrations and start application
CMD ["./start.sh"]
