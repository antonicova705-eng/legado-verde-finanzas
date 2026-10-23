"""Asistente de IA con Claude (Anthropic). La clave se lee de st.secrets o variables de entorno."""
import json
import os

MODELO_POR_DEFECTO = 'claude-sonnet-5-5'

SISTEMA = """Eres el analista de negocio de Legado Verde, emprendimiento mexicano de guacamole liofilizado \
(sobres de 40 g) elaborado con aguacate de huerta familiar en la Ciénega de Jalisco. Vende en Mercado Libre, \
Amazon, cafeterías de Guadalajara y tienda en Shopify.

Reglas obligatorias:
1. Responde en español claro, cercano y profesional.
2. Usa SOLO los datos del contexto JSON. No inventes clientes, ventas, convenios ni certificaciones.
3. Separa explícitamente: **Hechos** (datos registrados), **Estimaciones** (cálculos con el catálogo de costos \
o supuestos), **Recomendaciones** e **Información faltante**.
4. Distingue ingresos, margen de contribución, utilidad y flujo de efectivo; no los mezcles.
5. Si un dato está marcado como pendiente o preliminar, dilo y explica cómo afecta la conclusión.
6. Propón acciones concretas, priorizadas y medibles. Todo lo que generes será revisado por una persona \
antes de usarse."""

TAREAS = {
    'Diagnóstico financiero y comercial': 'Haz un diagnóstico de la situación financiera y comercial: rentabilidad por canal, '
        'distancia al punto de equilibrio y principales riesgos. Termina con las 5 acciones más importantes para los próximos 30 días.',
    'Estrategia por canal': 'Compara la rentabilidad estimada de cada canal y recomienda en cuáles concentrar esfuerzo, '
        'cuáles ajustar (precio, envío, presentación) y cuáles pausar. Justifica con los números del contexto.',
    'Plan de prospección de cafeterías': 'Diseña un plan de prospección B2B para cafeterías de Guadalajara usando el embudo del CRM: '
        'perfil ideal, propuesta de valor, guion de primer contacto y metas semanales medibles.',
    'Contenido para redes sociales': 'Propón 5 publicaciones para redes sociales (Instagram/TikTok) para impulsar ventas rentables: '
        'idea, texto listo para publicar, llamado a la acción y canal de venta al que dirige. No afirmes beneficios de salud ni certificaciones.',
    'Mensajes de recompra': 'Redacta mensajes breves de WhatsApp para los clientes con recompra próxima o vencida que aparecen en el contexto. '
        'Uno por cliente, personalizado con lo que se sabe de su último pedido.',
}


def clave_api(secrets=None):
    try:
        if secrets is not None and 'ANTHROPIC_API_KEY' in secrets:
            return secrets['ANTHROPIC_API_KEY']
    except Exception:
        pass
    return os.environ.get('ANTHROPIC_API_KEY')


def modelo(secrets=None):
    try:
        if secrets is not None and 'ANTHROPIC_MODEL' in secrets:
            return secrets['ANTHROPIC_MODEL']
    except Exception:
        pass
    return os.environ.get('ANTHROPIC_MODEL', MODELO_POR_DEFECTO)


def construir_prompt(tarea, contexto, pregunta=''):
    instruccion = TAREAS.get(tarea, '')
    partes = []
    if instruccion:
        partes.append('Tarea: ' + instruccion)
    if pregunta.strip():
        partes.append('Pregunta o indicación adicional del usuario: ' + pregunta.strip())
    partes.append('Contexto de datos del sistema (JSON):\n' + json.dumps(contexto, ensure_ascii=False, indent=1, default=str))
    return '\n\n'.join(partes)


def consultar(prompt, api_key, model=MODELO_POR_DEFECTO, max_tokens=2500):
    import anthropic  # importación diferida: la app funciona aunque falte la librería
    cliente = anthropic.Anthropic(api_key=api_key)
    resp = cliente.messages.create(model=model, max_tokens=max_tokens, system=SISTEMA,
                                   messages=[{'role': 'user', 'content': prompt}])
    return ''.join(b.text for b in resp.content if getattr(b, 'type', '') == 'text')
