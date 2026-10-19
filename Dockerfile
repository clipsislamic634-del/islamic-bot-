# Render Dockerfile for Islamic Clips44 bot.
# Why Docker and not plain Python on Render: the plain Python environment
# does not guarantee ffmpeg, and this bot needs ffmpeg (image + audio = video).
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# The 4 files are uploaded to the ROOT of the GitHub repo (phone flow),
# so they land at /app/*. COPY . . copies them into /app.
COPY . .
CMD ["python", "server_run.py"]
