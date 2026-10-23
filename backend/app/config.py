"""Configuración centralizada. Todo sale de variables de entorno (ver .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from zoneinfo import ZoneInfo


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    return value.strip() if isinstance(value, str) else value


def _db_url() -> str:
    url = _env("DATABASE_URL", "sqlite:///./legado_verde.db")
    # Render/Neon/Heroku entregan "postgres://"; SQLAlchemy 2 necesita el driver explícito.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=_db_url)
    app_token: str | None = field(default_factory=lambda: _env("APP_TOKEN"))
    mcp_token: str | None = field(default_factory=lambda: _env("MCP_TOKEN"))  # si falta, se usa APP_TOKEN
    zona_horaria: ZoneInfo = field(default_factory=lambda: ZoneInfo(_env("TZ_NEGOCIO", "America/Mexico_City")))
    # Render define RENDER_EXTERNAL_URL automáticamente; BASE_URL lo sobrescribe si existe.
    base_url: str = field(default_factory=lambda: _env("BASE_URL") or _env("RENDER_EXTERNAL_URL") or "http://localhost:8000")
    importar_historico_base: bool = field(default_factory=lambda: (_env("IMPORTAR_HISTORICO_BASE", "false") or "").lower() == "true")

    # IA
    anthropic_api_key: str | None = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    modelo_claude: str = field(default_factory=lambda: _env("CLAUDE_MODEL", "claude-sonnet-5-5"))
    openai_api_key: str | None = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    modelo_stt: str = field(default_factory=lambda: _env("STT_MODEL", "whisper-1"))

    # Supuestos financieros (ESTIMADOS hasta que se confirmen en Parametros)
    costo_variable_unitario: Decimal = field(default_factory=lambda: Decimal(_env("COSTO_VARIABLE_UNITARIO", "24.07")))
    costos_fijos_mensuales: Decimal = field(default_factory=lambda: Decimal(_env("COSTOS_FIJOS_MENSUALES", "29383.33")))

    # Mercado Libre
    ml_client_id: str | None = field(default_factory=lambda: _env("ML_CLIENT_ID"))
    ml_client_secret: str | None = field(default_factory=lambda: _env("ML_CLIENT_SECRET"))
    ml_auth_url: str = field(default_factory=lambda: _env("ML_AUTH_URL", "https://auth.mercadolibre.com.mx/authorization"))

    # Amazon SP-API (Login with Amazon + México)
    amz_client_id: str | None = field(default_factory=lambda: _env("AMZ_LWA_CLIENT_ID"))
    amz_client_secret: str | None = field(default_factory=lambda: _env("AMZ_LWA_CLIENT_SECRET"))
    amz_refresh_token: str | None = field(default_factory=lambda: _env("AMZ_REFRESH_TOKEN"))
    amz_endpoint: str = field(default_factory=lambda: _env("AMZ_ENDPOINT", "https://sellingpartnerapi-na.amazon.com"))
    amz_marketplace_id: str = field(default_factory=lambda: _env("AMZ_MARKETPLACE_ID", "A1AM78C64UM0Y8"))
    amz_sqs_url: str | None = field(default_factory=lambda: _env("AMZ_SQS_QUEUE_URL"))

    # Sincronización desatendida
    sync_minutos: int = field(default_factory=lambda: int(_env("SYNC_MINUTOS", "15")))
    sync_habilitado: bool = field(default_factory=lambda: _env("SYNC_HABILITADO", "true").lower() == "true")

    @property
    def es_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


settings = Settings()
