#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sala_worker — orquestador del BUCLE de la Sala de equipo (team_feed).
Hace que los agentes RESPONDAN automaticamente los handoffs que el CEO (u otro) les deja,
SIN tocar los bots vivos. Es la pieza-ensamblador encima de los agentes existentes.

Flujo de cada corrida:
1. Lee team_feed (proyecto airbnb) y toma los mensajes nuevos (id > last_id guardado).
2. Filtra los tipo='handoff' dirigidos (para=) a un agente VIVO de las Agent Cards.
3. Por cada uno (hasta SALA_WORKER_MAX), corre el cerebro del agente via el CLI de Claude
   con su card + tools de LECTURA, le pide SOLO el texto de la respuesta, y la postea UNA vez.
4. Avanza last_id solo hasta lo procesado (los que quedan por el tope se reintentan luego).

Seguridad:
- El agente-cerebro tiene prohibido postear/escribir; el worker hace el unico post (tipo=info).
- Solo procesa handoffs a agentes 'vivo'. No responde a sus propios posts (solo lee 'handoff').
- Fail-safe: si Postgres o el CLI fallan, saltea y sigue; nunca rompe.
- Tope por corrida (SALA_WORKER_MAX, default 5) para acotar costo.

Costo: cada respuesta = 1 llamada al CLI de Claude. Para abaratar, SALA_WORKER_MODEL puede
fijar un modelo mas barato (ej. haiku) — y a futuro un worker Nemotron (ver nota NVIDIA).

Uso:
  python3 sala_worker.py --dry-run   # muestra que haria, NO postea
  python3 sala_worker.py             # procesa y postea (idempotente via state file)
"""
import json
import os
import subprocess
import sys

import team_feed as tf

PROJ = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get("SALA_WORKER_STATE", os.path.join(PROJ, "sala_worker_state.json"))
CARDS = os.environ.get("AGENT_CARDS", os.path.join(PROJ, "agent_cards.json"))
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "/usr/bin/claude")
MODEL = os.environ.get("SALA_WORKER_MODEL", "").strip()
MAX_PER_RUN = int(os.environ.get("SALA_WORKER_MAX", "5"))
PROYECTO = "airbnb"
NL = chr(10)


def _cards():
    try:
        with open(CARDS, encoding="utf-8") as f:
            return json.load(f).get("agentes", {}) or {}
    except Exception:
        return {}


def _find_agent(para, cards):
    """Resuelve 'para' (slug o nombre) a (slug, card) de un agente vivo."""
    if not para:
        return None, None
    a = str(para).strip().lower()
    if a in cards:
        return a, cards[a]
    for slug, c in cards.items():
        nombre = (c.get("nombre") or "").lower()
        if a == nombre or (a in nombre) or (nombre and nombre in a):
            return slug, c
    return None, None


def _load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_id": 0}


def _save_state(last_id):
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump({"last_id": last_id}, f)
    except Exception as e:
        print("sala_worker: no pude guardar state:", e)


def _claude(prompt, timeout=200):
    cmd = [CLAUDE_BIN, "-p", prompt, "--dangerously-skip-permissions"]
    if MODEL:
        cmd += ["--model", MODEL]
    try:
        r = subprocess.run(cmd, cwd=PROJ, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "").strip()
    except Exception as e:
        print("sala_worker: claude error:", str(e)[:100])
        return ""


def _prompt_para_agente(card, sender, handoff_msg):
    nombre = card.get("nombre", "Agente")
    rol = card.get("rol", "")
    no_hace = card.get("no_hace", "")
    return (
        "Sos \"%s\" del equipo Airbnb. Tu rol: %s%s" % (
            nombre, rol, (" Lo que NO hacés: " + no_hace if no_hace else "")) + NL + NL +
        "Tenés herramientas MCP de LECTURA para informarte (equipo, panel, fichas, memoria, beds24, cards). "
        "En la Sala de equipo te llegó este handoff de \"%s\":" % sender + NL +
        "\"" + (handoff_msg or "").strip() + "\"" + NL + NL +
        "Tarea: si necesitás datos reales, usá tus tools de LECTURA. Luego redactá TU RESPUESTA para "
        "\"%s\" en primera persona, en español, CORTA (máx 600 caracteres): acusá recibo, decí tu plan "
        "concreto, y marcá qué necesita aprobación de Esteban." % sender + NL +
        "IMPORTANTE: NO uses ninguna tool de ESCRITURA (no postees en la sala, no cambies precios, no "
        "envíes correos). Devolveme SOLO el texto de tu respuesta, sin comillas ni preámbulo."
    )


def run(dry=False):
    cards = _cards()
    if not cards:
        print("sala_worker: sin agent_cards, no hago nada.")
        return
    rows = tf.fetch_feed(proyecto=PROYECTO, limit=200)  # mas reciente primero
    state = _load_state()
    last = int(state.get("last_id", 0) or 0)
    nuevos = sorted([r for r in rows if int(r.get("id", 0)) > last],
                    key=lambda r: int(r.get("id", 0)))
    if not nuevos:
        print("sala_worker: nada nuevo (last_id=%d)." % last)
        return

    new_last = last
    procesados = 0
    for r in nuevos:
        rid = int(r.get("id", 0))
        es_handoff = (r.get("tipo") == "handoff") and r.get("para")
        if not es_handoff:
            new_last = rid  # no es handoff: avanzo y sigo
            continue
        if procesados >= MAX_PER_RUN:
            break  # tope alcanzado: NO avanzo, se reintenta la proxima corrida
        slug, card = _find_agent(r.get("para"), cards)
        if not card or card.get("estado") != "vivo":
            new_last = rid  # handoff a alguien que no existe/no vivo: lo dejo pasar
            continue
        sender = r.get("agente", "CEO Airbnb")
        if (card.get("nombre") or "").lower() == str(sender).lower():
            new_last = rid  # no se responde a si mismo
            continue
        resp = _claude(_prompt_para_agente(card, sender, r.get("mensaje", "")))
        resp = (resp or "").strip()[:1900]
        if not resp:
            print("sala_worker: %s no produjo respuesta para handoff #%d (saltea)." % (card.get("nombre"), rid))
            # no avanzo new_last para reintentar luego
            break
        if dry:
            print("== DRY-RUN handoff #%d ==" % rid)
            print("  para:", card.get("nombre"), "| de:", sender)
            print("  handoff:", (r.get("mensaje") or "")[:120])
            print("  respondería:", resp[:300])
        else:
            ok = tf.post_feed(card.get("nombre"), resp, para=sender, tipo="info", proyecto=PROYECTO)
            print("sala_worker: %s respondió handoff #%d -> post ok=%s" % (card.get("nombre"), rid, ok))
        new_last = rid
        procesados += 1

    if not dry:
        _save_state(new_last)
    print("sala_worker: %d handoff(s) procesado(s). last_id %d -> %d%s" % (
        procesados, last, new_last, " (dry-run, no guardé state)" if dry else ""))


if __name__ == "__main__":
    run(dry=("--dry-run" in sys.argv))
