#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor MCP de MEMORIA (compartida, agentes-os) — memoria de LARGO PLAZO para cualquier cerebro.
Envuelve memoria_client.py (cliente HTTP fail-safe a la API de memoria en MEM_API_URL).
NO habla con Postgres directo: el cliente pega a la API, que toca pgvector.

Hoy la memoria la usan algunos bots cableados a mano detras de flags. Con este MCP, el CEO,
el Revenue y los agentes de futuras empresas hacen recall/remember de forma uniforme.

Seguridad / consistencia con el sistema:
- recall / bloque_memoria = LECTURA → libres (fail-safe: si la API esta caida devuelven vacio).
- recordar (remember) = ESCRITURA → honra el flag MEMORIA_REMEMBER (como el resto del sistema).
  Si el flag no esta 'on', no escribe y lo dice.

Carga el .env del proyecto (MEM_API_URL, MEM_API_TOKEN, flags, timeouts) igual que ceo.py.
Requisitos: pip install "mcp"
Registro (usuario dispatch):
  claude mcp add memoria -- python3 /opt/dispatch/projects/airbnb/memoria_mcp.py
"""
import os

from mcp.server.fastmcp import FastMCP

PROJ = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.environ.get("AIRBNB_ENV", os.path.join(PROJ, ".env"))


def load_env():
    """Carga el .env del proyecto (mismo patron que ceo.py) para tener MEM_API_URL,
    MEM_API_TOKEN y los flags MEMORIA_* disponibles cuando el CLI spawnea este server."""
    if os.path.exists(ENV_PATH):
        for line in open(ENV_PATH):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()

try:
    import memoria_client as mem
except Exception as e:  # pragma: no cover
    mem = None
    _IMPORT_ERR = str(e)
else:
    _IMPORT_ERR = None

mcp = FastMCP("memoria")

TIPOS_OK = ("decision", "aprendizaje", "hecho")
# scopes oficiales del vault (de _CLAUDE.md / CAJON_PROYECTO)
SCOPES = ("airbnb", "circuito-pdfs", "agencia", "dispatch", "meta-ads",
          "cazador-carros", "asistente-personal", "helios", "esteban-club")


def _need():
    if mem is None:
        raise RuntimeError("memoria_client no disponible: %s" % _IMPORT_ERR)


@mcp.tool()
def recall(query: str, proyecto: str = "airbnb", k: int = 6) -> dict:
    """Busca en la memoria compartida (largo plazo) lo relevante a `query` dentro de un
    `proyecto`/scope (default airbnb). Devuelve chunks con path, heading y texto.
    LECTURA, fail-safe: si la memoria esta caida devuelve lista vacia. """
    _need()
    try:
        k = max(1, min(int(k), 20))
    except Exception:
        k = 6
    try:
        results = mem.recall(proyecto, query, k=k)
        return {"ok": True, "proyecto": proyecto, "query": query,
                "n": len(results), "results": results}
    except Exception as e:
        return {"ok": False, "error": str(e)[:160], "results": []}


@mcp.tool()
def bloque_memoria(query: str, cajon: str = "airbnb", k: int = 6) -> dict:
    """Igual que recall pero devuelve el bloque 'MEMORIA RELEVANTE' ya formateado para
    inyectar al prompt. Mapea cajon->scope (airbnb, pdfs, agencia, general/control).
    Respeta el flag MEMORIA_RECALL (si esta off devuelve vacio). LECTURA."""
    _need()
    try:
        k = max(1, min(int(k), 20))
    except Exception:
        k = 6
    bloque = mem.memory_block(cajon, query, k=k)
    return {"ok": True, "cajon": cajon, "proyecto": mem.proyecto_for_cajon(cajon),
            "vacio": not bool(bloque), "bloque": bloque}


@mcp.tool()
def recordar(texto: str, tipo: str = "hecho", proyecto: str = "airbnb") -> dict:
    """Guarda un recuerdo DURABLE en la memoria compartida (decision/aprendizaje/hecho).
    ESCRITURA: honra el flag MEMORIA_REMEMBER del sistema; si no esta 'on', NO escribe.
    Usar solo para cosas que valga la pena recordar (decisiones, aprendizajes, hechos
    durables), nunca trivialidades. Fail-safe."""
    _need()
    if not texto or not texto.strip():
        return {"ok": False, "error": "texto vacio"}
    if not mem.remember_enabled():
        return {"ok": False, "error": "remember desactivado (MEMORIA_REMEMBER off). "
                                      "No se guardo nada."}
    t = (tipo or "hecho").strip().lower()
    if t not in TIPOS_OK:
        t = "hecho"
    ok = mem.remember(proyecto, texto.strip(), tipo=t)
    return {"ok": bool(ok), "proyecto": proyecto, "tipo": t,
            "guardado": bool(ok),
            "error": None if ok else "la API de memoria no confirmo (caida/lenta?)"}


@mcp.tool()
def estado() -> dict:
    """Estado de la memoria: flags recall/remember, URL de la API (sin token) y scopes
    validos. Util para diagnosticar si la memoria esta activa."""
    _need()
    return {
        "ok": True,
        "recall_enabled": mem.recall_enabled(),
        "remember_enabled": mem.remember_enabled(),
        "api_url": os.getenv("MEM_API_URL", "http://127.0.0.1:8090"),
        "scopes": list(SCOPES),
        "tipos": list(TIPOS_OK),
    }


if __name__ == "__main__":
    mcp.run()
