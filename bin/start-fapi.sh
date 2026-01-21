#!/bin/bash
# Start TarXiv FastAPI server

uv run fastapi run --port ${TARXIV_FASTAPI_PORT} --host 0.0.0.0 /app/tarxiv/fapi.py