# Fincas Incident Agent - Production VPS Setup

## Requisitos del servidor
- Ubuntu 22.04+ o Debian 12+
- 1GB RAM mínimo (2GB recomendado)
- 20GB disco

## 1. Setup inicial del VPS

```bash
# Actualizar sistema
sudo apt update && sudo apt upgrade -y

# Instalar Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Instalar Docker Compose
sudo apt install docker-compose-plugin -y

# Crear directorio
sudo mkdir -p /opt/fincas-incident-agent
cd /opt/fincas-incident-agent
```

## 2. Clonar y configurar

```bash
# Clonar repositorio
git clone https://github.com/TU_USUARIO/fincas-incident-agent.git .

# Crear archivo .env
cat > .env << 'EOF'
# Domain
DOMAIN=fincas.tudominio.com
ACME_EMAIL=tu@email.com

# Database
DB_PASSWORD=tu_password_seguro_aqui

# ===== EMAIL CONFIGURATION (Resend - RECOMMENDED) =====
# Resend handles BOTH sending and receiving emails via webhook
# No IMAP needed anymore!
EMAIL_PROVIDER=resend
RESEND_API_KEY=re_xxxxxxxxxxxx
# Webhook secret from Resend dashboard (optional but recommended)
RESEND_WEBHOOK_SECRET=whsec_xxxxxxxxxxxx

# From address (must be verified domain in Resend)
FROM_EMAIL=incidencias@adminsavia.com
FROM_NAME=AdminSavia

# App
DEBUG=false
LOG_LEVEL=INFO
ATTACHMENTS_PATH=/app/data/attachments
EOF
```

### Configuración de Resend Inbound (recibir emails)

1. Ve a [Resend Dashboard](https://resend.com/webhooks)
2. Crea un nuevo webhook:
   - **Endpoint URL:** `https://tu-dominio.com/api/resend/webhook`
   - **Events:** Selecciona `email.received`
3. Copia el **Webhook Secret** y añádelo como `RESEND_WEBHOOK_SECRET`
4. Configura los registros MX en tu dominio para que apunten a Resend:
   - **MX Record:** `feedback-smtp.us-east-1.amazonses.com` (Priority: 10)
   
> **Nota:** Consulta la documentación de Resend para los registros MX actualizados según tu región.

## 3. Desplegar

```bash
# Iniciar servicios
docker compose -f docker-compose.prod.yml up -d

# Ver logs
docker compose -f docker-compose.prod.yml logs -f app

# Ejecutar migraciones
docker compose -f docker-compose.prod.yml exec app alembic upgrade head
```

## 4. Configurar DNS

Añade un registro A en tu proveedor DNS:
```
fincas.tudominio.com -> IP_DE_TU_VPS
```

## 5. Comandos útiles

```bash
# Ver estado
docker compose -f docker-compose.prod.yml ps

# Reiniciar app  
docker compose -f docker-compose.prod.yml restart app

# Ver logs del email worker
docker compose -f docker-compose.prod.yml logs -f app | grep -i email

# Backup manual
docker compose -f docker-compose.prod.yml exec backup /backup.sh

# Actualizar a nueva versión
git pull origin main
docker compose -f docker-compose.prod.yml up -d --build
```

## 6. Monitoreo (opcional)

Para monitoreo básico, añade:
- **Uptime Kuma** - Health checks y alertas
- **Grafana + Prometheus** - Métricas detalladas

## Proveedores VPS recomendados

| Proveedor | Precio | Especificaciones |
|-----------|--------|------------------|
| Hetzner | €4.51/mes | 2GB RAM, 20GB SSD |
| DigitalOcean | $6/mes | 1GB RAM, 25GB SSD |
| Contabo | €4.99/mes | 4GB RAM, 50GB SSD |
| OVH | €3.50/mes | 2GB RAM, 20GB SSD |

## Seguridad

```bash
# Firewall básico
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp  
sudo ufw allow 443/tcp
sudo ufw enable

# Fail2ban para proteger SSH
sudo apt install fail2ban -y
sudo systemctl enable fail2ban
```
