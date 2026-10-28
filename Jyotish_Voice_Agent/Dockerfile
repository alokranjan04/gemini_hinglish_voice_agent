# Builder stage
FROM python:3.11 as builder
WORKDIR /install
COPY requirements.txt /requirements.txt
# Build-essential is needed for some python packages
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
RUN pip install --prefix=/install -r /requirements.txt

# Runtime stage
FROM python:3.11-slim
# Install basic system libraries that might be needed for audio/networking
RUN apt-get update && apt-get install -y --no-install-recommends libasound2 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /install /usr/local
COPY *.py app_config.json ./

EXPOSE 8080
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
