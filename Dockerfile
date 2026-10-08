ARG PYTHON_VERSION=3.12
ARG PYTHON_VARIANT=bookworm
FROM python:${PYTHON_VERSION}-${PYTHON_VARIANT}

WORKDIR /app
COPY pyproject.toml README.md requirements.txt ./
COPY src ./src
RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir -e .

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --no-create-home --shell /usr/sbin/nologin app \
    && chown -R app:app /app

USER app

CMD ["python", "-c", "from src.GraphTypeDefinitions.schema import schema; print(schema.as_str())"]
