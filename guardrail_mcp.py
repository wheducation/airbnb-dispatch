#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor MCP GUARDRAIL (Airbnb) — el freno de PLATA, deterministico.
Valida CUALQUIER precio propuesto contra la politica antes de que nadie lo aplique.
Es el cumplimiento formal de la regla de oro: la plata la aprueba Esteban.

Por que deterministico y NO un LLM: validar piso/techo/% es una verificacion numerica;
en Python puro es mas confiable, instantanea y sin dependencias. (NeMo Guardrails se puede
sumar despues como 2a capa sobre lo que el cerebro PROPONE en lenguaje natural.)

Reusa rm_fichas (topes piso/techo + nightly vs monthly). NO escribe nada, NO aplica precios:
solo dice PERMITIDO / BLOQUEADO + motivo. Aplicar sigue requiriendo aprobacion de Esteban.

Politica (configurable por env):
  GUARDRAIL_MAX_PCT_STEP  salto maximo por cambio vs precio actual (default 0.30 = 30%)

Requisitos: pip install "mcp"
Registro (usuario dispatch):
  claude mcp add -s user guardrail -- python3 /opt/dispatch/projects/airbnb/guardrail_mcp.py
"""
import os

from mcp.server.fastmcp import FastMCP

try:
    import rm_fichas
except Exception as e:
    rm_fichas = None
    _ERR = str(e)
else:
    _ERR = None

mcp = FastMCP("guardrail")

MAX_PCT_STEP = float(os.environ.get("GUARDRAIL_MAX_PCT_STEP", "0.30"))


def _need():
    if rm_fichas is None:
        raise RuntimeError("rm_fichas no disponible: %s" % _ERR)


@mcp.tool()
def validar_precio(apto: str, precio: float, precio_actual: float = 0) -> dict:
    """Valida un precio propuesto para un apto contra la politica de plata. Devuelve si
    esta PERMITIDO (dentro de piso/techo, apto nightly, salto razonable) o BLOQUEADO con
    motivo. NUNCA aplica: aplicar requiere aprobacion de Esteban. `precio_actual` opcional
    para chequear que el salto no sea brusco."""
    _need()
    apto = str(apto)
    try:
        precio = float(precio)
    except Exception:
        return {"ok": False, "permitido": False, "motivo": "precio no numerico"}

    if not rm_fichas.es_nightly(apto):
        return {"ok": True, "apto": apto, "permitido": False,
                "motivo": "apto MONTHLY (o sin ficha): precio estable, no se toca"}
    f = rm_fichas.ficha(apto) or {}
    pmin = f.get("precio_min")
    pmax = f.get("precio_max")
    moneda = f.get("moneda")
    motivos = []
    permitido = True

    if pmin is not None and precio < pmin:
        permitido = False
        motivos.append("debajo del piso (%s < %s %s)" % (precio, pmin, moneda))
    if pmax is not None and precio > pmax:
        permitido = False
        motivos.append("arriba del techo (%s > %s %s)" % (precio, pmax, moneda))
    if precio_actual and precio_actual > 0:
        pct = abs(precio - precio_actual) / precio_actual
        if pct > MAX_PCT_STEP:
            permitido = False
            motivos.append("salto brusco (%.0f%% > tope %.0f%%)" % (pct * 100, MAX_PCT_STEP * 100))

    return {
        "ok": True, "apto": apto, "precio": precio, "moneda": moneda,
        "precio_min": pmin, "precio_max": pmax,
        "permitido": permitido,
        "requiere_aprobacion": True,  # regla de oro: SIEMPRE
        "motivo": "dentro de politica; falta aprobacion de Esteban" if permitido
                  else "; ".join(motivos),
    }


@mcp.tool()
def politica(apto: str = "") -> dict:
    """Devuelve la politica de plata vigente. Sin apto: reglas generales. Con apto: sus
    topes (piso/techo) y si es nightly. Read-only."""
    _need()
    base = {
        "ok": True,
        "reglas": [
            "Solo aptos NIGHTLY se pueden re-precificar; los MONTHLY no se tocan.",
            "El precio debe estar entre precio_min (piso) y precio_max (techo) de la ficha.",
            "El salto vs precio actual no debe superar el %d%% (GUARDRAIL_MAX_PCT_STEP)." % int(MAX_PCT_STEP * 100),
            "TODO cambio de precio requiere aprobacion de Esteban (regla de oro), aunque pase la validacion.",
        ],
        "max_pct_step": MAX_PCT_STEP,
    }
    if apto:
        apto = str(apto)
        f = rm_fichas.ficha(apto) or {}
        base["apto"] = apto
        base["es_nightly"] = bool(rm_fichas.es_nightly(apto))
        base["precio_min"] = f.get("precio_min")
        base["precio_max"] = f.get("precio_max")
        base["moneda"] = f.get("moneda")
    return base


if __name__ == "__main__":
    mcp.run()
