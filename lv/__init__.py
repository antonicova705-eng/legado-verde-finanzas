"""Lógica de negocio de Legado Verde que no depende de Streamlit.

Los módulos de este paquete operan sobre el diccionario ``datos`` que guarda
``motor.Almacen``. Solo importan de ``motor`` los nombres que usan, de forma
explícita, para que una dependencia faltante falle con un mensaje claro.
"""

ESQUEMA = 2
