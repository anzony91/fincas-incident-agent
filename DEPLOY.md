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

# IMAP
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USER=fincas.madrid.incidencias@gmail.com
IMAP_PASSWORD=tu-app-password

# SMTP  
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=fincas.madrid.incidencias@gmail.com
SMTP_PASSWORD=tu-app-password
FROM_EMAIL=fincas.madrid.incidencias@gmail.com
FROM_NAME=Administración de Fincas

# App
POLL_INTERVAL_SECONDS=60
DEBUG=false
LOG_LEVEL=INFO
ATTACHMENTS_PATH=/app/data/attachments
EOF
```

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
