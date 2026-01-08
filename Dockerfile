FROM python:3.12-slim

# 安装curl用于健康检查
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# 设置环境变量 - 强化编码支持
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8
ENV PYTHONLEGACYWINDOWSSTDIO=0
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8

# 设置工作目录
WORKDIR /app

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY k2think_proxy.py .
COPY src/ ./src/

# 创建数据目录和默认accounts文件
RUN mkdir -p /app/data && \
    touch /app/data/accounts.txt && \
    echo '# 请通过volume挂载实际的accounts.txt文件' > /app/data/accounts.txt && \
    echo '# 格式：每行一个JSON对象，例如：' >> /app/data/accounts.txt && \
    echo '# {"email": "user@example.com", "k2_password": "password"}' >> /app/data/accounts.txt

# 创建简单的启动脚本
RUN echo '#!/bin/bash\n\
# 确保数据目录存在\n\
mkdir -p /app/data\n\
# 直接运行应用\n\
exec "$@"' > /app/entrypoint.sh && \
    chmod +x /app/entrypoint.sh

# 暴露端口
EXPOSE 8001

# 健康检查 - 增加启动延迟以等待token刷新完成
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD curl -f http://localhost:8001/health || exit 1

# 设置entrypoint和默认命令
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "k2think_proxy.py"]