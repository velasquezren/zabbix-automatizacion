FROM python:3.10-slim

LABEL maintainer="UAGRM - Motor de Failover Automatizado"
LABEL description="Automation engine: Zabbix monitoring + Ansible failover/failback"

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    iputils-ping \
    sshpass \
    curl \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Configurar SSH para equipos Cisco legacy
RUN mkdir -p /root/.ssh && \
    echo "Host *\n\
  KexAlgorithms +diffie-hellman-group14-sha1,diffie-hellman-group1-sha1\n\
  HostKeyAlgorithms +ssh-rsa\n\
  Ciphers +aes256-cbc\n\
  MACs +hmac-sha1,hmac-sha1-96\n\
  StrictHostKeyChecking no\n\
  UserKnownHostsFile /dev/null\n" > /root/.ssh/config && \
    chmod 600 /root/.ssh/config

WORKDIR /app

# Instalar dependencias Python (cacheado si requirements.txt no cambia)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar colección Ansible para Cisco IOS
RUN ansible-galaxy collection install cisco.ios --force

# Crear directorio para datos persistentes
RUN mkdir -p /app/data

# Puerto para healthcheck HTTP
EXPOSE 8000

# Healthcheck integrado
HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=10s \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "main.py"]