#!/bin/bash
# ==============================================================================
# Script de Configuración Automatizada para la Máquina Virtual (Ubuntu)
# Proyecto Failover Automático — Zabbix + GNS3 + Docker
# ==============================================================================

# Evitar diálogos interactivos durante la instalación de paquetes
export DEBIAN_FRONTEND=noninteractive

echo "🚀 Iniciando configuración de la máquina virtual..."
sleep 2

# 1. Actualizar el sistema e instalar prerrequisitos básicos
echo "🔄 Actualizando repositorios y paquetes..."
sudo apt-get update -y
sudo apt-get upgrade -y
sudo apt-get install -y curl git software-properties-common apt-transport-https ca-certificates gnupg lsb-release

# 2. Configurar selecciones de debconf para evitar preguntas interactivas (Wireshark y uBridge)
echo "wireshark-common wireshark-common/install-sysusers boolean true" | sudo debconf-set-selections

# 3. Agregar PPA oficial de GNS3 e instalar GNS3
echo "🌐 Agregando repositorio de GNS3..."
sudo add-apt-repository ppa:gns3/ppa -y
sudo apt-get update -y

echo "📦 Instalando GNS3 (GUI, Server y dependencias)..."
sudo apt-get install -y gns3-gui gns3-server dynamips ubridge wireshark

# 4. Instalar Docker y Docker Compose
echo "🐳 Instalando Docker y Docker Compose..."
sudo apt-get install -y docker.io docker-compose-v2

# 5. Configurar permisos de usuario
echo "🔑 Configurando permisos de grupo para el usuario actual ($USER)..."
# Agregar al grupo docker
sudo usermod -aG docker $USER
# Agregar al grupo ubridge (necesario para GNS3)
sudo usermod -aG ubridge $USER
# Agregar al grupo wireshark (para capturas de paquetes)
sudo usermod -aG wireshark $USER
# Agregar al grupo kvm si está disponible
if getent group kvm > /dev/null; then
    sudo usermod -aG kvm $USER
fi

# Configurar permisos en el ejecutable ubridge
sudo chmod 4755 /usr/bin/ubridge

# 6. Descargar imágenes Docker necesarias con antelación
echo "📥 Descargando imágenes Docker del proyecto para ahorrar tiempo..."
sudo docker pull mysql:8.0
sudo docker pull zabbix/zabbix-server-mysql:ubuntu-7.0-latest
sudo docker pull zabbix/zabbix-web-apache-mysql:ubuntu-7.0-latest
sudo docker pull zabbix/zabbix-agent:ubuntu-7.0-latest
sudo docker pull alpine:latest

echo "======================================================================="
echo "✅ ¡Configuración completada con éxito!"
echo "======================================================================="
echo "⚠️  IMPORTANTE:"
echo "1. Reinicia la máquina virtual para que se apliquen los grupos y permisos:"
echo "   sudo reboot"
echo "2. Después de reiniciar, copia la carpeta de tu proyecto 'Proyecto_Failover'"
echo "   dentro de esta VM."
echo "3. Abre GNS3, carga tu topología y arranca el proyecto con:"
echo "   docker compose up -d"
echo "======================================================================="
