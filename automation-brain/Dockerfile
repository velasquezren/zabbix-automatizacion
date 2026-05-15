FROM python:3.10-slim

# Instalar dependencias de red del sistema
RUN apt-get update && apt-get install -y \
    iputils-ping \
    sshpass \
    && rm -rf /var/lib/apt/lists/*

# Instalar Ansible y librería para hablar con Zabbix
RUN pip install ansible pyzabbix requests paramiko ansible-pylibssh

# Fix for old Cisco SSH crypto
RUN mkdir -p /root/.ssh && \
    echo "Host *\n  KexAlgorithms +diffie-hellman-group14-sha1,diffie-hellman-group1-sha1\n  HostKeyAlgorithms +ssh-rsa\n  Ciphers +aes256-cbc\n  MACs +hmac-sha1,hmac-sha1-96\n  StrictHostKeyChecking no\n  UserKnownHostsFile /dev/null\n" > /root/.ssh/config

WORKDIR /app
# El contenedor se queda esperando o corre tu script en loop
CMD ["python", "main.py"]