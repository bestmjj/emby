FROM ubuntu:20.04

WORKDIR /app

COPY requirements.txt /app/requirements.txt

ENV TZ=Asia/Shanghai
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -y && \
    apt-get install -y python3 python3-pip && \
    apt-get install -yq tzdata && \
    ln -fs /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata && \
    rm -rf /var/lib/apt/lists/* && \
    pip3 install -r /app/requirements.txt && \
    rm -f /app/requirements.txt



COPY app.py /app/app.py
COPY run.sh /app/run.sh
ENTRYPOINT ["/app/run.sh"]

