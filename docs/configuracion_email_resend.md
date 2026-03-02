# Guía de Configuración de Email Profesional con Resend

## Problema Actual
Los emails enviados desde Gmail sin dominio verificado se clasifican como SPAM porque:
- No hay registros SPF/DKIM/DMARC
- Gmail bloquea el reenvío desde servidores externos
- Los filtros de spam detectan "spoofing" de dirección

## Solución: Resend + Dominio Propio

### Costes Estimados
- **Dominio**: ~10-15€/año
- **Resend**: Gratis hasta 3000 emails/mes, luego $20/mes (50k emails)

---

## PASO 1: Comprar Dominio

### Proveedores Recomendados
| Proveedor | URL | Precio .es/.com |
|-----------|-----|-----------------|
| Namecheap | namecheap.com | ~10€/año |
| Porkbun | porkbun.com | ~9€/año |
| Cloudflare | cloudflare.com | ~8€/año |
| Google Domains | domains.google | ~12€/año |

### Sugerencias de Nombre
- `administracionfincas.es`
- `gestionincidencias.es`
- `[tunombre]fincas.com`
- `[nombreempresa].es`

---

## PASO 2: Crear Cuenta en Resend

1. Ir a https://resend.com
2. Clic en "Get Started" → Crear cuenta
3. Verificar email
4. Ir a **API Keys** en el menú lateral
5. Clic **Create API Key**
6. Copiar y guardar la API Key (formato: `re_xxxxxxxxx`)

---

## PASO 3: Añadir y Verificar Dominio

### En Resend:
1. Ir a **Domains** → **Add Domain**
2. Introducir tu dominio (ej: `tuempresa.es`)
3. Resend mostrará 3 registros DNS que necesitas añadir

### Registros DNS Requeridos:

#### 1. Verificación de dominio
```
Tipo:   TXT
Host:   @  (o dejar vacío)
Valor:  resend-verify=xxxxxxxx
TTL:    3600 (o automático)
```

#### 2. SPF (autoriza a Resend a enviar emails)
```
Tipo:   TXT
Host:   @  (o dejar vacío)
Valor:  v=spf1 include:_spf.resend.com ~all
TTL:    3600
```

#### 3. DKIM (firma digital)
```
Tipo:   CNAME
Host:   resend._domainkey
Valor:  [proporcionado por Resend]
TTL:    3600
```

### Cómo añadir registros DNS:

**En Namecheap:**
1. Ir a Domain List → Manage
2. Advanced DNS
3. Add New Record

**En Cloudflare:**
1. Seleccionar dominio
2. DNS → Records
3. Add record

**En Google Domains:**
1. DNS → Default name servers
2. Manage custom records

### Verificar:
- Esperar 5-30 minutos (puede tardar hasta 48h)
- En Resend, clic en **Verify**
- Estado debe cambiar a ✅ Verified

---

## PASO 4: Configurar Railway

### Variables de entorno a añadir/modificar:

```env
# Cambiar el proveedor a Resend
EMAIL_PROVIDER=resend

# Tu API Key de Resend
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxxxxxxxx

# Email de origen (debe ser de tu dominio verificado)
FROM_EMAIL=incidencias@tudominio.es

# Nombre que aparecerá como remitente
FROM_NAME=Administración de Fincas
```

### En Railway:
1. Ir a tu proyecto
2. Variables → Raw Editor (o añadir una a una)
3. Añadir las 4 variables
4. El servicio se reiniciará automáticamente

---

## PASO 5: (Recomendado) Añadir DMARC

DMARC mejora la deliverability y protege contra spoofing.

```
Tipo:   TXT
Host:   _dmarc
Valor:  v=DMARC1; p=none; rua=mailto:dmarc@tudominio.es
TTL:    3600
```

---

## PASO 6: Probar

1. Crear una incidencia de prueba desde WhatsApp o el formulario web
2. Verificar que el email llega correctamente
3. Revisar que NO está en spam
4. Verificar que el remitente aparece como `incidencias@tudominio.es`

---

## Troubleshooting

### El email sigue llegando a spam
- Verificar que todos los registros DNS están correctos
- Esperar 24-48h para la propagación DNS
- Verificar en https://mxtoolbox.com que SPF y DKIM están configurados

### Error "Domain not verified"
- El dominio aún no está verificado en Resend
- Revisar registros DNS
- En Resend, hacer clic en "Verify" de nuevo

### Error de API Key
- Verificar que la API Key empieza con `re_`
- Verificar que no hay espacios al inicio/final
- Crear una nueva API Key si es necesario

---

## Resumen de Variables Finales

```env
# Email Configuration
EMAIL_PROVIDER=resend
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxxxxxxxx
FROM_EMAIL=incidencias@tudominio.es
FROM_NAME=Administración de Fincas

# IMAP (para recibir emails - mantener Gmail)
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USER=tu.email@gmail.com
IMAP_PASSWORD=xxxx xxxx xxxx xxxx  # App Password

# Las variables SMTP ya no son necesarias si usas Resend
```

---

## Beneficios de esta configuración

✅ **Emails NO van a spam** - Dominio verificado con SPF/DKIM/DMARC
✅ **Aspecto profesional** - `incidencias@tuempresa.es` vs `usuario@gmail.com`
✅ **Alta deliverability** - Resend tiene excelente reputación
✅ **Sin bloqueos de puertos** - API HTTP, no SMTP
✅ **Dashboard de métricas** - Ver emails enviados, abiertos, rebotados

---

*Documento generado: Marzo 2026*
