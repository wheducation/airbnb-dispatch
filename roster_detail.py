#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
roster_detail.py — detalle READ-ONLY de los rooms sospechosos (duplicados / sin venta).
Vuelca el dict CRUDO de Beds24 de cada room para ver listingId, propertyId y mapeo de
canales (Airbnb / Vrbo / Booking) → para decidir cuales cerrar SIN riesgo de doble reserva.

Reusa airbnb_beds24. No cambia nada.
Uso:  python3 roster_detail.py                 # aptos duplicados + Luxury (auto)
      python3 roster_detail.py 690346 695315   # room_ids especificos
"""
import json
import re
import sys
from collections import defaultdict

import airbnb_beds24 as b24


def apto_de(nombre, room):
    mm = re.match(r"\s*([0-9]{2,5})", nombre or "")
    return mm.group(1) if mm else str(room.get("roomId") or room.get("id"))


def main():
    rooms = b24.fetch_rooms()
    pedidos = set(sys.argv[1:])  # room_ids explicitos opcionales

    # auto: rooms cuyo apto fisico tiene >1 room_id, + los sin numero (ej. Luxury)
    porapto = defaultdict(list)
    for r in rooms:
        nombre = r.get("propertyName") or r.get("name") or ""
        porapto[apto_de(nombre, r)].append(r)

    objetivo = []
    for apto, lst in porapto.items():
        nombre0 = lst[0].get("propertyName") or lst[0].get("name") or ""
        es_dup = len(lst) > 1
        sin_numero = not re.match(r"\s*[0-9]{2,5}", nombre0)
        for r in lst:
            rid = str(r.get("roomId") or r.get("id"))
            if pedidos:
                if rid in pedidos:
                    objetivo.append((apto, r))
            elif es_dup or sin_numero:
                objetivo.append((apto, r))

    print("=== DETALLE CRUDO DE ROOMS SOSPECHOSOS (%d) ===\n" % len(objetivo))
    # primero, que llaves trae cada room (para saber donde mirar canales)
    if objetivo:
        print("Llaves disponibles en el dict de room:")
        print("  " + ", ".join(sorted(objetivo[0][1].keys())) + "\n")

    for apto, r in sorted(objetivo, key=lambda x: (x[0], str(x[1].get("roomId") or x[1].get("id")))):
        rid = r.get("roomId") or r.get("id")
        print("---- apto %s · room_id %s ----" % (apto, rid))
        print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
        print()

    print("Nada se modifico (read-only). Buscar en el JSON: listingId / propertyId / "
          "channels / roomQty para entender si son canales linkeados o duplicados sueltos.")


if __name__ == "__main__":
    main()
