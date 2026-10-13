# Backend image — API (uvicorn) আর ingest job দুটোই এই একই image থেকে চলে,
# শুধু command আলাদা (docker-compose.yml দেখো)।
FROM python:3.12-slim

# .pyc ফাইল বানাবে না, আর print() সাথে সাথে docker logs এ দেখাবে
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# আগে শুধু requirements কপি করে install — কোড বদলালেও এই layer cache থেকে আসবে,
# প্রতিবার সব প্যাকেজ নতুন করে ডাউনলোড হবে না।
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
