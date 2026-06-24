"""Cliente de la Memoria Compartida (solo recall).

Fail-safe por diseño: si la API de memoria está caída, lenta o devuelve error,
NUNCA debe tumbar ni bloquear la respuesta de Dispatch → devuelve [] / "".
Usa solo stdlib (urllib) para no depender de paquetes externos.
"""
import os
import json
import logging
import urllib.request

logger = logging.getLogger(__name__)

# NOTA: las env vars se leen perezosamente (en cada llamada), porque este módulo
# se importa ANTES de load_dotenv() en main.py.

# Cajón (slug) -> proyecto (scope en el vault).
# general / control -> dispatch = modo AMPLIO (ve todo el vault + comunes).
# Cualquier otro cajón sin match usa su propio nombre como proyecto
# (y si ese proyecto no existe en el vault, igual recibe los nodos comunes).
CAJON_PROYECTO = {
    "airbnb": "airbnb",
    "pdfs": "circuito-pdfs",
    "agencia": "agencia",
    "general": "dispatch",
    "control": "dispatch",
}


def recall_enabled():
    return os.getenv("MEMORIA_RECALL", "off").strip().lower() == "on"


def remember_enabled():
    return os.getenv("MEMORIA_REMEMBER", "off").strip().lower() == "on"


def remember(proyecto, texto, tipo="hecho"):
    """Guarda un recuerdo durable vía API /remember (vault_buffer + índice instantáneo).

    Fail-safe: ante cualquier fallo (API caída/lenta/error) devuelve False en silencio;
    NUNCA debe tumbar ni bloquear a Dispatch. Pensada para correr en executor.
    """
    if not texto or not texto.strip():
        return False
    api_url = os.getenv("MEM_API_URL", "http://127.0.0.1:8090")
    api_token = os.getenv("MEM_API_TOKEN", "")
    timeout = float(os.getenv("MEM_REMEMBER_TIMEOUT", "4"))
    payload = json.dumps({
        "proyecto": proyecto,
        "texto": texto.strip(),
        "tipo": (tipo or "hecho").strip(),
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    req = urllib.request.Request(
        api_url.rstrip("/") + "/remember",
        data=payload, headers=headers, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
        logger.info(f"remember guardado: proyecto={proyecto} tipo={tipo} ({len(texto)} chars)")
        return True
    except Exception as e:
        logger.warning(f"remember falló (memoria caída/lenta?), lo ignoro: {e}")
        return False


def proyecto_for_cajon(slug):
    s = (slug or "general").strip().lower()
    return CAJON_PROYECTO.get(s, s)


def recall(proyecto, query, k=6):
    """Llama a la API /recall. Devuelve lista de chunks o [] ante cualquier fallo."""
    if not query or not query.strip():
        return []
    api_url = os.getenv("MEM_API_URL", "http://127.0.0.1:8090")
    api_token = os.getenv("MEM_API_TOKEN", "")
    timeout = float(os.getenv("MEM_RECALL_TIMEOUT", "3"))
    payload = json.dumps({"proyecto": proyecto, "query": query, "k": k}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    req = urllib.request.Request(
        api_url.rstrip("/") + "/recall",
        data=payload, headers=headers, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read() or b"{}")
        return data.get("results", []) or []
    except Exception as e:
        logger.warning(f"recall falló (memoria caída/lenta?), sigo sin memoria: {e}")
        return []


def memory_block(slug, query, k=6):
    """Bloque de texto listo para inyectar al prompt, o '' si flag off / sin resultados.

    Respeta el flag MEMORIA_RECALL: si no está 'on', devuelve '' sin tocar la red.
    """
    if not recall_enabled():
        return ""
    proyecto = proyecto_for_cajon(slug)
    results = recall(proyecto, query, k=k)
    if not results:
        return ""
    lines = [
        "=" * 50,
        "MEMORIA RELEVANTE (recuperada de tu vault claude-mind; NO la repitas literal, "
        "úsala como contexto para responder mejor):",
        "=" * 50,
        "",
    ]
    for r in results:
        src = r.get("path", "?")
        heading = (r.get("heading") or "").strip()
        loc = f"{src} › {heading}" if heading else src
        texto = (r.get("texto") or "").strip()
        lines.append(f"— [{loc}]")
        lines.append(texto)
        lines.append("")
    return "\n".join(lines)
