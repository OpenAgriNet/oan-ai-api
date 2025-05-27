# Use Python as the base image
FROM python:3.11-slim

# Set work directory
WORKDIR /

# Install build dependencies and PostgreSQL client
RUN apt-get update && apt-get install -y \
    supervisor \
    gcc \
    python3-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*


COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and .env file
COPY . .
# Change working directory to zavmo before running Django commands
WORKDIR /oan

# Run django's python manage.py and migrate commands
RUN python3 manage.py makemigrations --noinput
RUN python3 manage.py migrate


# Start supervisor
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
