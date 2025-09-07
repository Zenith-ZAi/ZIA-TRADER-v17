FROM python:3.11-slim-buster

WORKDIR /app

COPY requirements_unified.txt .
RUN pip install --no-cache-dir -r requirements_unified.txt

COPY . .

EXPOSE 5000

CMD ["python", "src/main.py"]


