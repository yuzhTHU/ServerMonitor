FROM python:3.13-slim-bookworm

RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    pydantic \
    paramiko \
    pyotp \
    python-dotenv \
    pyyaml \
    pandas

WORKDIR /app
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
