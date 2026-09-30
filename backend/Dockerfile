FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ffmpeg libgl1 libglib2.0-0 mesa-va-drivers vainfo && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
COPY requirements-ai.txt .
RUN pip install --no-cache-dir torch==2.14.0 torchvision==0.29.0 --index-url ${TORCH_INDEX} && pip install --no-cache-dir -r requirements-ai.txt
COPY alembic.ini .
COPY alembic alembic
COPY app app
CMD ["sh","-c","alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
