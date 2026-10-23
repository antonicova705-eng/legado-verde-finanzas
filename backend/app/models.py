"""Modelo de datos. Montos en MXN con Numeric(12,2); nunca float."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

CANALES = ("Mercado Libre", "Amazon", "Cafeterías", "Tienda en línea", "Venta directa", "Otros")
ORIGENES = ("voz", "texto", "manual", "mercadolibre", "amazon", "importacion")
Dinero = Numeric(12, 2)


def ahora() -> datetime:
    return datetime.now(timezone.utc)


class Cliente(Base):
    __tablename__ = "clientes"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120))
    nombre_norm: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tipo: Mapped[str] = mapped_column(String(30), default="Cafetería")
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    ventas: Mapped[list["Venta"]] = relationship(back_populates="cliente")


class Venta(Base):
    __tablename__ = "ventas"
    __table_args__ = (UniqueConstraint("canal", "referencia_externa", name="uq_venta_canal_ref"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[date | None] = mapped_column(Date, index=True)          # None = fecha exacta pendiente
    mes_reportado: Mapped[str | None] = mapped_column(String(40))         # etiqueta histórica sin fecha
    canal: Mapped[str] = mapped_column(String(40), index=True)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id"))
    referencia_externa: Mapped[str | None] = mapped_column(String(80))
    producto: Mapped[str] = mapped_column(String(120), default="Guacamole Liofilizado 40g")
    cantidad: Mapped[int] = mapped_column(Integer)
    total_producto: Mapped[Decimal] = mapped_column(Dinero)              # venta de producto, sin envío
    ingreso_envio: Mapped[Decimal] = mapped_column(Dinero, default=Decimal("0"))
    comision: Mapped[Decimal] = mapped_column(Dinero, default=Decimal("0"))
    costo_logistico: Mapped[Decimal] = mapped_column(Dinero, default=Decimal("0"))
    otros_cargos: Mapped[Decimal] = mapped_column(Dinero, default=Decimal("0"))
    costo_producto: Mapped[Decimal | None] = mapped_column(Dinero)        # costo de ventas real
    costo_confirmado: Mapped[bool] = mapped_column(Boolean, default=False)
    pendiente_conciliar: Mapped[bool] = mapped_column(Boolean, default=False)  # cargos de plataforma incompletos
    origen: Mapped[str] = mapped_column(String(20), default="manual")
    estado: Mapped[str] = mapped_column(String(20), default="confirmada")  # confirmada | anulada
    notas: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora, onupdate=ahora)

    cliente: Mapped[Cliente | None] = relationship(back_populates="ventas")

    @property
    def neto(self) -> Decimal:
        """Lo que queda tras cargos de canal (antes de costo de producto). No es utilidad."""
        return (self.total_producto + self.ingreso_envio - self.comision
                - self.costo_logistico - self.otros_cargos)


class OperacionPendiente(Base):
    """Escritura propuesta por el asistente; solo se aplica con confirmación en un turno posterior."""
    __tablename__ = "operaciones_pendientes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sesion_id: Mapped[str] = mapped_column(String(64), index=True)
    turno: Mapped[int] = mapped_column(Integer)
    tipo: Mapped[str] = mapped_column(String(30))
    datos: Mapped[dict] = mapped_column(JSON)
    resumen: Mapped[str] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente")  # pendiente|aplicada|cancelada|expirada
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resultado_id: Mapped[int | None] = mapped_column(Integer)


class SesionChat(Base):
    __tablename__ = "sesiones_chat"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    turno: Mapped[int] = mapped_column(Integer, default=0)
    mensajes: Mapped[list] = mapped_column(JSON, default=list)
    actualizada: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora, onupdate=ahora)


class Parametro(Base):
    __tablename__ = "parametros"
    clave: Mapped[str] = mapped_column(String(60), primary_key=True)
    valor: Mapped[str] = mapped_column(String(200))
    tipo_dato: Mapped[str] = mapped_column(String(20), default="estimado")  # estimado | confirmado


class TokenIntegracion(Base):
    __tablename__ = "tokens_integracion"
    proveedor: Mapped[str] = mapped_column(String(20), primary_key=True)
    cuenta_id: Mapped[str | None] = mapped_column(String(40))
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora, onupdate=ahora)


class EventoWebhook(Base):
    __tablename__ = "eventos_webhook"
    __table_args__ = (UniqueConstraint("proveedor", "evento_id", name="uq_evento"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    proveedor: Mapped[str] = mapped_column(String(20))
    evento_id: Mapped[str] = mapped_column(String(80))
    topic: Mapped[str] = mapped_column(String(40))
    resource: Mapped[str] = mapped_column(String(200))
    recibido_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    procesado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
