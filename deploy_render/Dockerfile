FROM python:3.14-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 ffmpeg && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 appuser
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=appuser:appuser . .
USER appuser
ENV PYTHONUNBUFFERED=1 GRADIO_ANALYTICS_ENABLED=False
EXPOSE 7860
CMD ["python", "gradio_app.py", "--host", "0.0.0.0"]
