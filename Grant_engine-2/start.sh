#!/bin/bash
set -e

echo "Starting AltCarbon Grants Intelligence..."

# Backend (Railway FastAPI)
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Streamlit UI
streamlit run app/main.py --server.port 8501 --server.address 0.0.0.0 &
STREAMLIT_PID=$!

echo "Backend running on :8000"
echo "Streamlit running on :8501"

trap "kill $BACKEND_PID $STREAMLIT_PID" EXIT
wait
