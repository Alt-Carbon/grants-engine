FROM python:3.11-slim

WORKDIR /app

# Install Streamlit app dependencies
COPY app/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy full project so `app.*` and `backend.*` imports resolve
COPY . .

EXPOSE 8501

CMD streamlit run app/main.py \
    --server.port=${PORT:-8501} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.fileWatcherType=none \
    --browser.gatherUsageStats=false
