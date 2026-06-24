#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor MCP de EQUIPO (Airbnb) — la "foto del equipo" para cualquier cerebro.
SOLO LECTURA sobre las SQLite donde los agentes dejan su estado (la forma real en que
se comunican, segun el Mapa de Agentes: comparten datos por SQLite, no por Telegram).

Generaliza lo que hoy hace SOLO el CEO (ctx_revenue/ctx_limpiezas/ctx_servicio/ctx_soporte
en ceo.py): lo expone como herramientas MCP para que el CEO, el Revenue Manager, o los
agentes de futuras empresas vean el panorama sin reimplementar nada.

Esquemas y rutas tomados 1:1 de ceo.py / revenue_manager.py (fuente de verdad).
Abre cada DB en modo read-only (file:...?mode=ro) — NO puede escribir.
Fail-safe: si una DB falta o esta bloqueada, devuelve un aviso, no rompe.

Requisitos: pip install "mcp"
Registro (usuario dispatch):
  claude mcp add equipo -- python3 /opt/dispatch/projects/airbnb/equipo_mcp.py
"""
import os
import sqlite3

from mcp.server.fastmcp import FastMCP

PROJ = os.path.dirname(os.path.abspath(__file__))

# mismas rutas/env que ceo.py
REVENUE_DB = os.environ.get("REVENUE_DB", os.path.join(PROJ, "revenue.db"))
LIMPIEZAS_DB = os.environ.get("LIMPIEZAS_DB", os.path.join(PROJ, "limpiezas.db"))
CHAT_DB = os.environ.get("CHAT_DB", "/opt/airbnb-chat/data/chat.db")
CASES_DB = os.environ.get("CASES_DB", "/opt/dispatch/airbnb-support-bot/data/cases.db")

mcp = FastMCP("equipo")


def _q(path, sql, args=()):
    """Query read-only. Devuelve lista de dicts (usa cursor.description)."""
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    try:
        cur = con.execute(sql, args)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        con.close()


def _lim(n, default, tope=200):
    try:
        return max(1, min(int(n), tope))
    except Exception:
        return default


# ---------- Revenue (precios) ----------
@mcp.tool()
def precios_recientes(limit: int = 12, estado: str = "") -> dict:
    """Recomendaciones de precio del Revenue Manager (revenue.db). Opcional filtrar por
    estado: 'pendiente' | 'aplicada' | 'rechazada' | 'error'. Read-only."""
    n = _lim(limit, 12)
    try:
        if estado:
            rows = _q(REVENUE_DB,
                      "SELECT apto,ciudad,room_id,desde,hasta,precio_actual,precio_sugerido,"
                      "pct,estado,motivo,ts FROM recomendaciones WHERE estado=? "
                      "ORDER BY ts DESC LIMIT ?", (estado, n))
        else:
            rows = _q(REVENUE_DB,
                      "SELECT apto,ciudad,room_id,desde,hasta,precio_actual,precio_sugerido,"
                      "pct,estado,motivo,ts FROM recomendaciones ORDER BY ts DESC LIMIT ?", (n,))
        return {"ok": True, "recomendaciones": rows}
    except Exception as e:
        return {"ok": False, "error": "revenue.db: %s" % str(e)[:120]}


@mcp.tool()
def precios_resumen() -> dict:
    """Resumen del estado de precios: cuantas recomendaciones por estado y cuantas
    pendientes sin aprobar (revenue.db). Read-only."""
    try:
        por_estado = _q(REVENUE_DB,
                        "SELECT estado, count(*) AS n FROM recomendaciones GROUP BY estado")
        pend = _q(REVENUE_DB,
                  "SELECT count(*) AS n FROM recomendaciones WHERE estado='pendiente'")
        return {"ok": True, "por_estado": por_estado,
                "pendientes": (pend[0]["n"] if pend else 0)}
    except Exception as e:
        return {"ok": False, "error": "revenue.db: %s" % str(e)[:120]}


@mcp.tool()
def desempeno_aptos(limit: int = 30) -> dict:
    """Reporte de desempeno por apartamento que genera el Revenue Manager (tabla
    'desempeno' en revenue.db, si existe). Schema-agnostico. Read-only."""
    n = _lim(limit, 30)
    try:
        rows = _q(REVENUE_DB, "SELECT * FROM desempeno ORDER BY rowid DESC LIMIT ?", (n,))
        return {"ok": True, "desempeno": rows}
    except Exception as e:
        return {"ok": False, "error": "desempeno no disponible: %s" % str(e)[:120]}


# ---------- Limpiezas ----------
@mcp.tool()
def limpiezas_recientes(limit: int = 15) -> dict:
    """Ultimas limpiezas con su veredicto del Supervisor de Limpiezas (limpiezas.db):
    apto, ciudad, fecha, estado, veredicto. Read-only."""
    n = _lim(limit, 15)
    try:
        rows = _q(LIMPIEZAS_DB,
                  "SELECT apto,ciudad,fecha_iso,estado,veredicto,ts FROM limpiezas "
                  "ORDER BY ts DESC LIMIT ?", (n,))
        return {"ok": True, "limpiezas": rows}
    except Exception as e:
        return {"ok": False, "error": "limpiezas.db: %s" % str(e)[:120]}


# ---------- Servicio al cliente (chat huespedes) ----------
@mcp.tool()
def chat_huespedes_reciente(limit: int = 20) -> dict:
    """Ultimos mensajes del chat de huespedes / servicio al cliente (chat.db):
    role, content, created_at. Read-only."""
    n = _lim(limit, 20)
    try:
        rows = _q(CHAT_DB,
                  "SELECT role, content, created_at FROM messages ORDER BY id DESC LIMIT ?", (n,))
        rows.reverse()  # orden cronologico
        return {"ok": True, "mensajes": rows}
    except Exception as e:
        return {"ok": False, "error": "chat.db: %s" % str(e)[:120]}


# ---------- Soporte (correos) ----------
@mcp.tool()
def soporte_casos(limit: int = 12, status: str = "") -> dict:
    """Casos de soporte de Airbnb por correo (cases.db): from_name, subject, summary,
    status, received_at. Opcional filtrar por status. Read-only."""
    n = _lim(limit, 12)
    try:
        if status:
            rows = _q(CASES_DB,
                      "SELECT from_name,subject,summary,status,received_at FROM cases "
                      "WHERE status=? ORDER BY received_at DESC LIMIT ?", (status, n))
        else:
            rows = _q(CASES_DB,
                      "SELECT from_name,subject,summary,status,received_at FROM cases "
                      "ORDER BY received_at DESC LIMIT ?", (n,))
        por_estado = _q(CASES_DB, "SELECT status, count(*) AS n FROM cases GROUP BY status")
        return {"ok": True, "casos": rows, "por_estado": por_estado}
    except Exception as e:
        return {"ok": False, "error": "cases.db: %s" % str(e)[:120]}


# ---------- Panorama combinado ----------
@mcp.tool()
def panorama() -> dict:
    """Foto rapida de TODO el equipo en una sola llamada: resumen de precios,
    ultimas limpiezas, ultimos mensajes de huespedes y casos de soporte. Read-only."""
    return {
        "precios": precios_resumen(),
        "precios_recientes": precios_recientes(limit=6),
        "limpiezas": limpiezas_recientes(limit=6),
        "chat_huespedes": chat_huespedes_reciente(limit=8),
        "soporte": soporte_casos(limit=6),
    }


if __name__ == "__main__":
    mcp.run()
