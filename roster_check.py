#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
roster_check.py — diagnostico READ-ONLY del roster de Beds24.
Clasifica cada room en VIVO / DUPLICADO / CONGELADO para limpiar el roster
sin borrar a ciegas (regla del vault: investigar antes de tocar).

Reusa airbnb_beds24. No cambia nada (no llama set_calendar).
Uso:  python3 roster_check.py            # tabla + agrupado por apto fisico
      python3 roster_check.py --dias 90  # ventana (default 90)
"""
import re
import sys
from collections import defaultdict
from datetime import date, timedelta

import airbnb_beds24 as b24

DIAS = 90
if "--dias" in sys.argv:
    try:
        DIAS = int(sys.argv[sys.argv.index("--dias") + 1])
    except Exception:
        pass


def apto_de(nombre, room):
    mm = re.match(r"\s*([0-9]{2,5})", nombre or "")
    return mm.group(1) if mm else str(room.get("roomId") or room.get("id"))


def analizar():
    hoy = date.today()
    desde = hoy.isoformat()
    hasta = (hoy + timedelta(days=DIAS)).isoformat()
    rooms = b24.fetch_rooms()
    filas = []
    for r in rooms:
        nombre = r.get("propertyName") or r.get("name") or ""
        rid = r.get("roomId") or r.get("id")
        apto = apto_de(nombre, r)
        libres = precios_none = total = 0
        reservadas = 0
        try:
            flat = b24._flatten_days(b24.get_calendar(rid, desde, hasta))
            for _f, info in (flat.items() if isinstance(flat, dict) else []):
                if not isinstance(info, dict):
                    continue
                total += 1
                na = info.get("numAvail")
                disp = True if na is None else (float(na) > 0)
                if disp:
                    libres += 1
                if info.get("price") in (None, "", 0):
                    precios_none += 1
        except Exception as e:
            nombre += " (cal error: %s)" % str(e)[:40]
        try:
            reservadas = len(b24._real_booking_nights(rid, desde, hasta) or [])
        except Exception:
            reservadas = -1
        # Heuristica de estado
        if total and precios_none == total and libres == 0:
            estado = "CONGELADO"   # sin precio y sin disponibilidad = pausado a nivel canal
        elif reservadas == 0 and libres == 0 and total:
            estado = "CERRADO"
        else:
            estado = "VIVO"
        filas.append({"apto": apto, "room_id": rid, "nombre": nombre[:42],
                      "total": total, "libres": libres, "reservadas": reservadas,
                      "precio_none": precios_none, "estado": estado})
    return filas


def main():
    filas = analizar()
    print("ROSTER BEDS24 — %d rooms — ventana %d dias\n" % (len(filas), DIAS))
    print("%-6s %-8s %-9s %5s %6s %6s %6s  %s" % (
        "apto", "room_id", "estado", "tot", "libre", "resv", "p=None", "nombre"))
    for f in sorted(filas, key=lambda x: (x["apto"], str(x["room_id"]))):
        print("%-6s %-8s %-9s %5d %6d %6d %6d  %s" % (
            f["apto"], f["room_id"], f["estado"], f["total"], f["libres"],
            f["reservadas"], f["precio_none"], f["nombre"]))
    # Agrupado por apto fisico → detectar duplicados
    g = defaultdict(list)
    for f in filas:
        g[f["apto"]].append(f)
    dups = {k: v for k, v in g.items() if len(v) > 1}
    if dups:
        print("\n== APTOS CON VARIOS ROOM_ID (posibles duplicados) ==")
        for apto, v in sorted(dups.items()):
            ids = ", ".join("%s[%s]" % (x["room_id"], x["estado"]) for x in v)
            print("  apto %s → %d rooms: %s" % (apto, len(v), ids))
    print("\nNota: VIVO = vendible; CONGELADO = sin precio y sin dispo (pausado en canal); "
          "CERRADO = sin dispo. Nada de esto se modifico (read-only).")


if __name__ == "__main__":
    main()
