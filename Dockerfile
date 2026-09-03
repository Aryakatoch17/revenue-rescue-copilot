FROM python:3.12-slim-bookworm
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY data/diagnosis_cache.json ./data/diagnosis_cache.json
ENV DIAGNOSIS_MODE=cache
ENV LIVE_COPY=0
ENV ALLOW_LIVE_LLM=0
ENV RAZORPAY_LIVE_BATCH=0
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
