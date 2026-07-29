FROM python:3.12-slim

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev build-essential && rm -rf /var/lib/apt/lists/*

# Set workdir
WORKDIR /app

# Copy only requirements first for better caching
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Copy the entire backend source code
COPY backend/ .
COPY frontend/ ./frontend/

# Expose the FastAPI port
EXPOSE 8000

# Command to run the server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
