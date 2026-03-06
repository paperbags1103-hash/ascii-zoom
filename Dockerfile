FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY server.py .
EXPOSE 8765
CMD ["python3", "server.py", "--host", "0.0.0.0", "--port", "8765"]
