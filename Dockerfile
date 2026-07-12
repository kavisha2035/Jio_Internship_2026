# ─── Multi-Stage Build: Build React UI & Run FastAPI ──────────────────
FROM python:3.10-slim

# Install system dependencies for OpenCV and Node.js
RUN apt-get update && apt-get install -y \
    build-essential \
    libgl1-mesa-glx \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 18 (to build the frontend React bundle)
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs

WORKDIR /app

# Install backend dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy and build React frontend assets
COPY frontend/package*.json ./frontend/
RUN cd frontend && npm install
COPY frontend/ ./frontend/
RUN cd frontend && npm run build

# Copy remaining source code (FastAPI backend + ML modules)
COPY . .

# Expose server port
EXPOSE 8000

# Start server
CMD ["python", "app.py"]
