FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

# 非 root 运行：固定 UID 的系统用户，代码目录归其所有（uvicorn 需要写 __pycache__）
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV PYTHONPATH=/app
EXPOSE 8000

# 存活探针（liveness）：只验证进程能响应 HTTP，不把 Mongo/Redis 故障算进来——
# 依赖故障时重启本容器并不能修复，/health 的 db 字段留给运维/监控核对。
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
