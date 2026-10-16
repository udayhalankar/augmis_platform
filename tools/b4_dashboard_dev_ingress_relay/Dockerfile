FROM python:3.12-slim
WORKDIR /opt/augmis-relay
COPY server.py ./server.py
RUN groupadd --gid 10002 augmisrelay && \
    useradd --uid 10002 --gid 10002 --no-create-home --shell /usr/sbin/nologin augmisrelay
USER 10002:10002
EXPOSE 18080
CMD ["python", "-I", "server.py"]
