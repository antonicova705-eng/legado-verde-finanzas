# legado-verde-finanzas
Tablero financiero integrado a la IA

**Ver el tablero en línea:** https://legado-verde-finanzas-hjpvvpcwsbhuxiulswe5td.streamlit.app/

## Sistema financiero 2.0

Aplicación Streamlit para registrar ventas, cobros y gastos, y consultar resultados financieros de Legado Verde.

## Archivos

| Archivo | Qué hace |
|---|---|
| `app.py` | Aplicación (Inicio, Ventas, Costos y gastos, Finanzas, Simulador, Configuración y respaldos). |
| `motor.py` | Sin cambios. Contabilidad y almacenamiento con control de versiones. |
| `lv/` | Lógica nueva: modelo de venta, operaciones atómicas, importación, reportes, respaldos, integraciones. |
| `registrar_venta.py` | Registra ventas desde un JSON/CSV con la misma lógica de la app (vista previa y `--confirmar`). |
| `convertir_reportes.py` | Convierte los reportes descargados de Mercado Libre (Excel de ventas) y Amazon (transacciones CSV) al formato de importación. |
| `servidor_mcp.py` | Conector de voz para Claude (MCP remoto): consultar y registrar ventas en dos pasos. Se despliega en Render con `render.yaml`. |
| `lv/almacen_sql.py` | Base PostgreSQL externa compartida por Streamlit y el conector (se activa con `DATABASE_URL`). |
| `sync_worker.py` | Proceso de sincronización con Mercado Libre y Amazon, independiente de Streamlit. |
| `webhook_ml.py` | Receptor de notificaciones `orders_v2` de Mercado Libre. |
| `tests/` | Pruebas automáticas contra el `motor.py` real. `tests/stubs/` simula Streamlit y Plotly solo para pruebas de humo. |

## Ejecutar

```bash
pip install -r requirements.txt
streamlit run app.py
```

Pruebas: `python -m unittest discover -s tests -p "test_*.py"`

## Base de datos permanente y conector de voz

```
Claude (voz, CarPlay) → servidor_mcp.py (Render) ─┐
                                                   ├→ PostgreSQL externo (Neon, DATABASE_URL)
Tablero Streamlit ─────────────────────────────────┘
```

1. Crea un proyecto gratuito en Neon y copia su cadena de conexión (`postgresql://…`).
2. Streamlit Cloud → tu app → *Settings → Secrets*: `DATABASE_URL = "postgresql://…"`. Al guardar, la app se reinicia y usa esa base; restaura tu respaldo JSON en *Configuración y respaldos*.
3. Render → *New → Blueprint* → este repositorio. Pega la misma `DATABASE_URL`; `MCP_TOKEN` se genera solo.
4. Claude → *Configuración → Conectores → Agregar conector personalizado*: `https://<servicio>.onrender.com/mcp?key=<MCP_TOKEN>`.
5. En *Configuración y respaldos → Parámetros* define el costo de producción por sobre para que las ventas por voz lleven costo confirmado.

Registrar por voz: Claude prepara la venta, te la lee y solo la guarda si respondes con un «sí» claro. Repetir la confirmación no duplica. Venta directa (cafeterías) entra sin comisión ni costo de entrega salvo que los digas; en marketplaces la comisión queda pendiente.

Límites del plan gratuito: el servicio de Render se duerme tras 15 minutos sin uso y tarda cerca de un minuto en despertar (la primera orden puede fallar; repítela). Neon suspende el cómputo tras 5 minutos de inactividad sin borrar datos (1 GB por proyecto).

## Dónde viven los datos (importante)

Las ventas se guardan en SQLite (`LEGADO_VERDE_DB`, por omisión `datos/legado_verde.sqlite3`). **Streamlit Community Cloud no tiene disco persistente**: un reinicio o redespliegue puede borrar la base. Para conservar datos:

- Despliega en un servidor con disco persistente (VPS, Railway/Render/Fly con volumen) y define `LEGADO_VERDE_DB` en ese disco.
- El mismo servidor debe correr `sync_worker.py` (y `webhook_ml.py` si quieres tiempo real), porque comparten la base.
- Descarga respaldos JSON con regularidad (Configuración y respaldos → Respaldos).

La app avisa en «Almacenamiento» si detecta un disco temporal.

## Registrar una venta

1. Botón **Registrar venta** (arriba a la derecha en Inicio, Ventas, Costos y Finanzas).
2. Captura rápida: fecha, canal, presentación, cantidad y precio por presentación.
3. *Detalles avanzados* (opcional): descuentos, devolución en dinero y en sobres, envío, comisiones, logística, costo de ventas, entrega, cliente.
4. Si ya cobraste, elige «Sí, registrar el cobro ahora» con fecha e importe. La venta y su cobro se guardan juntos o no se guarda ninguno.
5. Revisa la vista previa y pulsa **Guardar venta**. Verás el ID verificado en la base.

Reglas: el folio debe ser único por canal (también frente a ventas anuladas); si lo dejas vacío se genera uno interno `INT-AAAAMMDD-XXXXXX`. «Cantidad» del sistema = sobres equivalentes; un paquete de 3 vendido 4 veces son 4 presentaciones y 12 sobres. Un dato que no conoces queda *pendiente*, no en cero. Cambiar el estado a «Cobrado» no crea efectivo: el cobro se registra con su fecha e importe.

## Ventas desde Claude

Esta conversación no tiene acceso a tu servidor, así que el mecanismo funcional es **archivo validado**:

1. Escríbele a Claude, por ejemplo: «Agrega una venta de 10 sobres a una cafetería, a $60 cada uno, realizada hoy; cobrada por transferencia».
2. Claude muestra lo interpretado y lo pendiente (cliente, referencia bancaria, comisión, costo) y te entrega un JSON con formato `legado-verde-ventas` v1 y una clave única por venta.
3. En la app: **Ventas → Importar**, carga el archivo, revisa la vista previa y confirma. O en el servidor: `python registrar_venta.py ventas.json --confirmar`.
4. Recibes el ID de cada venta verificado en la base. Importar el mismo archivo otra vez no duplica nada.

Conexión directa futura (no incluida): requeriría una API privada con autenticación, HTTPS, una clave guardada en secretos del servidor y una herramienta MCP propia que llame a esa API. Mientras no exista, Claude no puede escribir en tu base ni debe afirmar que lo hizo.

## Recuperar un respaldo

Configuración y respaldos → Respaldos → carga el JSON. La app lo valida (estructura, IDs y claves duplicadas, asientos cuadrados) y muestra qué cambiaría. Al confirmar, guarda una copia automática de la base actual en `datos/respaldos/` y luego restaura.

## Integraciones Mercado Libre y Amazon

Estado: **integración preparada y probada con APIs simuladas**. No hay conexión autorizada ni sincronización comprobada con datos reales.

| | Mercado Libre | Amazon (SP-API, México) |
|---|---|---|
| Autenticación | OAuth 2.0; el refresh token rota y se guarda en `integraciones.sqlite3` | LWA con refresh token en variable de entorno |
| Pedidos | `GET /orders/search` por `date_last_updated` (offset/limit 50), `GET /orders/{id}` | Orders API v2026-01-01 `GET /orders/2026-01-01/orders` con `lastUpdatedAfter` y `paginationToken` |
| Comisiones | `sale_fee × cantidad`, marcada como estimada | Finances API (eventos financieros), disponibles después del envío |
| Tiempo real | Notificaciones `orders_v2` → `webhook_ml.py` → cola (respuesta < 500 ms) | No incluido: requiere Amazon SQS/EventBridge (cuenta AWS) |
| Frecuencia efectiva | Segundos con webhook; si no, cada 15 min | Cada 15 min; límite publicado de 0.0056 solicitudes/s (ráfaga 20) |
| Límites | Órdenes de hasta 12 meses; filtros de fecha ignoran minutos (se traslapan 2 h) | v0 de Orders se retira; migración exigida antes del 27-mar-2027 |

Reglas de integridad: identidad por plataforma + cuenta + pedido + partida; IDs deterministas; JSON original e historial por pedido; el cursor solo avanza si la corrida termina bien; bloqueo por cuenta; posibles duplicados con capturas manuales quedan en revisión (incorporar, vincular o ignorar); SKU sin relacionar no se cuenta; costos, cliente, notas y cobros nunca se sobrescriben; ediciones manuales generan conflicto salvo que elijas «la plataforma prevalece»; un pedido pagado no crea efectivo; cancelaciones anulan la venta solo si no tiene cobros.

Reconocimiento: Mercado Libre `paid`/`partially_refunded` y Amazon `UNSHIPPED`/`PARTIALLY_SHIPPED`/`SHIPPED` se reconocen en la fecha del pedido (hora de Ciudad de México); los pagos en proceso o `PENDING` quedan como pendientes fuera de reportes.

Para activar:
1. Crea las aplicaciones oficiales, define las variables de `.env.example` en el servidor.
2. Mercado Libre: autoriza en `https://auth.mercadolibre.com.mx/authorization?response_type=code&client_id=…&redirect_uri=…` y ejecuta `python sync_worker.py --autorizar-ml CODIGO`.
3. Relaciona tus SKU con presentaciones (Configuración → Canales y presentaciones).
4. `python sync_worker.py --inicial --desde 2026-07-01`, revisa «Integraciones» y anula los resúmenes heredados (ML-001…ML-004, AMZ-001) que ahora vengan desglosados.
5. Deja corriendo `python sync_worker.py --continuo --minutos 15` (systemd o similar) y, para tiempo real, `webhook_ml.py` detrás de HTTPS.

Validar con la primera respuesta real: los campos de Amazon marcados «por validar» (descuentos de promoción) y si `sale_fee` de Mercado Libre es por unidad en tu cuenta.
