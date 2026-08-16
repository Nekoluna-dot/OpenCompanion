FROM python:3.11-slim

# 时区数据：每日日记/写信/提醒按本地时间运行，缺失时 Python 本地时间会退化为 UTC
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# 默认中国时区，可用 docker-compose.yml 的 environment 覆盖
ENV TZ=Asia/Shanghai
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 先装依赖，利用构建缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 项目代码
COPY . .

EXPOSE 9000 18001

CMD ["python", "main.py"]
