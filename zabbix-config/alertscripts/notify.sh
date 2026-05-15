#!/bin/bash
# ============================================================
#  Script de Notificación de Alerta para Zabbix
#  Se coloca en: /usr/lib/zabbix/alertscripts/
#  
#  Zabbix ejecuta este script cuando se dispara una acción.
#  Parámetros: $1=destinatario $2=asunto $3=mensaje
# ============================================================

RECIPIENT="$1"
SUBJECT="$2"
MESSAGE="$3"
LOG_FILE="/tmp/zabbix_alerts.log"

# Registrar la alerta
echo "$(date '+%Y-%m-%d %H:%M:%S') | TO: ${RECIPIENT} | SUBJECT: ${SUBJECT}" >> "${LOG_FILE}"
echo "  MESSAGE: ${MESSAGE}" >> "${LOG_FILE}"
echo "---" >> "${LOG_FILE}"

# Aquí puedes agregar integraciones adicionales:
# - Enviar a Telegram
# - Enviar a Slack/Discord  
# - Enviar por email con sendmail
# - Llamar a un webhook HTTP

# Ejemplo: Notificar al automation-engine vía HTTP
# curl -s -X POST http://automation-engine:8000/alert \
#   -H "Content-Type: application/json" \
#   -d "{\"subject\": \"${SUBJECT}\", \"message\": \"${MESSAGE}\"}"

exit 0
