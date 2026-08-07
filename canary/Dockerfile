FROM python:3.12-slim
WORKDIR /app
COPY app.py .
# /data là volume chứa canary_hits.jsonl (bằng chứng G1) — xem docker-compose.yml.
VOLUME ["/data"]
EXPOSE 8099
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8099/healthz', timeout=2).status==200 else 1)"
CMD ["python", "-u", "app.py"]
