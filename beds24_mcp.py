#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor MCP de Beds24 (Airbnb).
Envuelve el modulo existente `airbnb_beds24` (b24) y expone sus capacidades como
herramientas MCP que el CLI de Claude (CEO, Revenue Manager, etc.) puede llamar EN VIVO.

Diseno (lecciones del vault):
- REUSA airbnb_beds24, no reimplementa nada.
- Pieza chica y modular (no toca dashboard.py ni los bots).
- SOLO LECTURA por defecto. Tocar precios = plata = aprobacion de Esteban.
  La escritura (cambiar_precio) queda DESACTIVADA salvo que BEDS24_MCP_ALLOW_WRITE=1,
  y aun asi solo deberia activarse cuando exista el guardrail de plata.
  El camino normal de precios sigue siendo el boton de aprobacion del Revenue Manager.

Transport: stdio (lo que consume el CLI de Claude para servidores MCP locales).

Requisitos: pip install "mcp[cli]"
Registro en el server (usuario dispatch):
  claude mcp add beds24 -- python3 /opt/dispatch/projects/airbnb/beds24_mcp.py
"""
import os
import re
from datetime import date, timedelta

from mcp.server.fastmcp import FastMCP

try:
    import airbnb_beds24 as b24
except Exception as e:  # pragma: no cover - en el server si esta
    b24 = None
    _IMPORT_ERR = str(e)
else:
    _IMPORT_ERR = None

mcp = FastMCP("beds24")

ALLOW_WRITE = os.environ.get("BEDS24_MCP_ALLOW_WRITE", "0") == "1"


# ---------- helpers (mismo criterio que revenue_manager.snapshot) ----------
def _ciudad_de(nombre, room=None):
    if room and room.get("city"):
        return room["city"]
    t = (nombre or "").lower()
    if any(x in t for x in ("medell", "poblado", "colombia", "(med)")):
        return "Medellin"
    if "austin" in t or "(aus)" in t:
        return "Austin"
    return "San Antonio"


def _apto_de(nombre, room):
    mm = re.match(r"\s*([0-9]{2,5})", nombre or "")
    return mm.group(1) if mm else str(room.get("roomId") or room.get("id"))


def _hab_de(nombre):
    br = re.search(r"([0-9])\s*BR", nombre or "", re.I)
    return int(br.group(1)) if br else 1


def _need_b24():
    if b24 is None:
        raise RuntimeError("airbnb_beds24 no disponible: %s" % _IMPORT_ERR)


# ---------- herramientas de LECTURA ----------
@mcp.tool()
def listar_propiedades() -> list:
    """Lista las propiedades/habitaciones de Beds24 con su apto, room_id, ciudad,
    numero de habitaciones (hab) y moneda. Util para saber sobre que room_id operar."""
    _need_b24()
    out = []
    for r in b24.fetch_rooms():
        nombre = r.get("propertyName") or r.get("name") or ""
        out.append({
            "apto": _apto_de(nombre, r),
            "room_id": r.get("roomId") or r.get("id"),
            "ciudad": _ciudad_de(nombre, r),
            "hab": _hab_de(nombre),
            "moneda": "COP" if _ciudad_de(nombre, r) == "Medellin" else "USD",
            "nombre": nombre,
        })
    return out


@mcp.tool()
def ver_calendario(room_id: str, desde: str, hasta: str) -> list:
    """Calendario de un room_id entre dos fechas (YYYY-MM-DD): por cada dia devuelve
    fecha, disponible (bool), precio y minStay. Fechas inclusivas."""
    _need_b24()
    cal = b24.get_calendar(room_id, desde, hasta)
    flat = b24._flatten_days(cal)
    dias = []
    for fecha, info in (flat.items() if isinstance(flat, dict) else []):
        if not isinstance(info, dict):
            continue
        na = info.get("numAvail")
        try:
            disp = True if na is None else float(na) > 0
        except Exception:
            disp = True
        try:
            precio = float(info.get("price")) if info.get("price") is not None else None
        except Exception:
            precio = None
        dias.append({
            "fecha": fecha,
            "disponible": disp,
            "precio": precio,
            "minStay": info.get("minStay"),
        })
    dias.sort(key=lambda d: d["fecha"])
    return dias


@mcp.tool()
def noches_reservadas(room_id: str, desde: str, hasta: str) -> list:
    """Lista de noches realmente reservadas (YYYY-MM-DD) de un room_id en el rango.
    Sirve para detectar check-outs y calcular ocupacion real."""
    _need_b24()
    noches = b24._real_booking_nights(room_id, desde, hasta)
    try:
        return sorted(str(n) for n in noches)
    except Exception:
        return list(noches)


@mcp.tool()
def ocupacion(room_id: str, desde: str, hasta: str) -> dict:
    """% de ocupacion real de un room_id en el rango (noches reservadas / noches totales).
    Devuelve noches_totales, noches_reservadas, noches_libres y ocupacion_pct."""
    _need_b24()
    d0 = date.fromisoformat(desde)
    d1 = date.fromisoformat(hasta)
    total = max((d1 - d0).days, 1)
    reservadas = len(b24._real_booking_nights(room_id, desde, hasta) or [])
    pct = round(100.0 * reservadas / total, 1)
    return {
        "room_id": room_id,
        "desde": desde,
        "hasta": hasta,
        "noches_totales": total,
        "noches_reservadas": reservadas,
        "noches_libres": total - reservadas,
        "ocupacion_pct": pct,
    }


# ---------- herramienta de ESCRITURA (desactivada por defecto) ----------
@mcp.tool()
def cambiar_precio(room_id: str, desde: str, hasta: str, precio: int) -> dict:
    """[PLATA] Cambia el precio de un room_id en un rango. DESACTIVADA salvo
    BEDS24_MCP_ALLOW_WRITE=1. Regla de oro: los precios los aprueba Esteban; el
    camino normal sigue siendo el boton del Revenue Manager. No usar sin guardrail."""
    if not ALLOW_WRITE:
        return {"ok": False, "error": "escritura desactivada (BEDS24_MCP_ALLOW_WRITE != 1). "
                                      "Los precios se aprueban por el Revenue Manager."}
    _need_b24()
    setter = getattr(b24, "set_calendar", None)
    if setter is None:
        return {"ok": False, "error": "set_calendar no disponible en airbnb_beds24"}
    try:
        setter(room_id, desde, hasta, price=precio)
        return {"ok": True, "room_id": room_id, "desde": desde, "hasta": hasta, "precio": precio}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


if __name__ == "__main__":
    mcp.run()
