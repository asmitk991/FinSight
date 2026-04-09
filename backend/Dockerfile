FROM python:3.11-slim

# Install system dependencies for PyMuPDF (lighter)
RUN apt-get update && apt-get install -y \
    build-essential \
    libglib2.0-0 \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install (Light Version)
COPY requirements-light.txt .
RUN pip install --no-cache-dir -r requirements-light.txt

# Copy the application code
COPY . .

# Create data directory if it doesn't exist
RUN mkdir -p data

# Default environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

EXPOSE 8000

# Make start script executable
RUN chmod +x start.sh

# Start command
CMD ["./start.sh"]
