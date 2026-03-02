# Sistema de Gestión de Incidencias de Fincas
## Manual de Interacciones de Usuario

**Versión:** 1.0  
**Fecha:** Febrero 2026

---

## 1. Introducción

Este documento describe las diferentes formas en que los usuarios (vecinos/propietarios) pueden interactuar con el sistema de gestión de incidencias de administración de fincas.

El sistema ofrece **tres canales principales** de comunicación:
1. **WhatsApp** - Canal conversacional con IA
2. **Formulario Web** - Formulario público online
3. **Email** - Integración con correo electrónico

---

## 2. Canal WhatsApp

### 2.1 Descripción General

Los usuarios pueden reportar incidencias y consultar el estado de sus tickets enviando mensajes de WhatsApp al número configurado de la administración.

El sistema utiliza **Inteligencia Artificial** para entender la intención del usuario y responder de forma conversacional.

### 2.2 Intenciones Detectadas

El sistema puede detectar automáticamente las siguientes intenciones:

| Intención | Descripción | Ejemplo de mensaje |
|-----------|-------------|-------------------|
| **GREETING** | Saludo simple | "Hola", "Buenos días" |
| **NEW_INCIDENT** | Reportar un problema | "La luz del portal no funciona" |
| **CHECK_STATUS** | Consultar estado de incidencias | "¿Cómo va mi incidencia?", "Estado" |
| **PROVIDE_INFO** | Proporcionar información solicitada | "Mi dirección es Calle Mayor 15" |
| **CONFIRM_DATA** | Confirmar datos correctos | "Sí, correcto", "Ok" |
| **OFF_TOPIC** | Pregunta no relacionada | Preguntas sobre clima, política, etc. |

### 2.3 Flujo de Reportar Nueva Incidencia

```
┌─────────────────────────────────────────────────────────────┐
│                    USUARIO ENVÍA MENSAJE                     │
│         "Tengo una fuga de agua en el baño"                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              IA DETECTA INTENCIÓN: NEW_INCIDENT              │
│         - Extrae descripción del problema                    │
│         - Clasifica categoría (WATER)                        │
│         - Determina prioridad                                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 SE CREA TICKET (INC-XXXXXX)                  │
│         - Estado: NEW o NEEDS_INFO                           │
│         - Canal: WHATSAPP                                    │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│    INFO COMPLETA        │     │   FALTA INFORMACIÓN     │
│                         │     │                         │
│ ✅ Se notifica al       │     │ ⚠️ Se solicita:         │
│    proveedor            │     │   - Dirección           │
│                         │     │   - Piso/Puerta         │
│ ✅ Usuario recibe       │     │                         │
│    confirmación         │     │ Usuario responde →      │
│                         │     │ Se actualiza ticket     │
└─────────────────────────┘     └─────────────────────────┘
```

### 2.4 Respuestas del Sistema

#### Mensaje de Bienvenida
Cuando el usuario envía un saludo, recibe:

```
👋 ¡Hola [nombre]!

Soy el asistente de Administración de Fincas. Puedo ayudarte con:

📝 Reportar una incidencia
   Cuéntame el problema (ej: "no funciona la luz del portal")

📊 Consultar estado de tus incidencias abiertas
   Escribe "estado" o "mis incidencias"

❓ Ayuda
   Escribe "ayuda" para ver más opciones

¿En qué puedo ayudarte?
```

#### Incidencia Registrada Correctamente
```
✅ INCIDENCIA REGISTRADA CORRECTAMENTE

📋 Código de seguimiento: INC-XXXXXX

📝 Resumen del problema:
[descripción generada por IA]

🏷️ Categoría: [Fontanería/Electricidad/etc.]
📍 Ubicación: [dirección] ([piso/puerta])

━━━━━━━━━━━━━━━━━━━━━━
✔️ Hemos notificado al técnico especializado.

🔔 Le informaremos cuando la incidencia esté solucionada.

💾 Guarde el código INC-XXXXXX para consultar el estado.
```

#### Solicitud de Información Adicional
```
📋 INCIDENCIA RECIBIDA
Código: INC-XXXXXX

📝 Hemos entendido que su problema es:
"[resumen del problema]"

✅ Sus datos registrados:
👤 Nombre: [nombre]
📱 Teléfono: [teléfono]

━━━━━━━━━━━━━━━━━━━━━━
⚠️ Para poder gestionar su incidencia necesitamos:

• Dirección del edificio (Ej: Calle Mayor 15)
• Piso y puerta (Ej: 3º A)

📩 Por favor, indíquenos estos datos.
```

#### Notificación de Cierre
Cuando una incidencia se resuelve:
```
✅ INCIDENCIA RESUELTA

📋 Código: INC-XXXXXX
📝 Asunto: [asunto del ticket]

¡Su incidencia ha sido solucionada!

Si tiene alguna duda o el problema persiste, responda a este mensaje.

Gracias por su paciencia. 🙏
```

### 2.5 Prevención de Duplicados

El sistema incluye lógica inteligente para evitar crear múltiples tickets por la misma incidencia:

- **Ventana de 2 horas**: Los mensajes dentro de 2 horas de un ticket activo se asocian automáticamente al mismo ticket
- **Detección IA**: Se usa IA para determinar si un mensaje es sobre un problema nuevo o el mismo
- **Palabras clave**: Detecta frases como "otro problema", "nueva incidencia" para crear tickets separados

---

## 3. Formulario Web Público

### 3.1 Acceso

URL: `https://[dominio]/reportar`

### 3.2 Campos del Formulario

#### Información del Reportante
| Campo | Obligatorio | Descripción |
|-------|-------------|-------------|
| Nombre completo | ✅ Sí | Nombre del vecino/propietario |
| Email | ✅ Sí | Para comunicaciones y seguimiento |
| Teléfono | ✅ Sí | Para contacto directo |

#### Información de Ubicación
| Campo | Obligatorio | Descripción |
|-------|-------------|-------------|
| Comunidad | No | Nombre de la comunidad de propietarios |
| Dirección | No | Dirección del edificio |
| Piso/Puerta | No | Ubicación específica |

#### Información de la Incidencia
| Campo | Obligatorio | Descripción |
|-------|-------------|-------------|
| Asunto | ✅ Sí | Descripción breve del problema |
| Descripción | ✅ Sí | Detalles completos |
| Categoría | No | Tipo de incidencia (se auto-detecta si no se indica) |
| Urgencia | No | Nivel de urgencia (urgente, alta, media, baja) |

### 3.3 Flujo del Formulario

```
┌─────────────────────────────────────────────────────────────┐
│              USUARIO ACCEDE A /reportar                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   COMPLETA FORMULARIO                        │
│         - Datos personales                                   │
│         - Ubicación                                          │
│         - Descripción del problema                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    SISTEMA PROCESA                           │
│         - Crea/actualiza Reporter en BD                      │
│         - IA analiza la incidencia                           │
│         - Auto-clasifica categoría si no se indicó          │
│         - Crea Ticket con código único                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              PÁGINA DE CONFIRMACIÓN                          │
│         ✅ Ticket creado: INC-XXXXXX                        │
│         📋 Resumen de la incidencia                          │
│         🔔 Instrucciones de seguimiento                      │
└─────────────────────────────────────────────────────────────┘
```

### 3.4 Categorías Disponibles

| Código | Descripción | Ejemplos |
|--------|-------------|----------|
| WATER | Fontanería | Fugas, atascos, problemas de agua |
| ELEVATOR | Ascensor | Averías, paradas, ruidos |
| ELECTRICITY | Electricidad | Cortes, fallos de luz, enchufes |
| GARAGE_DOOR | Puerta de garaje | No abre/cierra, ruidos |
| CLEANING | Limpieza | Zonas sucias, basura |
| SECURITY | Seguridad | Cerraduras, portales, cámaras |
| OTHER | Otros | Cualquier otra incidencia |

### 3.5 Niveles de Prioridad

| Nivel | Criterio |
|-------|----------|
| **URGENT** | Personas atrapadas, inundación activa, emergencia de seguridad |
| **HIGH** | Afecta a varios vecinos, fugas contenidas, ascensor averiado |
| **MEDIUM** | Puede esperar 24-48h |
| **LOW** | Problemas menores, mantenimiento preventivo |

---

## 4. Canal Email

### 4.1 Funcionamiento

Los usuarios pueden enviar emails a la dirección de la administración. El sistema:

1. Recibe el email mediante webhook/polling
2. Analiza el contenido con IA
3. Crea automáticamente un ticket
4. Asocia al reporter existente o crea uno nuevo
5. Responde automáticamente si es necesario

### 4.2 Notificaciones por Email

El sistema envía emails automáticos en los siguientes casos:

- **Confirmación de recepción**: Cuando se crea un ticket
- **Solicitud de información**: Si faltan datos necesarios
- **Cierre de incidencia**: Cuando se resuelve el problema

---

## 5. Consulta de Estado

### 5.1 Por WhatsApp

Comandos disponibles:
- "estado"
- "mis incidencias"
- "cómo va mi incidencia"
- "[código de ticket]" (ej: INC-ABC123)

Respuesta ejemplo:
```
📊 Tus incidencias abiertas (2):

1. 🆕 INC-ABC123
   Fuga de agua en el baño
   Estado: Pendiente

2. 🔧 INC-DEF456
   Luz del portal no funciona
   Estado: En proceso

Para más detalles de una incidencia, escribe su código.
```

### 5.2 Detalle de Incidencia Específica

```
📋 Incidencia INC-ABC123

📝 Problema: Fuga de agua en el baño

📊 Estado: 🔧 En proceso de reparación
📍 Ubicación: Calle Mayor 15 (3º A)
📅 Reportada: 24/02/2026 10:30

```

---

## 6. Estados de las Incidencias

| Estado | Código | Descripción |
|--------|--------|-------------|
| Nueva | NEW | Recién creada, pendiente de asignación |
| Necesita Info | NEEDS_INFO | Esperando datos del reportante |
| En Validación | VALIDATING | Verificando información |
| Asignada | DISPATCHED | Técnico/proveedor asignado |
| Programada | SCHEDULED | Visita programada |
| En Proceso | IN_PROGRESS | Trabajo en curso |
| Pendiente Confirmación | NEEDS_CONFIRMATION | Esperando confirmación de resolución |
| Esperando Factura | WAITING_INVOICE | Trabajo terminado, pendiente factura |
| Cerrada | CLOSED | Incidencia resuelta y cerrada |
| Escalada | ESCALATED | Requiere atención especial |

---

## 7. Notificaciones Proactivas

### 7.1 Al Reportante

- **Cierre de incidencia**: Notificación automática por el canal original (WhatsApp o Email) cuando se cierra un ticket

### 7.2 Al Proveedor

- **Nueva incidencia asignada**: Email con detalles del problema
- **Información actualizada**: Cuando el reportante proporciona más datos

---

## 8. Diagrama de Arquitectura de Canales

```
                    ┌─────────────────┐
                    │    USUARIOS     │
                    │  (Vecinos/Prop) │
                    └────────┬────────┘
                             │
            ┌────────────────┼────────────────┐
            │                │                │
            ▼                ▼                ▼
    ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
    │   WhatsApp    │ │  Web Form     │ │    Email      │
    │   (Twilio)    │ │  /reportar    │ │  (Resend/SG)  │
    └───────┬───────┘ └───────┬───────┘ └───────┬───────┘
            │                 │                 │
            └────────────────┬┴─────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   Sistema IA    │
                    │  (OpenAI GPT)   │
                    │                 │
                    │ • Análisis      │
                    │ • Clasificación │
                    │ • Detección     │
                    │   de intención  │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │     TICKETS     │
                    │   (PostgreSQL)  │
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
                    │                 │
                    ▼                 ▼
           ┌───────────────┐ ┌───────────────┐
           │  PROVEEDORES  │ │   DASHBOARD   │
           │  (Email)      │ │   (Admin)     │
           └───────────────┘ └───────────────┘
```

---

## 9. Preguntas Frecuentes (FAQ)

### ¿Cómo sé que mi incidencia fue recibida?
Recibirá una confirmación inmediata con un código de seguimiento (INC-XXXXXX) por el mismo canal que usó para reportarla.

### ¿Puedo adjuntar fotos?
Actualmente el sistema no procesa archivos adjuntos por WhatsApp. Se recomienda describir el problema detalladamente.

### ¿Cómo consulto el estado de mi incidencia?
- **WhatsApp**: Escriba "estado" o el código de su incidencia
- **Dashboard**: Contacte con su administrador

### ¿Me avisarán cuando se solucione?
Sí, recibirá una notificación automática por el mismo canal que usó para reportar (WhatsApp o Email).

### ¿Qué hago si el problema persiste después del cierre?
Responda al mensaje de cierre indicando que el problema continúa. Se reabrirá o creará un nuevo ticket según corresponda.

---

*Documento generado automáticamente - Sistema de Gestión de Incidencias de Fincas v1.0*
