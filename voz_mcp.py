#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor MCP VOZ (Airbnb) — la voz de los agentes en la SALA DE EQUIPO (team_feed).
Envuelve team_feed.py (post_feed / fetch_feed → Postgres agentes_os, fail-safe).

Alcance (decidido con Esteban): SOLO la Sala de equipo interna.
- NO envia mensajes a huespedes ni a grupos de limpieza/danos (eso sigue por los flujos
  propios de cada bot).
- NO escribe a Telegram privado de Esteban (se puede sumar despues si se quiere).

Da a cualquier cerebro dos capacidades para que los agentes CONVERSEN entre si:
- leer_sala  → ver lo que dijeron los otros (para responder con contexto).
- postear_en_sala → hablar en 1a persona / hacer handoffs.

Escritura con kill-switch: VOZ_MCP_ALLOW_POST (default "1" = on). Fail-safe: si Postgres
falla, devuelve False/[], nunca rompe.

Requisitos: pip install "mcp"  (psycopg2 ya lo usa team_feed)
Registro (usuario dispatch):
  claude mcp add -s user voz -- python3 /opt/dispatch/projects/airbnb/voz_mcp.py
"""
import os

from mcp.server.fastmcp import FastMCP

try:
    import team_feed as tf
except Exception as e:
    tf = None
    _ERR = str(e)
else:
    _ERR = None

mcp = FastMCP("voz")

TIPOS_OK = ("info", "accion", "handoff", "alerta", "pregunta")
ALLOW_POST = os.environ.get("VOZ_MCP_ALLOW_POST", "1") == "1"


def _need():
    if tf is None:
        raise RuntimeError("team_feed no disponible: %s" % _ERR)


def _lim(n, default, tope=200):
    try:
        return max(1, min(int(n), tope))
    except Exception:
        return default


@mcp.tool()
def leer_sala(limit: int = 30, agente: str = "") -> dict:
    """Lee la Sala de equipo (team_feed) del proyecto airbnb, mas reciente primero.
    Opcional filtrar por `agente`. Devuelve ts, agente, para, tipo, mensaje. LECTURA."""
    _need()
    n = _lim(limit, 30)
    rows = tf.fetch_feed(proyecto="airbnb", limit=n, agente=(agente or None))
    return {"ok": True, "n": len(rows), "mensajes": rows}


@mcp.tool()
def postear_en_sala(agente: str, mensaje: str, para: str = "", tipo: str = "info") -> dict:
    """Publica un mensaje en la Sala de equipo (team_feed) hablando en 1a persona.
    `agente` = quien habla (ej. 'Revenue Manager'); `mensaje` = texto natural;
    `para` = a quien (otro agente) o vacio = general; `tipo` = info|accion|handoff|alerta|pregunta.
    ESCRITURA interna (no sale a huespedes/Telegram). Honra VOZ_MCP_ALLOW_POST. Fail-safe."""
    _need()
    if not ALLOW_POST:
        return {"ok": False, "error": "posteo desactivado (VOZ_MCP_ALLOW_POST != 1)"}
    if not agente or not str(agente).strip():
        return {"ok": False, "error": "falta 'agente' (quien habla)"}
    if not mensaje or not str(mensaje).strip():
        return {"ok": False, "error": "mensaje vacio"}
    t = (tipo or "info").strip().lower()
    if t not in TIPOS_OK:
        t = "info"
    ok = tf.post_feed(str(agente).strip(), str(mensaje).strip(),
                      para=(para.strip() or None), tipo=t, proyecto="airbnb")
    return {"ok": bool(ok), "posteado": bool(ok), "agente": str(agente).strip(),
            "para": (para.strip() or None), "tipo": t,
            "error": None if ok else "team_feed no confirmo (Postgres caido/lento?)"}


if __name__ == "__main__":
    mcp.run()
