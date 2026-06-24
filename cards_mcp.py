#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor MCP CARDS (Airbnb) — Agent Cards: la identidad de cada agente del equipo.
Lee agent_cards.json (quien es cada agente, que sabe, que MCP usa, a quien escala/handoff).

Para que sirve: el CEO (o cualquier orquestador) lee las cards para saber A QUIEN delegarle
cada cosa, y luego publica el handoff en la Sala de equipo via el MCP 'voz'. Es la capa de
identidad encima de los 7 MCP de herramientas.

SOLO LECTURA. Loader endurecido (no cachea vacio, reintenta) — leccion del bug de rm_fichas.
Requisitos: pip install "mcp"
Registro (usuario dispatch):
  claude mcp add -s user cards -- python3 /opt/dispatch/projects/airbnb/cards_mcp.py
"""
import json
import os
import time

from mcp.server.fastmcp import FastMCP

RUTA = os.environ.get("AGENT_CARDS",
                      os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_cards.json"))
_cache = {"data": None}

mcp = FastMCP("cards")


def _cargar():
    err = None
    for _ in range(3):
        try:
            with open(RUTA, encoding="utf-8") as f:
                data = json.load(f).get("agentes", {}) or {}
            if data:
                return data
        except Exception as e:
            err = e
        time.sleep(0.2)
    if err:
        print("cards: no pude cargar", RUTA, err)
    return {}


def _cards():
    if not _cache["data"]:
        _cache["data"] = _cargar()
    return _cache["data"] or {}


def _buscar(agente):
    """Resuelve por slug exacto o por nombre (case-insensitive, parcial)."""
    cards = _cards()
    a = str(agente).strip().lower()
    if a in cards:
        return a, cards[a]
    for slug, c in cards.items():
        if a == (c.get("nombre", "").lower()) or a in c.get("nombre", "").lower():
            return slug, c
    return None, None


@mcp.tool()
def lista_agentes() -> dict:
    """Lista todos los agentes del equipo con su slug, nombre, rol y estado. El CEO la usa
    para saber a quien delegar. Read-only."""
    out = []
    for slug, c in _cards().items():
        out.append({"slug": slug, "nombre": c.get("nombre"), "rol": c.get("rol"),
                    "estado": c.get("estado")})
    out.sort(key=lambda x: x["slug"])
    return {"ok": True, "n": len(out), "agentes": out}


@mcp.tool()
def card(agente: str) -> dict:
    """Ficha completa de un agente (por slug o nombre): rol, que hace, que MCP usa, a quien
    escala/delega/handoff, y que NO hace. Read-only."""
    slug, c = _buscar(agente)
    if not c:
        return {"ok": False, "error": "no encontre el agente '%s'" % agente,
                "disponibles": list(_cards().keys())}
    return {"ok": True, "slug": slug, "card": c}


@mcp.tool()
def quien_para(necesidad: str = "") -> dict:
    """Ayuda a delegar: devuelve las cards (rol + que_hace + delega_a/handoff_a) para que el
    CEO decida a quien mandarle una tarea. Si se pasa `necesidad`, igual devuelve todas
    (la decision la toma el cerebro leyendo los roles). Read-only."""
    out = []
    for slug, c in _cards().items():
        out.append({"slug": slug, "nombre": c.get("nombre"), "rol": c.get("rol"),
                    "que_hace": c.get("que_hace"),
                    "delega_a": c.get("delega_a", []), "handoff_a": c.get("handoff_a", []),
                    "escala_a": c.get("escala_a")})
    return {"ok": True, "necesidad": necesidad, "agentes": out}


if __name__ == "__main__":
    mcp.run()
