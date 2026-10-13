FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY streamlit_app.py .

EXPOSE 8501
# runOnSave: `docker compose watch` দিয়ে কোড sync হলে পেজ নিজে থেকে রিলোড হবে
CMD ["streamlit", "run", "streamlit_app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", \
     "--server.runOnSave=true", "--browser.gatherUsageStats=false"]
