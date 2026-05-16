"""
╔══════════════════════════════════════════════════════════════╗
║          Motor de Automatización Failover UAGRM             ║
║   Monitoreo Zabbix → Detección de Fallas → Ansible Action   ║
╚══════════════════════════════════════════════════════════════╝

Este motor se conecta a la API de Zabbix para detectar problemas
de conectividad ICMP y ejecuta playbooks de Ansible para realizar
failover/failback automático de rutas en routers Cisco.

Características:
  - Logging profesional con rotación de archivos
  - Estado persistente (sobrevive reinicios del contenedor)
  - Healthcheck HTTP en puerto 8000
  - Reintentos con backoff exponencial para Zabbix API
  - Cooldown configurable entre operaciones
  - Métricas de eventos procesados
  - Generación dinámica de inventario Ansible
"""

import os
import sys
import json
import time
import logging
import signal
import subprocess
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from logging.handlers import RotatingFileHandler

from pyzabbix import ZabbixAPI


# ============================================================
#  Configuración desde Variables de Entorno
# ============================================================
class Config:
    """Configuración centralizada del motor."""

    ZABBIX_URL = os.getenv("ZABBIX_URL", "http://zabbix-web:8080")
    ZABBIX_USER = os.getenv("ZABBIX_USER", "Admin")
    ZABBIX_PASSWORD = os.getenv("ZABBIX_PASSWORD", "zabbix")

    POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))
    FAILOVER_COOLDOWN = int(os.getenv("FAILOVER_COOLDOWN", "30"))
    STATE_FILE = os.getenv("STATE_FILE", "/app/data/engine_state.json")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    ROUTER_IP = os.getenv("ROUTER_IP", "10.50.0.100")
    ROUTER_USER = os.getenv("ROUTER_USER", "admin")
    ROUTER_PASSWORD = os.getenv("ROUTER_PASSWORD", "cisco")
    PRIMARY_GATEWAY = os.getenv("PRIMARY_GATEWAY", "10.0.1.2")
    BACKUP_GATEWAY = os.getenv("BACKUP_GATEWAY", "10.0.2.2")

    TRIGGER_KEYWORD = "ICMP"  # Palabra clave para detectar triggers de ping

    HEALTHCHECK_PORT = 8000


# ============================================================
#  Logging Profesional
# ============================================================
def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configura logging con formato profesional y rotación de archivos."""
    logger = logging.getLogger("failover-engine")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter(
        fmt="%(asctime)s │ %(levelname)-7s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Consola
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Archivo con rotación (5 archivos de 2MB)
    log_dir = Path("/app/data")
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "engine.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


log = setup_logging(Config.LOG_LEVEL)


# ============================================================
#  Estado Persistente
# ============================================================
class EngineState:
    """Manejo de estado persistente que sobrevive reinicios."""

    def __init__(self, state_file: str):
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    def _load(self) -> dict:
        """Carga el estado desde disco."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    state = json.load(f)
                log.info(f"Estado restaurado desde {self.state_file}")
                return state
            except (json.JSONDecodeError, IOError) as e:
                log.warning(f"No se pudo leer estado previo: {e}")
        return self._default_state()

    def _default_state(self) -> dict:
        return {
            "en_failover": False,
            "last_failover_at": None,
            "last_failback_at": None,
            "total_failovers": 0,
            "total_failbacks": 0,
            "last_check_at": None,
            "consecutive_errors": 0,
            "engine_started_at": datetime.now(timezone.utc).isoformat()
        }

    def save(self):
        """Persiste el estado a disco."""
        try:
            with open(self.state_file, "w") as f:
                json.dump(self._state, f, indent=2, default=str)
        except IOError as e:
            log.error(f"Error guardando estado: {e}")

    @property
    def en_failover(self) -> bool:
        return self._state.get("en_failover", False)

    @en_failover.setter
    def en_failover(self, value: bool):
        self._state["en_failover"] = value
        self.save()

    def registrar_failover(self):
        self._state["en_failover"] = True
        self._state["last_failover_at"] = datetime.now(timezone.utc).isoformat()
        self._state["total_failovers"] += 1
        self._state["consecutive_errors"] = 0
        self.save()

    def registrar_failback(self):
        self._state["en_failover"] = False
        self._state["last_failback_at"] = datetime.now(timezone.utc).isoformat()
        self._state["total_failbacks"] += 1
        self._state["consecutive_errors"] = 0
        self.save()

    def registrar_check(self):
        self._state["last_check_at"] = datetime.now(timezone.utc).isoformat()
        self._state["consecutive_errors"] = 0
        self.save()

    def registrar_error(self):
        self._state["consecutive_errors"] = self._state.get("consecutive_errors", 0) + 1
        self.save()

    def to_dict(self) -> dict:
        return dict(self._state)


# ============================================================
#  Generador Dinámico de Inventario Ansible
# ============================================================
def generar_inventario():
    """Genera el inventario Ansible con datos del entorno."""
    contenido = f"""[router1]
{Config.ROUTER_IP} ansible_user={Config.ROUTER_USER} ansible_password={Config.ROUTER_PASSWORD} ansible_network_os=ios ansible_connection=network_cli ansible_command_timeout=60 ansible_ssh_common_args='-c aes256-cbc -o KexAlgorithms=+diffie-hellman-group14-sha1 -o HostKeyAlgorithms=+ssh-rsa -o StrictHostKeyChecking=no'

[router1:vars]
primary_gateway={Config.PRIMARY_GATEWAY}
backup_gateway={Config.BACKUP_GATEWAY}
"""
    hosts_path = Path("/app/hosts.ini")
    hosts_path.write_text(contenido)
    log.debug("Inventario Ansible generado dinámicamente")


# ============================================================
#  Healthcheck HTTP Server
# ============================================================
class HealthHandler(BaseHTTPRequestHandler):
    """Handler HTTP para healthcheck y métricas."""

    engine_state: EngineState = None  # Se inyecta después

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {
                "status": "healthy",
                "service": "failover-engine",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            self.wfile.write(json.dumps(response).encode())

        elif self.path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            state = self.engine_state.to_dict() if self.engine_state else {}
            response = {
                "service": "failover-engine-uagrm",
                "state": state,
                "config": {
                    "poll_interval": Config.POLL_INTERVAL,
                    "cooldown": Config.FAILOVER_COOLDOWN,
                    "router_ip": Config.ROUTER_IP,
                    "primary_gw": Config.PRIMARY_GATEWAY,
                    "backup_gw": Config.BACKUP_GATEWAY,
                }
            }
            self.wfile.write(json.dumps(response, indent=2).encode())

        elif self.path == "/metrics":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            state = self.engine_state.to_dict() if self.engine_state else {}
            metrics = (
                f"# HELP failover_total Total de failovers ejecutados\n"
                f"failover_total {state.get('total_failovers', 0)}\n"
                f"# HELP failback_total Total de failbacks ejecutados\n"
                f"failback_total {state.get('total_failbacks', 0)}\n"
                f"# HELP engine_errors_consecutive Errores consecutivos\n"
                f"engine_errors_consecutive {state.get('consecutive_errors', 0)}\n"
                f"# HELP engine_in_failover Estado actual de failover\n"
                f"engine_in_failover {1 if state.get('en_failover') else 0}\n"
            )
            self.wfile.write(metrics.encode())

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Silencia los logs del servidor HTTP para no ensuciar los del motor."""
        pass


def iniciar_healthcheck(state: EngineState):
    """Inicia el servidor HTTP de healthcheck en un hilo separado."""
    HealthHandler.engine_state = state
    server = HTTPServer(("0.0.0.0", Config.HEALTHCHECK_PORT), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info(f"Healthcheck HTTP activo en puerto {Config.HEALTHCHECK_PORT}")
    log.info(f"  → GET /health   — Estado de salud")
    log.info(f"  → GET /status   — Estado completo del motor")
    log.info(f"  → GET /metrics  — Métricas Prometheus-compatible")


# ============================================================
#  Conexión a Zabbix con Reintentos
# ============================================================
def conectar_zabbix(max_retries: int = 5) -> ZabbixAPI:
    """Conecta a la API de Zabbix con backoff exponencial."""
    for intento in range(1, max_retries + 1):
        try:
            zapi = ZabbixAPI(Config.ZABBIX_URL)
            zapi.login(Config.ZABBIX_USER, Config.ZABBIX_PASSWORD)
            log.info(f"Conectado a Zabbix API v{zapi.api_version()}")
            return zapi
        except Exception as e:
            wait = min(2 ** intento, 60)
            log.warning(f"Intento {intento}/{max_retries} fallido: {e}")
            log.warning(f"Reintentando en {wait}s...")
            time.sleep(wait)

    log.error("No se pudo conectar a Zabbix después de todos los reintentos")
    return None


# ============================================================
#  Ejecución de Playbooks
# ============================================================
def ejecutar_playbook(nombre: str) -> bool:
    """Ejecuta un playbook de Ansible y retorna True si fue exitoso."""
    log.info(f"Ejecutando playbook: {nombre}")
    inicio = time.time()

    resultado = subprocess.run(
        ["ansible-playbook", "-i", "hosts.ini", nombre, "-v"],
        capture_output=True,
        text=True,
        timeout=120
    )

    duracion = round(time.time() - inicio, 2)

    if resultado.returncode == 0:
        log.info(f"Playbook {nombre} completado en {duracion}s")
        # Log selectivo del output
        for line in resultado.stdout.splitlines():
            if "changed" in line.lower() or "ok" in line.lower():
                log.debug(f"  → {line.strip()}")
        return True
    else:
        log.error(f"Playbook {nombre} FALLÓ en {duracion}s")
        log.error(f"  STDERR: {resultado.stderr.strip()}")
        for line in resultado.stdout.splitlines()[-5:]:
            log.error(f"  STDOUT: {line.strip()}")
        return False


# ============================================================
#  Ciclo Principal de Monitoreo
# ============================================================
def monitorear(state: EngineState):
    """Ciclo principal: consulta Zabbix y toma decisiones."""
    zapi = conectar_zabbix()
    if not zapi:
        state.registrar_error()
        return

    try:
        # Buscar triggers activos (value=1 = PROBLEM)
        triggers = zapi.trigger.get(
            filter={"value": 1},
            active=True,
            expandDescription=True,
            selectHosts=["host"],
            sortfield="lastchange",
            sortorder="DESC",
            limit=50
        )

        # Detectar falla ICMP
        hay_falla = False
        trigger_desc = ""
        for t in triggers:
            if Config.TRIGGER_KEYWORD.lower() in t["description"].lower():
                hay_falla = True
                trigger_desc = t["description"]
                hosts = [h["host"] for h in t.get("hosts", [])]
                log.warning(f"⚠ Trigger activo: {trigger_desc} (hosts: {', '.join(hosts)})")
                break

        state.registrar_check()

        # --- FAILOVER ---
        if hay_falla and not state.en_failover:
            log.critical("=" * 60)
            log.critical("  ¡FALLA CRÍTICA DETECTADA! Iniciando FAILOVER")
            log.critical(f"  Trigger: {trigger_desc}")
            log.critical("=" * 60)

            if ejecutar_playbook("failover.yml"):
                state.registrar_failover()
                log.info(f"✓ FAILOVER #{state.to_dict()['total_failovers']} completado")
                log.info(f"  Ruta cambiada: {Config.PRIMARY_GATEWAY} → {Config.BACKUP_GATEWAY}")
                log.info(f"  Cooldown: {Config.FAILOVER_COOLDOWN}s antes de próxima acción")
                time.sleep(Config.FAILOVER_COOLDOWN)
            else:
                log.error("✗ FAILOVER FALLÓ — Se reintentará en el próximo ciclo")
                state.registrar_error()

        # --- FAILBACK ---
        elif not hay_falla and state.en_failover:
            log.info("=" * 60)
            log.info("  Enlace principal restaurado — Iniciando FAILBACK")
            log.info("=" * 60)

            if ejecutar_playbook("failback.yml"):
                state.registrar_failback()
                log.info(f"✓ FAILBACK #{state.to_dict()['total_failbacks']} completado")
                log.info(f"  Ruta restaurada: {Config.BACKUP_GATEWAY} → {Config.PRIMARY_GATEWAY}")
                time.sleep(Config.FAILOVER_COOLDOWN)
            else:
                log.error("✗ FAILBACK FALLÓ — Se reintentará en el próximo ciclo")
                state.registrar_error()

        # --- ESPERANDO ---
        elif hay_falla and state.en_failover:
            log.info("⏳ Failover activo — Esperando restauración del enlace principal...")

        # --- ESTABLE ---
        else:
            log.info("✓ Red estable — Monitoreando...")

    except Exception as e:
        log.error(f"Error en ciclo de monitoreo: {e}", exc_info=True)
        state.registrar_error()


# ============================================================
#  Punto de Entrada
# ============================================================
def main():
    # Manejo de señales para shutdown limpio
    running = True

    def signal_handler(signum, frame):
        nonlocal running
        log.info(f"Señal {signum} recibida — Deteniendo motor...")
        running = False

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Banner
    log.info("╔══════════════════════════════════════════════════════════╗")
    log.info("║       Motor de Automatización Failover — UAGRM         ║")
    log.info("║       Failover + Failback Automático v2.0               ║")
    log.info("╠══════════════════════════════════════════════════════════╣")
    log.info(f"║  Zabbix:    {Config.ZABBIX_URL:<44}║")
    log.info(f"║  Router:    {Config.ROUTER_IP:<44}║")
    log.info(f"║  Primary:   {Config.PRIMARY_GATEWAY:<44}║")
    log.info(f"║  Backup:    {Config.BACKUP_GATEWAY:<44}║")
    log.info(f"║  Intervalo: {str(Config.POLL_INTERVAL) + 's':<44}║")
    log.info(f"║  Cooldown:  {str(Config.FAILOVER_COOLDOWN) + 's':<44}║")
    log.info("╚══════════════════════════════════════════════════════════╝")

    # Inicializar estado persistente
    state = EngineState(Config.STATE_FILE)
    if state.en_failover:
        log.warning("⚡ Motor reiniciado en estado FAILOVER — continuando monitoreo")

    # Generar inventario dinámico
    generar_inventario()

    # Iniciar healthcheck HTTP
    iniciar_healthcheck(state)

    # Loop principal
    log.info(f"Iniciando monitoreo (cada {Config.POLL_INTERVAL}s)...")
    while running:
        monitorear(state)
        time.sleep(Config.POLL_INTERVAL)

    log.info("Motor detenido correctamente")


if __name__ == "__main__":
    main()