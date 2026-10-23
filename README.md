# legado-verde-finanzas
Ecosistema de gestión de Legado Verde con tablero financiero, flujo comercial e inteligencia artificial (Claude).

## Módulos
| Módulo | Qué hace | Tipo de dato |
|---|---|---|
| 📊 Resumen Ejecutivo | Ventas, EBITDA y punto de equilibrio del periodo | Registrado / preliminar |
| 🌐 Ventas por Canal | Captura, edición y anulación de ventas | Registrado |
| 📋 Catálogo de Costos | Presupuesto de costos fijos y variables | Estimado / confirmado |
| 🔮 Simulador de Escenarios | Escenarios de volumen y **mezcla de canales** | Estimación |
| 📑 Estados financieros | Resultados, flujo de efectivo y situación financiera (partida doble) | Registrado |
| 📈 Histórico y margen por canal | Ventas reportadas por mes y canal, deducciones no explicadas y contribución estimada | Hecho + estimación |
| 🔄 Flujo comercial | Captación → CRM → pedido → inventario → margen → recompra → contabilidad | Operativo (captación web simulada) |
| 🤖 Asistente IA | Diagnóstico, estrategia por canal, prospección, contenido y mensajes de recompra con Claude; bitácora con revisión humana | IA + revisión humana |

## Configurar la IA (Streamlit Cloud)
1. Crea una API key en https://console.anthropic.com
2. En la app: **Settings → Secrets** y agrega:
```toml
ANTHROPIC_API_KEY = "sk-ant-..."
# opcional:
# ANTHROPIC_MODEL = "claude-sonnet-5-5"
```
Sin clave, la app funciona y el módulo de IA muestra cómo configurarla.

## Importante sobre los datos
Streamlit Community Cloud **borra el archivo SQLite al reiniciar o redesplegar** la app. Descarga el
"📦 Respaldo completo JSON" (barra lateral) después de capturar y restáuralo si se pierde.
Siguiente fase: migrar el almacenamiento a una base externa (Supabase o Google Sheets).

## Archivos
- `app.py` – interfaz principal (Streamlit)
- `motor.py` – contabilidad y persistencia
- `comercial.py` – histórico por canal, escenarios, CRM, pedidos, inventario y recompra
- `vistas.py` – pantallas nuevas
- `ia.py` – conexión con Claude
