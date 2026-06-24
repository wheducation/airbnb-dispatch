#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor MCP de FICHAS (Airbnb) — el perfil real de cada propiedad para cualquier cerebro.
Envuelve rm_fichas.py (que carga airbnb_fichas.json). SOLO LECTURA.

Hoy estas fichas solo las ve el Revenue Manager. Con este MCP, el CEO y cualquier agente
(actual o de futuras empresas) acceden a: piso/techo de precio, habitaciones, rating,
diferenciales, y la distincion clave NIGHTLY (el RM las maneja) vs MONTHLY (precio estable,
NO se tocan). Critico para el futuro guardrail de precios (validar contra piso/techo).

Reusa rm_fichas. No reimplementa nada.
Requisitos: pip install "mcp"
Registro (usuario dispatch):
  claude mcp add fichas -- python3 /opt/dispatch/projects/airbnb/fichas_mcp.py
"""
from mcp.server.fastmcp import FastMCP

try:
    import rm_fichas
except Exception as e:  # pragma: no cover
    rm_fichas = None
    _IMPORT_ERR = str(e)
else:
    _IMPORT_ERR = None

mcp = FastMCP("fichas")


def _need():
    if rm_fichas is None:
        raise RuntimeError("rm_fichas no disponible: %s" % _IMPORT_ERR)


@mcp.tool()
def lista_nightly() -> dict:
    """Lista los aptos NIGHTLY (corto plazo, los que el Revenue Manager maneja) con su
    resumen: ciudad, moneda, habitaciones, piso/techo de precio y rating. Los aptos que
    NO esten aca son MONTHLY (precio estable, no se tocan). Read-only."""
    _need()
    out = []
    for apto, f in (rm_fichas.fichas() or {}).items():
        out.append({
            "apto": apto,
            "ciudad": f.get("ciudad"),
            "moneda": f.get("moneda"),
            "habitaciones": f.get("habitaciones"),
            "capacidad": f.get("capacidad"),
            "rating": f.get("rating"),
            "precio_min": f.get("precio_min"),
            "precio_max": f.get("precio_max"),
        })
    out.sort(key=lambda x: str(x["apto"]))
    return {"ok": True, "nightly": out, "total": len(out)}


@mcp.tool()
def ficha(apto: str) -> dict:
    """Ficha completa de un apto NIGHTLY (direccion, titulo, amenities, diferenciales,
    rating_detalle, nota estrategica, comp_query, topes). Read-only."""
    _need()
    f = rm_fichas.ficha(apto)
    if not f:
        return {"ok": False, "error": "apto %s no es nightly o no existe ficha" % apto}
    return {"ok": True, "apto": str(apto), "ficha": f}


@mcp.tool()
def topes_precio(apto: str) -> dict:
    """Piso (precio_min) y techo (precio_max) + moneda de un apto. Es la barrera que el
    Revenue Manager / el futuro guardrail deben respetar. Read-only."""
    _need()
    f = rm_fichas.ficha(apto)
    if not f:
        return {"ok": False, "error": "apto %s sin ficha (no nightly?)" % apto}
    return {"ok": True, "apto": str(apto), "moneda": f.get("moneda"),
            "precio_min": f.get("precio_min"), "precio_max": f.get("precio_max")}


@mcp.tool()
def es_nightly(apto: str) -> dict:
    """Dice si un apto es NIGHTLY (lo maneja el RM) o MONTHLY (precio estable, no tocar).
    Read-only."""
    _need()
    return {"ok": True, "apto": str(apto), "es_nightly": bool(rm_fichas.es_nightly(apto))}


if __name__ == "__main__":
    mcp.run()
