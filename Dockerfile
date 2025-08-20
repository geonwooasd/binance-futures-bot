FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY config ./config
COPY src ./src
COPY data ./data
ENV PYTHONPATH=/app/src
CMD ["python", "-m", "src.runner"]
