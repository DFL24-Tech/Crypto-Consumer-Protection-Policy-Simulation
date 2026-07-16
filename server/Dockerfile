# Build from the repository root: docker build -f server/Dockerfile .
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY dfl24sim/ dfl24sim/
COPY server/ server/
RUN pip install --no-cache-dir . ./server

EXPOSE 8000
CMD ["uvicorn", "dfl24sim_server.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
