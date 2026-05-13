FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY tests ./tests
COPY scripts ./scripts
COPY configs ./configs
COPY data ./data
COPY reports ./reports
RUN pip install --no-cache-dir -e ".[dev]"
CMD ["make", "test"]
