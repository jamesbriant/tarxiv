#!/bin/bash
# Start old Flask API and new FastAPI servers

TARXIV_FASTAPI_PORT=${TARXIV_FASTAPI_PORT} /app/bin/start-fapi.sh &
/app/bin/start-api