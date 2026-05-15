# 🔄 Proyecto Failover Automático — UAGRM

> **Sistema de Failover/Failback automático** que integra Zabbix + Python + Ansible para conmutar rutas en routers Cisco cuando se detecta una caída de enlace.

---

## 📐 Arquitectura

```
┌──────────────────────────────────────────────────────────────┐
│                    Docker Compose Stack                       │
│                                                              │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ MySQL 8  │◄─│ Zabbix Server│─►│   Zabbix Web (8080)   │  │
│  │(zabbix-db)│ │   (backend)  │  │    (frontend)         │  │
│  └──────────┘  └──────┬───────┘  └───────────────────────┘  │
│                       │ API                                  │
│                       ▼                                      │
│             ┌───────────────────┐                            │
│             │ Automation Engine │──► /health  (8000)         │
│             │  (Python 3.10)    │──► /status                 │
│             │                   │──► /metrics                │
│             └────────┬──────────┘                            │
│                      │ SSH (Ansible)                         │
└──────────────────────┼───────────────────────────────────────┘
                       │ Red 10.50.0.0/16
                       │
                ┌──────┴──────┐
                │   R1 (GNS3) │
                │ 10.50.0.100 │ ← management (fa0/0)
                │ 10.0.1.1    │ ← enlace principal (fa1/0)
                │ 10.0.2.1    │ ← enlace respaldo  (fa1/1)
                └──┬──────┬───┘
          PRINCIPAL │      │ RESPALDO
        (10.0.1.0/24)    (10.0.2.0/24)
                   │      │
                ┌──┴──────┴───┐
                │   R2 (GNS3) │
                │ 10.0.1.2    │ ← enlace principal (fa1/0)
                │ 10.0.2.2    │ ← enlace respaldo  (fa1/1)
                └─────────────┘
```

## 🔁 Flujo de Operación

```
1. Zabbix monitorea ping ICMP a 10.0.1.2 (R2 por enlace principal)
2. Si el enlace principal cae → ping falla → Trigger PROBLEM
3. Automation Engine detecta el trigger vía Zabbix API
4. Ejecuta failover.yml (Ansible → SSH → R1):
   → Elimina ruta: ip route 0.0.0.0 0.0.0.0 10.0.1.2
   → Agrega ruta:  ip route 0.0.0.0 0.0.0.0 10.0.2.2
   → Guarda configuración en el router
5. Cuando el enlace se restaura → Zabbix confirma ping OK → Trigger RESOLVED
6. Ejecuta failback.yml (restaura ruta principal automáticamente)
```

## 🗂 Estructura del Proyecto

```
Proyecto_Failover/
├── docker-compose.yml          # Orquestación de todos los servicios
├── .env                        # Variables de entorno (NO commitear)
├── .env.example                # Plantilla de variables
├── .gitignore                  # Exclusiones de Git
├── README.md                   # Este archivo
│
├── automation-brain/           # Motor de automatización
│   ├── Dockerfile              # Imagen Python + Ansible
│   ├── requirements.txt        # Dependencias Python
│   ├── main.py                 # Motor principal (polling + decisiones)
│   ├── hosts.ini               # Inventario Ansible (generado dinámicamente)
│   ├── failover.yml            # Playbook: cambiar a ruta de respaldo
│   └── failback.yml            # Playbook: restaurar ruta principal
│
└── zabbix-config/              # Configuración de Zabbix
    ├── setup.sh                # Script de inicialización (legacy)
    ├── setup_zabbix.py         # Configuración automática vía API
    └── alertscripts/
        └── notify.sh           # Script de notificación de alertas
```

## 🚀 Despliegue Paso a Paso

### Prerrequisitos

- Docker + Docker Compose
- GNS3 con imagen de router Cisco IOS (ej: c7200, c3725)
- Conectividad entre Docker y GNS3 (red `10.50.0.0/16`)

---

### Paso 1: Clonar y Configurar

```bash
git clone <repo-url>
cd Proyecto_Failover

# Copiar y editar variables de entorno
cp .env.example .env
nano .env  # Ajustar IPs y contraseñas si es necesario
```

---

### Paso 2: Configurar la Topología GNS3

#### 2.1 Crear los dispositivos

1. Arrastrar **2 routers Cisco** (R1 y R2) al workspace
2. Arrastrar un **Cloud** y vincularlo a la interfaz Docker (`br-xxxxx`)
3. Conectar los cables:
   - **Cloud** `br-xxxx` ↔ **R1** `fa0/0` (management)
   - **R1** `fa1/0` ↔ **R2** `fa1/0` (enlace principal)
   - **R1** `fa1/1` ↔ **R2** `fa1/1` (enlace respaldo)

#### 2.2 Configurar R1 (Router Principal)

```
enable
configure terminal

hostname R1
ip domain-name lab.uagrm
crypto key generate rsa modulus 1024
username admin privilege 15 password cisco

line vty 0 4
  login local
  transport input ssh
exit

! Interfaz management → Docker
interface FastEthernet0/0
  ip address 10.50.0.100 255.255.0.0
  no shutdown
exit

! Enlace principal → R2
interface FastEthernet1/0
  ip address 10.0.1.1 255.255.255.0
  no shutdown
exit

! Enlace respaldo → R2
interface FastEthernet1/1
  ip address 10.0.2.1 255.255.255.0
  no shutdown
exit

! Ruta default por enlace principal
ip route 0.0.0.0 0.0.0.0 10.0.1.2

end
write memory
```

#### 2.3 Configurar R2 (Router Destino)

```
enable
configure terminal

hostname R2

! Enlace principal → R1
interface FastEthernet1/0
  ip address 10.0.1.2 255.255.255.0
  no shutdown
exit

! Enlace respaldo → R1
interface FastEthernet1/1
  ip address 10.0.2.2 255.255.255.0
  no shutdown
exit

! ⚠️ IMPORTANTE: Ruta de retorno hacia Docker (a través de R1)
ip route 10.50.0.0 255.255.0.0 10.0.1.1

end
write memory
```

> ⚠️ **Sin la ruta de retorno en R2**, los pings de Zabbix llegarán a R2 pero las respuestas se perderán porque R2 no sabe cómo alcanzar la red Docker `10.50.0.0/16`.

---

### Paso 3: Levantar Docker

```bash
docker compose up -d --build
```

Esperar ~2 minutos a que todos los servicios estén healthy:

```bash
docker compose ps
```

---

### Paso 4: Agregar Ruta en Zabbix Server

El contenedor de Zabbix necesita saber cómo llegar a la red `10.0.1.0/24` a través de R1:

```bash
docker compose exec --user root zabbix-server bash -c \
  "apt-get update -qq && apt-get install -y -qq iproute2 2>/dev/null && \
   ip route add 10.0.1.0/24 via 10.50.0.100 && \
   ip route add 10.0.2.0/24 via 10.50.0.100 && \
   echo '✓ Rutas agregadas'"
```

> ⚠️ **Esta ruta se pierde al reiniciar el contenedor.** Ejecutar de nuevo si se hace `docker compose down/up`.

---

### Paso 5: Configurar Zabbix Web

1. Abrir **http://localhost:8080** (Admin / zabbix)

2. **Crear Host Group:**
   - `Data collection` → `Host groups` → `Create host group`
   - Nombre: `GNS3 Routers` → Click `Add`

3. **Crear Host para monitorear el enlace principal:**
   - `Data collection` → `Hosts` → `Create host`
   - **Host name:** `Router-R1-GNS3`
   - **Templates:** buscar y seleccionar `ICMP Ping`
   - **Host groups:** `GNS3 Routers`
   - **Interfaces:** Click `Add` → `Agent` → IP: **`10.0.1.2`** → Port: `10050`
   - Click `Add` para guardar

4. Esperar 2-3 minutos hasta que el host esté **🟢 verde** en `Monitoring → Hosts`

---

### Paso 6: Verificar

```bash
# Ver logs del motor
docker compose logs -f automation-engine

# Healthcheck
curl http://localhost:8000/health

# Estado completo
curl http://localhost:8000/status

# Métricas
curl http://localhost:8000/metrics
```

Cuando todo funcione, deberías ver:
```
✓ Red estable — Monitoreando...
```

---

### Paso 7: Probar el Failover 🧪

**Simular caída del enlace principal** (en consola de R1 en GNS3):
```
enable
configure terminal
interface FastEthernet1/0
  shutdown
end
```

**Resultado esperado (~1-2 min):**
```
⚠ Trigger activo: ICMP Ping: Unavailable by ICMP ping
¡FALLA CRÍTICA DETECTADA! Iniciando FAILOVER
✓ FAILOVER #1 completado
  Ruta cambiada: 10.0.1.2 → 10.0.2.2
```

**Restaurar el enlace** (en consola de R1):
```
enable
configure terminal
interface FastEthernet1/0
  no shutdown
end
```

**Resultado esperado (~1-2 min):**
```
Enlace principal restaurado — Iniciando FAILBACK
✓ FAILBACK #1 completado
  Ruta restaurada: 10.0.2.2 → 10.0.1.2
✓ Red estable — Monitoreando...
```

---

## ⚙️ Configuración

### Variables de Entorno (`.env`)

| Variable | Default | Descripción |
|---|---|---|
| `ZABBIX_URL` | `http://zabbix-web:8080` | URL interna de la API de Zabbix |
| `ZABBIX_USER` | `Admin` | Usuario de la API |
| `ZABBIX_PASSWORD` | `zabbix` | Contraseña de la API |
| `POLL_INTERVAL` | `10` | Segundos entre cada consulta a Zabbix |
| `FAILOVER_COOLDOWN` | `30` | Segundos de espera después de un failover/failback |
| `ROUTER_IP` | `10.50.0.100` | IP de management de R1 (para Ansible SSH) |
| `ROUTER_USER` | `admin` | Usuario SSH del router |
| `ROUTER_PASSWORD` | `cisco` | Contraseña SSH del router |
| `PRIMARY_GATEWAY` | `10.0.1.2` | Gateway del enlace principal |
| `BACKUP_GATEWAY` | `10.0.2.2` | Gateway del enlace de respaldo |

## 📊 Endpoints del Motor

| Endpoint | Método | Descripción |
|---|---|---|
| `/health` | GET | Healthcheck simple (200 = OK) |
| `/status` | GET | Estado completo del motor en JSON |
| `/metrics` | GET | Métricas Prometheus-compatible |

### Ejemplo de `/status`

```json
{
  "service": "failover-engine-uagrm",
  "state": {
    "en_failover": false,
    "last_failover_at": "2026-05-15T18:45:57Z",
    "last_failback_at": "2026-05-15T18:46:53Z",
    "total_failovers": 1,
    "total_failbacks": 1,
    "consecutive_errors": 0
  },
  "config": {
    "poll_interval": 10,
    "cooldown": 30,
    "router_ip": "10.50.0.100"
  }
}
```

## 🔍 Troubleshooting

| Problema | Solución |
|---|---|
| Motor dice "Buscando a Zabbix..." | Normal los primeros 1-2 min. Esperar a que `zabbix-web` esté healthy |
| Zabbix no puede hacer ping a 10.0.1.2 | Ejecutar el comando de rutas del Paso 4 |
| R2 no responde pings de Zabbix | Verificar que R2 tenga la ruta de retorno: `ip route 10.50.0.0 255.255.0.0 10.0.1.1` |
| Host en Zabbix está gris | Esperar 2-3 min, Zabbix aún no ha intentado monitorear |
| Host en Zabbix está rojo | R2 no es alcanzable. Verificar cables y configuración |
| Ansible no conecta al router | Verificar que R1 tenga SSH habilitado y las credenciales sean correctas |
| Failover no se ejecuta | Verificar en Zabbix Web → Monitoring → Problems que el trigger ICMP aparezca |
| Estado del motor atascado | Resetear: `docker compose exec automation-engine python3 -c "import json; json.dump({'en_failover':False,'total_failovers':0,'total_failbacks':0,'last_failover_at':None,'last_failback_at':None,'last_check_at':None,'consecutive_errors':0,'engine_started_at':'now'}, open('/app/data/engine_state.json','w'))"` |
| Rutas perdidas tras reinicio de Docker | Volver a ejecutar el comando del Paso 4 |

## 📝 Logs

- **Consola:** `docker compose logs -f automation-engine`
- **Archivo:** `/app/data/engine.log` dentro del contenedor (rotación automática 5×2MB)

---

**Universidad Autónoma Gabriel René Moreno — Redes de Computadoras**
