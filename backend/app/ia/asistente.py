"""Router de intenciones con Claude tool use.

Flujo por turno:
1. Carga la sesión, incrementa el turno e inyecta en el system prompt la operación pendiente (si hay).
2. Bucle de tool use (máx. 6 vueltas): Claude elige herramientas; el Ejecutor las corre contra la BD.
3. Persiste solo texto (usuario/asistente) para no romper pares tool_use/tool_result entre turnos.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.orm import Session

from ..config import settings
from ..models import CANALES, Cliente, SesionChat
from ..servicios import ventas as sv
from .herramientas import HERRAMIENTAS, Contexto, Ejecutor, pendiente_actual

log = logging.getLogger("legado.asistente")
MAX_VUELTAS = 6
HISTORIAL = 12

SISTEMA_BASE = """Eres el copiloto financiero de Legado Verde (guacamole liofilizado en sobres de 40 g, Jalisco).
Fecha de hoy: {hoy}. Moneda: pesos mexicanos. Canales válidos: {canales}.

Modo de respuesta: {modo}.
- En modo voz el usuario va manejando: responde en 1 o 2 frases cortas, sin listas, sin markdown, sin emojis,
  con cifras redondeadas y dichas de forma natural ("mil trescientos cuarenta pesos", "quince sobres").
- En modo texto puedes ser algo más detallado, pero conciso.

Reglas:
1. Toda cifra sale de una herramienta. Nunca inventes ventas, clientes ni montos.
2. Distingue ventas (ingreso), neto de canal (tras comisiones y envíos), contribución (neto menos costo de producto)
   y utilidad. Si un dato es "estimado", dilo en pocas palabras.
3. Para registrar una venta usa preparar_venta, lee el resumen y pregunta "¿Lo confirmo?". Nunca llames
   confirmar_operacion en el mismo turno en que preparaste la operación.
4. Si el usuario confirma ("sí", "confirmo", "dale", "adelante") y hay una operación pendiente, llama
   confirmar_operacion con su id. Si corrige un dato, vuelve a llamar preparar_venta con los datos corregidos.
5. Si falta cantidad o monto, pregunta solo lo que falta.
6. "Cafetería X" significa canal Cafeterías y cliente X.
{pendiente}
Clientes registrados (para reconocer nombres dictados): {clientes}"""


class ClienteLLM(Protocol):
    @property
    def messages(self) -> Any: ...


@dataclass
class Respuesta:
    texto: str
    acciones: list[dict] = field(default_factory=list)
    pendiente: dict | None = None
    refrescar: bool = False


def _cliente_anthropic() -> ClienteLLM:
    import anthropic  # importación diferida: el resto de la app funciona sin la librería
    if not settings.anthropic_api_key:
        raise RuntimeError("Falta ANTHROPIC_API_KEY.")
    return anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=2, timeout=30)


class Asistente:
    def __init__(self, cliente: ClienteLLM | None = None, modelo: str | None = None):
        self._cliente = cliente
        self.modelo = modelo or settings.modelo_claude

    @property
    def cliente(self) -> ClienteLLM:
        if self._cliente is None:
            self._cliente = _cliente_anthropic()
        return self._cliente

    def _sistema(self, db: Session, sesion_id: str, modo: str) -> str:
        op = pendiente_actual(db, sesion_id)
        pendiente = (f"\nOperación pendiente de confirmar: id={op.id}; {op.resumen}.\n" if op else "\nNo hay operaciones pendientes.\n")
        nombres = [c.nombre for c in db.query(Cliente).order_by(Cliente.nombre).limit(80)]
        return SISTEMA_BASE.format(hoy=sv.hoy().isoformat(), canales=", ".join(CANALES),
                                   modo="VOZ" if modo == "voz" else "TEXTO", pendiente=pendiente,
                                   clientes=", ".join(nombres) or "ninguno")

    def responder(self, db: Session, sesion_id: str, texto: str, modo: str = "voz") -> Respuesta:
        texto = (texto or "").strip()
        if not texto:
            return Respuesta("No te escuché bien. ¿Me lo repites?")
        sesion = db.get(SesionChat, sesion_id) or SesionChat(id=sesion_id, turno=0, mensajes=[])
        if sesion not in db:
            db.add(sesion)
        sesion.turno += 1
        db.commit()

        ctx = Contexto(db=db, sesion_id=sesion_id, turno=sesion.turno)
        ejecutor = Ejecutor(ctx)
        mensajes: list[dict] = list(sesion.mensajes or [])[-HISTORIAL:] + [{"role": "user", "content": texto}]
        sistema = self._sistema(db, sesion_id, modo)
        final = ""
        for _ in range(MAX_VUELTAS):
            resp = self.cliente.messages.create(model=self.modelo, max_tokens=700 if modo == "voz" else 1500,
                                                system=sistema, tools=HERRAMIENTAS, messages=mensajes)
            bloques = [x for x in (_bloque(b) for b in resp.content) if x]
            mensajes.append({"role": "assistant", "content": bloques})
            usos = [b for b in bloques if b["type"] == "tool_use"]
            if resp.stop_reason != "tool_use" or not usos:
                final = " ".join(b["text"] for b in bloques if b["type"] == "text").strip()
                break
            resultados = []
            for uso in usos:
                salida = ejecutor.ejecutar(uso["name"], uso.get("input") or {})
                log.info("tool %s -> %s", uso["name"], "error" if "error" in salida else "ok")
                resultados.append({"type": "tool_result", "tool_use_id": uso["id"],
                                   "content": json.dumps(salida, ensure_ascii=False, default=str),
                                   **({"is_error": True} if "error" in salida else {})})
            mensajes.append({"role": "user", "content": resultados})
        else:
            final = "Me tomó demasiados pasos resolverlo. ¿Lo puedes decir de otra forma?"

        final = final or "Listo."
        historial = list(sesion.mensajes or []) + [{"role": "user", "content": texto},
                                                    {"role": "assistant", "content": final}]
        sesion.mensajes = historial[-HISTORIAL:]
        db.commit()
        op = pendiente_actual(db, sesion_id)
        return Respuesta(texto=final, acciones=ctx.acciones,
                         pendiente={"id": op.id, "resumen": op.resumen} if op else None,
                         refrescar=any(a["tipo"] == "venta_creada" for a in ctx.acciones))


def _bloque(b: Any) -> dict | None:
    """Normaliza bloques del SDK (objetos) o de dobles de prueba (dicts)."""
    if isinstance(b, dict):
        return b
    if b.type == "text":
        return {"type": "text", "text": b.text}
    if b.type == "tool_use":
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    return None
