FROM python:3.14.0a6-bullseye
WORKDIR /app
USER root
RUN pip install requests && \
    apt-get update -y && \
    apt-get install -yq tzdata && \
    ln -fs /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata && \
    rm -rf /var/lib/apt/lists/*

COPY app.py /app/app.py


