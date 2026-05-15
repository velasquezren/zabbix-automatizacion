import time
import subprocess
from pyzabbix import ZabbixAPI

ZABBIX_URL = "http://zabbix-web:8080"
ZABBIX_USER = "Admin"
ZABBIX_PASS = "zabbix" # Contraseña por defecto de la web de Zabbix

# Estado del sistema: False = ruta principal, True = ruta de respaldo
en_failover = False

def monitorear_fallas():
    global en_failover
    try:
        zapi = ZabbixAPI(ZABBIX_URL)
        zapi.login(ZABBIX_USER, ZABBIX_PASS)
        
        # Buscar problemas activos
        triggers = zapi.trigger.get(filter={'value': 1}, active=1, expandDescription=1)
        
        # Verificar si hay falla de ICMP activa
        hay_falla = False
        for t in triggers:
            if "ICMP Ping: Unavailable by ICMP ping" in t['description']:
                hay_falla = True
                break
        
        if hay_falla and not en_failover:
            # ============================================
            # FAILOVER: Se cayó el enlace principal
            # ============================================
            print(f"[*] ¡Falla Crítica Detectada!: ICMP Ping: Unavailable by ICMP ping")
            print("[*] Ejecutando Failover: Cambiando a ruta de respaldo...")
            resultado = subprocess.run(
                ["ansible-playbook", "-i", "hosts.ini", "failover.yml"],
                capture_output=True, text=True
            )
            if resultado.returncode == 0:
                print("[✓] Failover completado exitosamente. R1 ahora usa ruta de respaldo (10.0.2.2)")
                en_failover = True
            else:
                print(f"[✗] Error en Failover: {resultado.stderr}")

        elif not hay_falla and en_failover:
            # ============================================
            # FAILBACK: El enlace principal se restauró
            # ============================================
            print("[*] ¡Enlace principal restaurado! Zabbix reporta conexión OK.")
            print("[*] Ejecutando Failback: Volviendo a ruta principal...")
            resultado = subprocess.run(
                ["ansible-playbook", "-i", "hosts.ini", "failback.yml"],
                capture_output=True, text=True
            )
            if resultado.returncode == 0:
                print("[✓] Failback completado. R1 volvió a ruta principal (10.0.1.2)")
                en_failover = False
            else:
                print(f"[✗] Error en Failback: {resultado.stderr}")

        elif hay_falla and en_failover:
            # Ya hicimos el failover, esperando a que se resuelva
            print("[~] Failover activo. Esperando restauración del enlace principal...")

        else:
            # Todo tranquilo, no hay fallas
            print("[OK] Red estable. Monitoreando...")
                
    except Exception as e:
        print(f"Buscando a Zabbix... ({e})")

if __name__ == "__main__":
    print("=" * 50)
    print("  Motor de Automatización UAGRM")
    print("  Failover + Failback Automático")
    print("=" * 50)
    while True:
        monitorear_fallas()
        time.sleep(10) # Monitorea cada 10 segundos