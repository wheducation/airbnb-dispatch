#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor MCP PANEL (Airbnb) — capa de COMPOSICION inteligente (read-only).
Fusiona lo que ya exponen los MCP primitivos (beds24 + fichas + las SQLite del equipo)
en herramientas analiticas de alto nivel, para que el cerebro no tenga que hacer 5 llamadas.

Reusa: airbnb_beds24 (calendario/reservas), rm_fichas (perfil/topes), y lee revenue.db /
limpiezas.db en modo read-only. NO reimplementa ni escribe nada.

Requisitos: pip install "mcp"
Registro (usuario dispatch):
  claude mcp add -s user panel -- python3 /opt/dispatch/projects/airbnb/panel_mcp.py
"""
import os
import re
import sqlite3
from datetime import date, timedelta

from mcp.server.fastmcp import FastMCP

try:
    import airbnb_beds24 as b24
except Exception as e:
    b24 = None
    _B24_ERR = str(e)
else:
    _B24_ERR = None

try:
    import rm_fichas
except Exception:
    rm_fichas = None

PROJ = os.path.dirname(os.path.abspath(__file__))
REVENUE_DB = os.environ.get("REVENUE_DB", os.path.join(PROJ, "revenue.db"))
LIMPIEZAS_DB = os.environ.get("LIMPIEZAS_DB", os.path.join(PROJ, "limpiezas.db"))

mcp = FastMCP("panel")


def _need_b24():
    if b24 is None:
        raise RuntimeError("airbnb_beds24 no disponible: %s" % _B24_ERR)


def _q(path, sql, args=()):
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    try:
        cur = con.execute(sql, args)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()


def _apto_de(nombre, room):
    mm = re.match(r"\s*([0-9]{2,5})", nombre or "")
    return mm.group(1) if mm else str(room.get("roomId") or room.get("id"))


def _booked_set(room_id, desde, hasta):
    try:
        return set(str(n) for n in (b24._real_booking_nights(room_id, desde, hasta) or []))
    except Exception:
        return set()


def _avail_map(room_id, desde, hasta):
    """{fecha: disponible(bool)} desde el calendario."""
    out = {}
    try:
        flat = b24._flatten_days(b24.get_calendar(room_id, desde, hasta))
        for f, info in (flat.items() if isinstance(flat, dict) else []):
            if not isinstance(info, dict):
                continue
            na = info.get("numAvail")
            out[f] = True if na is None else (float(na) > 0)
    except Exception:
        pass
    return out


@mcp.tool()
def huecos(room_id: str, desde: str, hasta: str) -> dict:
    """Noches HUERFANAS de un room_id: noches libres atrapadas entre noches reservadas
    (candidatas a bajar minimo/precio). Read-only."""
    _need_b24()
    booked = _booked_set(room_id, desde, hasta)
    d0, d1 = date.fromisoformat(desde), date.fromisoformat(hasta)
    avail = _avail_map(room_id, desde, hasta)
    libres = []
    d = d0
    while d < d1:
        f = d.isoformat()
        prev = (d - timedelta(days=1)).isoformat()
        nxt = (d + timedelta(days=1)).isoformat()
        es_libre = avail.get(f, f not in booked)
        if es_libre and (prev in booked) and (nxt in booked):
            libres.append(f)
        d += timedelta(days=1)
    return {"ok": True, "room_id": room_id, "huecos": libres, "n": len(libres)}


@mcp.tool()
def proximos_checkouts(dias: int = 14) -> dict:
    """Check-outs proximos en TODAS las propiedades (una noche reservada seguida de una
    libre = sale un huesped → toca limpieza). Util para el Supervisor de Limpiezas. Read-only."""
    _need_b24()
    try:
        dias = max(1, min(int(dias), 90))
    except Exception:
        dias = 14
    hoy = date.today()
    desde = hoy.isoformat()
    hasta = (hoy + timedelta(days=dias)).isoformat()
    out = []
    for r in b24.fetch_rooms():
        nombre = r.get("propertyName") or r.get("name") or ""
        rid = r.get("roomId") or r.get("id")
        apto = _apto_de(nombre, r)
        booked = _booked_set(rid, desde, hasta)
        for n in sorted(booked):
            try:
                nxt = (date.fromisoformat(n) + timedelta(days=1)).isoformat()
            except Exception:
                continue
            if nxt not in booked and date.fromisoformat(n) < (hoy + timedelta(days=dias)):
                out.append({"apto": apto, "room_id": rid, "checkout": nxt,
                            "ciudad": r.get("city")})
    out.sort(key=lambda x: (x["checkout"], str(x["apto"])))
    return {"ok": True, "dias": dias, "checkouts": out, "n": len(out)}


@mcp.tool()
def propiedad_360(apto: str, dias: int = 30) -> dict:
    """Foto COMPLETA de un apto en una sola llamada: ficha (topes, rating, diferenciales),
    ocupacion en vivo (Beds24), ultima limpieza y recomendaciones de precio pendientes.
    Read-only."""
    _need_b24()
    try:
        dias = max(1, min(int(dias), 180))
    except Exception:
        dias = 30
    apto = str(apto)
    hoy = date.today()
    desde, hasta = hoy.isoformat(), (hoy + timedelta(days=dias)).isoformat()

    # ficha
    ficha = rm_fichas.ficha(apto) if rm_fichas else None
    es_nightly = bool(rm_fichas.es_nightly(apto)) if rm_fichas else None

    # rooms de ese apto (puede haber varios room_id) + ocupacion
    rooms = []
    for r in b24.fetch_rooms():
        nombre = r.get("propertyName") or r.get("name") or ""
        if _apto_de(nombre, r) != apto:
            continue
        rid = r.get("roomId") or r.get("id")
        reservadas = len(_booked_set(rid, desde, hasta))
        total = max((date.fromisoformat(hasta) - hoy).days, 1)
        rooms.append({"room_id": rid, "nombre": nombre,
                      "noches_reservadas": reservadas, "noches_totales": total,
                      "ocupacion_pct": round(100.0 * reservadas / total, 1)})

    # ultima limpieza
    try:
        limp = _q(LIMPIEZAS_DB, "SELECT apto,ciudad,fecha_iso,estado,veredicto FROM limpiezas "
                  "WHERE apto=? ORDER BY ts DESC LIMIT 1", (apto,))
    except Exception:
        limp = []
    # precios pendientes
    try:
        recs = _q(REVENUE_DB, "SELECT desde,hasta,precio_actual,precio_sugerido,pct,motivo "
                  "FROM recomendaciones WHERE apto=? AND estado='pendiente' ORDER BY desde", (apto,))
    except Exception:
        recs = []

    return {"ok": True, "apto": apto, "es_nightly": es_nightly,
            "ficha": ficha, "rooms": rooms,
            "ultima_limpieza": (limp[0] if limp else None),
            "precios_pendientes": recs, "ventana_dias": dias}


if __name__ == "__main__":
    mcp.run()
