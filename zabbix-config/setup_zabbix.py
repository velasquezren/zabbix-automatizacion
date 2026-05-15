"""
╔══════════════════════════════════════════════════════════════╗
║     Configuración Automática de Zabbix vía API              ║
║     Crea hosts, templates, triggers y acciones              ║
╚══════════════════════════════════════════════════════════════╝

Ejecutar después de que Zabbix esté completamente inicializado:
  python setup_zabbix.py

Operaciones:
  1. Crea el Host Group "GNS3 Routers"
  2. Registra el Router como host con interfaz SNMP/Agent
  3. Asocia el template de ICMP ping
  4. Crea una Acción que ejecuta un script remoto al detectar falla
"""

import os
import sys
import time
import json
from pyzabbix import ZabbixAPI

# ============================================================
#  Configuración
# ============================================================
ZABBIX_URL = os.getenv("ZABBIX_URL", "http://zabbix-web:8080")
ZABBIX_USER = os.getenv("ZABBIX_USER", "Admin")
ZABBIX_PASSWORD = os.getenv("ZABBIX_PASSWORD", "zabbix")

ROUTER_IP = os.getenv("ROUTER_IP", "10.50.0.100")
ROUTER_NAME = os.getenv("ROUTER_NAME", "Router-R1-GNS3")
HOST_GROUP_NAME = "GNS3 Routers"
ICMP_TEMPLATE = "ICMP Ping"  # Template incluido por defecto en Zabbix 7.0


def esperar_zabbix(url: str, max_intentos: int = 30):
    """Espera a que Zabbix esté listo para recibir conexiones."""
    print(f"⏳ Esperando a que Zabbix esté disponible en {url}...")
    for i in range(1, max_intentos + 1):
        try:
            zapi = ZabbixAPI(url)
            zapi.login(ZABBIX_USER, ZABBIX_PASSWORD)
            print(f"✓ Conectado a Zabbix API v{zapi.api_version()}")
            return zapi
        except Exception as e:
            wait = min(2 ** min(i, 6), 60)
            print(f"  Intento {i}/{max_intentos}: {e}")
            print(f"  Reintentando en {wait}s...")
            time.sleep(wait)

    print("✗ No se pudo conectar a Zabbix.")
    sys.exit(1)


def obtener_o_crear_hostgroup(zapi: ZabbixAPI, nombre: str) -> str:
    """Obtiene o crea un Host Group y retorna su ID."""
    grupos = zapi.hostgroup.get(filter={"name": nombre})
    if grupos:
        gid = grupos[0]["groupid"]
        print(f"  ℹ Host Group '{nombre}' ya existe (ID: {gid})")
        return gid

    resultado = zapi.hostgroup.create(name=nombre)
    gid = resultado["groupids"][0]
    print(f"  ✓ Host Group '{nombre}' creado (ID: {gid})")
    return gid


def obtener_template_id(zapi: ZabbixAPI, nombre: str) -> str:
    """Busca un template por nombre y retorna su ID."""
    templates = zapi.template.get(filter={"host": nombre})
    if not templates:
        # Intentar búsqueda parcial
        templates = zapi.template.get(search={"host": nombre})

    if templates:
        tid = templates[0]["templateid"]
        print(f"  ℹ Template '{nombre}' encontrado (ID: {tid})")
        return tid

    print(f"  ⚠ Template '{nombre}' no encontrado — se usará monitoreo básico")
    return None


def registrar_router(zapi: ZabbixAPI, group_id: str, template_id: str = None) -> str:
    """Registra el router como host en Zabbix."""
    # Verificar si ya existe
    hosts = zapi.host.get(filter={"host": ROUTER_NAME})
    if hosts:
        hid = hosts[0]["hostid"]
        print(f"  ℹ Host '{ROUTER_NAME}' ya existe (ID: {hid})")
        return hid

    host_params = {
        "host": ROUTER_NAME,
        "name": f"🌐 {ROUTER_NAME}",
        "groups": [{"groupid": group_id}],
        "interfaces": [
            {
                "type": 2,       # SNMP
                "main": 1,       # Interfaz principal
                "useip": 1,
                "ip": ROUTER_IP,
                "dns": "",
                "port": "161",
                "details": {
                    "version": 2,        # SNMPv2c
                    "community": "{$SNMP_COMMUNITY}"
                }
            }
        ],
        "description": "Router principal GNS3 - Monitoreo de failover automático"
    }

    if template_id:
        host_params["templates"] = [{"templateid": template_id}]

    resultado = zapi.host.create(**host_params)
    hid = resultado["hostids"][0]
    print(f"  ✓ Host '{ROUTER_NAME}' registrado (ID: {hid}, IP: {ROUTER_IP})")
    return hid


def crear_accion_failover(zapi: ZabbixAPI):
    """Crea una acción que notifica cuando hay un problema de ICMP."""
    nombre_accion = "Failover - ICMP Ping Failed"

    # Verificar si ya existe
    acciones = zapi.action.get(filter={"name": nombre_accion})
    if acciones:
        print(f"  ℹ Acción '{nombre_accion}' ya existe (ID: {acciones[0]['actionid']})")
        return

    try:
        resultado = zapi.action.create(
            name=nombre_accion,
            eventsource=0,   # Triggers
            status=0,        # Habilitada
            esc_period="60s",
            filter={
                "evaltype": 0,  # AND/OR
                "conditions": [
                    {
                        "conditiontype": 4,    # Trigger severity
                        "operator": 5,         # >= 
                        "value": "4"           # High
                    },
                    {
                        "conditiontype": 2,    # Trigger name
                        "operator": 2,         # Contains
                        "value": "ICMP"
                    }
                ]
            },
            operations=[
                {
                    "operationtype": 0,  # Send message
                    "opmessage": {
                        "default_msg": 1,
                        "mediatypeid": "0"
                    },
                    "opmessage_grp": [
                        {"usrgrpid": "7"}   # Zabbix administrators
                    ]
                }
            ],
            recovery_operations=[
                {
                    "operationtype": 11,  # Send recovery message
                    "opmessage": {
                        "default_msg": 1,
                        "mediatypeid": "0"
                    }
                }
            ]
        )
        print(f"  ✓ Acción '{nombre_accion}' creada (ID: {resultado['actionids'][0]})")
    except Exception as e:
        print(f"  ⚠ No se pudo crear la acción: {e}")
        print(f"    (Puedes crearla manualmente desde la interfaz web)")


def main():
    print("=" * 60)
    print("  Configuración Automática de Zabbix")
    print("  Proyecto Failover UAGRM")
    print("=" * 60)

    # 1. Conectar
    zapi = esperar_zabbix(ZABBIX_URL)

    # 2. Crear Host Group
    print("\n📁 Configurando Host Group...")
    group_id = obtener_o_crear_hostgroup(zapi, HOST_GROUP_NAME)

    # 3. Buscar template ICMP
    print("\n📋 Buscando template ICMP...")
    template_id = obtener_template_id(zapi, ICMP_TEMPLATE)

    # 4. Registrar Router
    print("\n🖧 Registrando Router...")
    host_id = registrar_router(zapi, group_id, template_id)

    # 5. Crear Acción de Failover
    print("\n⚡ Configurando Acción de Failover...")
    crear_accion_failover(zapi)

    # Resumen
    print("\n" + "=" * 60)
    print("  ✓ Configuración completada")
    print(f"  → Host Group: {HOST_GROUP_NAME} (ID: {group_id})")
    print(f"  → Router:     {ROUTER_NAME} (ID: {host_id})")
    print(f"  → Template:   {ICMP_TEMPLATE}")
    print(f"  → Acción:     Failover - ICMP Ping Failed")
    print("=" * 60)
    print("\n💡 Accede a Zabbix Web en: http://localhost:8080")
    print("   Usuario: Admin / Contraseña: zabbix")


if __name__ == "__main__":
    main()
