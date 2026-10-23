# Legado Verde Finanzas 2.0: arquitectura

Tablero financiero en tiempo real con asistente de voz/texto (Claude tool use) y sincronización desatendida de Mercado Libre y Amazon.

## 1. Stack y estructura

| Capa | Elección | Por qué |
|---|---|---|
| API | **FastAPI** (Python 3.12) + Uvicorn | Async para SSE, tipado con Pydantic, OpenAPI gratis en `/docs` |
| Base de datos | **PostgreSQL** (Neon, Supabase o Render) · SQLite en local | Persistente; resuelve el borrado de datos de Streamlit Cloud |
| ORM | SQLAlchemy 2.0, montos en `Numeric(12,2)` | Sin errores de redondeo de `float` |
| Tiempo real | **Server-Sent Events** (`sse-starlette`) | Unidireccional, reconecta solo, funciona en redes móviles; más simple que WebSockets |
| IA | **Claude Messages API con tool use** | Router de intenciones con escritura en dos fases |
| Voz | **Web Speech API** (captura y TTS en el teléfono) + **Whisper** de respaldo | Latencia mínima y sin costo; Whisper solo cuando el navegador no reconoce voz |
| Frontend | HTML + CSS + JS sin paso de build, servido por FastAPI | Un solo despliegue; carga instantánea en el teléfono |

Se descartó Next.js para esta fase: duplica el despliegue y el tooling sin aportar nada que el tablero necesite hoy. La API ya está separada, así que migrar a React/Next después solo cambia `frontend/`.

```
legado-verde-app/
├── Dockerfile · .env.example · ARQUITECTURA.md
├── frontend/                 index.html · styles.css · app.js
└── backend/
    ├── app/
    │   ├── main.py           rutas, auth, SSE, webhook ML, sincronizador
    │   ├── mcp_servidor.py   conector MCP para la app de Claude (voz)
    │   ├── config.py · db.py · models.py · eventos.py
    │   ├── servicios/ventas.py        reglas de negocio y KPIs (sin HTTP ni IA)
    │   ├── ia/herramientas.py         esquemas de tools + ejecutor contra BD
    │   ├── ia/asistente.py            bucle de tool use con Claude
    │   ├── voz/transcripcion.py       Whisper de respaldo
    │   └── integraciones/mercadolibre.py · amazon.py
    ├── scripts/importar_historico.py  migra el histórico sin inventar fechas
    └── tests/test_nucleo.py           12 pruebas (Claude simulado, webhooks, API)
```

### Modelo de datos
- `ventas`: canal, cliente, cantidad, `total_producto`, `ingreso_envio`, `comision`, `costo_logistico`, `otros_cargos`, `costo_producto` + `costo_confirmado`, `pendiente_conciliar`, `origen` (voz, texto, manual, mercadolibre, amazon, importacion) y `estado`. Restricción única `(canal, referencia_externa)` para idempotencia.
- `neto` = producto + envío cobrado − comisión − logística − otros cargos. **No es utilidad.**
- `contribucion` = neto − costo de producto (confirmado o, si falta, estimado con el catálogo). La API devuelve `tipo_contribucion: registrado | estimado`.
- `operaciones_pendientes`, `sesiones_chat`, `tokens_integracion`, `eventos_webhook`, `parametros`.

## 2. Interfaz

Jerarquía de información, de arriba abajo:
1. **Barra fija:** marca, selector de periodo (Hoy · 7 días · Mes · Año), indicador "En vivo" y botón **Modo coche**.
2. **Barra de comando:** campo de texto y micrófono, como la paleta de comandos de Linear. La respuesta aparece debajo, con botones Confirmar o Cancelar cuando hay una venta pendiente.
3. **Cuatro KPIs:** ventas de producto, sobres, contribución y avance al punto de equilibrio. Cada uno lleva su sello `registrado` o `estimado`.
4. **Canales**, con ventas y contribución por sobre (en rojo si es negativa), junto a **Actividad**, un feed en tiempo real que resalta cada venta nueva.

Paleta: verde bosque `#0B5127` (acento), lima `#8EB712` (progreso) y beige `#F4F2EC` (fondo). En tema oscuro el verde se aclara a `#4FB27A` para conservar el contraste. Tipografía Geist y Geist Mono, con cifras tabulares. En pantallas menores a 900 px los KPIs pasan a 2 columnas y la rejilla a 1.

**Modo coche:** pantalla completa oscura con un micrófono de unos 220 px como único control y respuestas grandes leídas en voz alta. Mantiene la pantalla encendida (Wake Lock). Cuando hay una confirmación pendiente, vuelve a escuchar solo, así que no hace falta tocar la pantalla. Úsalo con el teléfono en soporte; los botones Sí y No son para cuando el coche está detenido.

## 3. Voz

```
Teléfono: Web Speech (es-MX) ──texto──► POST /api/asistente ──► Claude + tools ──► BD ──► SSE ──► tablero
     └─ sin Web Speech: MediaRecorder ──audio──► POST /api/voz/transcribir (Whisper) ──texto──┘
Respuesta ◄── speechSynthesis (es-MX)
```
- El servidor no puede acceder al micrófono del coche: la captura **siempre** ocurre en el navegador (`frontend/app.js → escucharFrase`). Python recibe el texto o el audio.
- `voz/transcripcion.py` envía a Whisper `language=es` y un `prompt` con el vocabulario del negocio y los nombres de clientes registrados, para que "Casa Monic" no se transcriba como "casa mónica".
- En modo voz, el prompt de sistema obliga a responder en 1 o 2 frases, sin markdown y con cifras dichas de forma natural.

## 3-bis. Voz a través de Claude (ruta principal)

La forma más simple de usar la voz es **hablar con la app de Claude** y conectar este backend como **conector personalizado (MCP remoto)**. Claude hace el reconocimiento de voz, el razonamiento y la respuesta hablada; tu servidor solo expone las herramientas.

```
App de Claude (modo de voz, iPhone/Android) ──MCP──► https://TU-DOMINIO/mcp ──► servicios/ventas.py ──► Postgres
                                                                                         └─► SSE ──► tablero web
```

- `app/mcp_servidor.py` (SDK oficial `mcp`, FastMCP con transporte Streamable HTTP sin estado) expone `consultar_ventas`, `punto_de_equilibrio`, `ultimas_ventas`, `buscar_cliente`, `preparar_venta`, `confirmar_venta` y `cancelar_venta`. Las de lectura llevan `readOnlyHint` para que Claude las use sin pedir permiso.
- **Alta en Claude:** Configuración → Conectores → Agregar conector personalizado → URL `https://TU-DOMINIO/mcp`, con el header `Authorization: Bearer <MCP_TOKEN>`. Si tu plan no permite headers, usa la URL `https://TU-DOMINIO/mcp?key=<MCP_TOKEN>`.
- **Confirmación de escrituras:** en MCP no existen los "turnos" del asistente propio, así que `confirmar_venta` exige tres cosas: la frase literal del usuario con una afirmación clara (y sin negaciones), al menos 4 segundos desde que se preparó la venta, y que la operación no haya vencido (5 minutos). Además, Claude pide aprobación para herramientas de escritura salvo que elijas "permitir siempre".
- Las instrucciones del servidor indican a Claude que en voz responda con frases cortas y sin listas.
- **Verificar:** la documentación de modo de voz menciona conectores como Gmail y Calendar, pero no dice explícitamente que funcionen los conectores personalizados. Pruébalo en tu teléfono antes de depender de ello; si no funcionan, el asistente propio (sección 3) cubre el mismo flujo.

## 4. Function calling (`ia/`)

Herramientas de lectura: `consultar_ventas`, `punto_de_equilibrio`, `ultimas_ventas`, `buscar_cliente`.
Herramientas de escritura: `preparar_venta` → `confirmar_operacion` | `cancelar_operacion`.

**Escritura en dos fases, impuesta en código:**
1. "Agrega una venta a Cafetería Casa Monic por $1000 pesos de 15 sobres" → `preparar_venta(canal="Cafeterías", cliente="Casa Monic", cantidad=15, monto_total=1000)`. Se valida, se crea una `OperacionPendiente` (vigencia de 5 min) y **no se escribe la venta**. Claude lee el resumen: "15 sobres a Casa Monic (cliente nuevo), total $1,000.00 ($66.67 por sobre). ¿Lo confirmo?"
2. "Sí" → `confirmar_operacion(id)`. El ejecutor rechaza la confirmación si `op.turno >= turno_actual`, así que el modelo no puede preparar y confirmar en el mismo mensaje aunque lo intente (cubierto por `test_no_confirma_en_el_mismo_turno`). También la rechaza si la operación expiró o pertenece a otra sesión.
3. La venta se guarda con `origen="voz"`, se publica por SSE y el tablero se actualiza al instante.

Otros detalles:
- Los nombres dictados se resuelven con normalización sin acentos más `difflib`: "Casa Monik" encuentra "Casa Monic".
- El historial guarda solo el texto de cada turno. La operación pendiente se inyecta en el prompt de sistema en cada turno; así nunca se rompen los pares `tool_use`/`tool_result` y el contexto se mantiene corto.
- El bucle de herramientas da como máximo 6 vueltas; los errores de negocio regresan como `tool_result` con `is_error`, y Claude los explica en voz.

## 5. Mercado Libre y Amazon

### Mercado Libre (`integraciones/mercadolibre.py`)
- **OAuth 2.0:** `/integraciones/mercadolibre/conectar?token=…` redirige a `auth.mercadolibre.com.mx` con un `state` de un solo uso; el callback intercambia el `code` en `/oauth/token`. El access token dura unas 6 horas; el refresh token **rota**, así que siempre se guarda el nuevo.
- **Webhook** `POST /integraciones/mercadolibre/webhook`, topic `orders_v2`:
  1. Verifica `application_id` y `user_id` contra la cuenta conectada.
  2. Registra el evento con llave única `(proveedor, _id)`; los duplicados se ignoran.
  3. Responde 200 de inmediato y procesa en segundo plano. ML reenvía cualquier respuesta distinta de 200 durante una hora; las notificaciones perdidas se consultan en `/missed_feeds`.
  4. **Nunca confía en el cuerpo de la notificación:** consulta `GET /orders/{id}` con el token, así que un POST falsificado no puede crear ventas.
- **Mapeo:** `unit_price × quantity` → producto; `sale_fee × quantity` → comisión; `/shipments/{id}/costs` (`senders[].cost`) → logística. Si el costo de envío no está disponible, la venta queda `pendiente_conciliar`. **Valida estos campos con una orden real de varias unidades antes de confiar en las comisiones.**
- **Reconciliación** cada `SYNC_MINUTOS` con `/orders/search` de las últimas 48 horas: cubre notificaciones perdidas y envíos que se conciliaron después.

### Amazon SP-API (`integraciones/amazon.py`)
- **Amazon no envía webhooks HTTP.** La notificación `ORDER_CHANGE` llega a una cola SQS: `consumir_sqs()` (boto3, opcional). Para empezar, conviene el polling incremental de `GET /orders/v0/orders?LastUpdatedAfter=…`, ya incluido en el sincronizador.
- **Autenticación:** LWA con el refresh token de una app privada autorizada desde Seller Central, enviado en el header `x-amz-access-token`. Región NA, marketplace México `A1AM78C64UM0Y8`.
- **Cargos:** `GET /finances/v0/orders/{id}/financialEvents`. `Principal` → producto; `Shipping*` → envío cobrado; `Commission` y cuotas de cierre → comisión; tarifas FBA → logística; el resto → otros cargos. Los eventos se publican días después del envío, así que la venta queda `pendiente_conciliar` hasta que `reconciliar_pendientes()` los encuentra.
- Las cuotas de Orders y Finances son bajas: hay backoff exponencial ante 429. No se solicita información personal del comprador (evita el trámite de datos restringidos).

## 6. Despliegue y operación

1. Crea una base Postgres (Neon o Supabase tienen plan gratuito) y copia `.env.example` a las variables del servicio.
2. Despliega el `Dockerfile` en Render, Railway o Fly. Debe ser **una sola instancia**: el bus SSE vive en proceso. Para escalar, cambia `eventos.Bus` por Postgres `LISTEN/NOTIFY`.
3. Importa el histórico: `python -m scripts.importar_historico --respaldo respaldo_legado_verde.json` (o `--historico-base`).
4. Registra en Mercado Libre la URL de notificaciones `https://TU-DOMINIO/integraciones/mercadolibre/webhook` con el topic `orders_v2`.
5. Abre la app en el teléfono, escribe el `APP_TOKEN` y agrégala a la pantalla de inicio.

Seguridad: el token de acceso se compara con `hmac.compare_digest`; los secretos viven solo en variables de entorno. A Claude solo le llegan cifras agregadas y nombres de negocio, nunca teléfonos ni correos.

## 7. Pruebas
`cd backend && pip install -r requirements-dev.txt && pytest -q`. Las 12 pruebas cubren KPIs, validaciones, nombres dictados con errores, la venta por voz en dos turnos con Claude simulado, el intento de confirmar en el mismo turno, la expiración, el webhook de ML (otra app, otro vendedor, duplicados, sincronización idempotente), el mapeo de cargos de Amazon, la API protegida y el conector MCP de punta a punta (token, preparar, confirmación prematura, negativa y válida).

## 8. Pendientes conocidos
- Validar con datos reales: `sale_fee` y costos de envío de ML, y la clasificación de FeeType de Amazon México.
- Web Speech en iOS depende de la versión de Safari; si falla, la app usa Whisper automáticamente (requiere `OPENAI_API_KEY`).
- Lo que ya existía en la versión de Streamlit y aún no se migra: el catálogo editable de costos, los estados financieros de partida doble y el CRM y el inventario.

### Referencias
- Notificaciones de Mercado Libre: https://developers.mercadolibre.com.ar/en_us/products-receive-notifications
- Finances API de Amazon (eventos por orden): https://developer-docs.amazon.com/sp-api/reference/listfinancialeventsbyorderid
