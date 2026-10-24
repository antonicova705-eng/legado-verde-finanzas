"""Integraciones oficiales con Mercado Libre y Amazon (SP-API).

Arquitectura:

* ``estado``: base SQLite propia (separada de la base contable) con cuentas,
  tokens, pedidos en preparación (con su JSON original), cola de
  notificaciones, bitácora de sincronizaciones y bloqueos.
* ``mercadolibre`` / ``amazon``: clientes de API y normalización a «partidas».
* ``conciliacion``: reglas que convierten partidas en ventas del sistema.
* ``sincronizador``: orquesta inicial, incremental, cola y recuperación.

Ningún token se guarda en el código ni en los respaldos JSON.
"""
