#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""team_feed — sala de equipo de los agentes (Postgres: tabla team_feed).

Helper chico y FAIL-SAFE: si la base falla, NUNCA rompe al agente que lo llama.
Lo usan los agentes de Airbnb para "hablar" en lenguaje natural y el dashboard
para renderizar la sala (estilo Teams).

Uso:
    from team_feed import post_feed
    post_feed("Supervisor Limpiezas", "Confirme limpieza del 1224 (check-out hoy).")
    post_feed("Chat Huespedes", "Le respondi al huesped del 402.", para="Danos", tipo="handoff")
"""
import os

# --- credenciales de Postgres (mismas que el resto de agentes-os) ---
_ENV_PATH = "/opt/agentes-os/.env"


def _load_env(path):
    env = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return env


def _pg():
    env = _load_env(_ENV_PATH)
    return dict(
        host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        user=os.environ.get("POSTGRES_USER", env.get("POSTGRES_USER", "")),
        password=os.environ.get("POSTGRES_PASSWORD", env.get("POSTGRES_PASSWORD", "")),
        dbname=os.environ.get("POSTGRES_DB", env.get("POSTGRES_DB", "")),
    )


def post_feed(agente, mensaje, para=None, tipo="info", proyecto="airbnb"):
    """Inserta una fila en team_feed. Devuelve True/False. NUNCA lanza excepcion."""
    try:
        import psycopg2
        conn = psycopg2.connect(connect_timeout=4, **_pg())
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO team_feed (proyecto, agente, para, tipo, mensaje) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (proyecto, str(agente)[:80], (str(para)[:80] if para else None),
                     str(tipo)[:20], str(mensaje)[:2000]),
                )
            return True
        finally:
            conn.close()
    except Exception:
        return False


def fetch_feed(proyecto="airbnb", limit=200, agente=None):
    """Lee el feed (mas reciente primero). Devuelve lista de dicts. Fail-safe -> []."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(connect_timeout=4, **_pg())
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if agente:
                    cur.execute(
                        "SELECT id, ts, proyecto, agente, para, tipo, mensaje FROM team_feed "
                        "WHERE proyecto=%s AND agente=%s ORDER BY ts DESC LIMIT %s",
                        (proyecto, agente, limit))
                else:
                    cur.execute(
                        "SELECT id, ts, proyecto, agente, para, tipo, mensaje FROM team_feed "
                        "WHERE proyecto=%s ORDER BY ts DESC LIMIT %s",
                        (proyecto, limit))
                return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception:
        return []


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        ok = post_feed(sys.argv[1], sys.argv[2],
                       para=(sys.argv[3] if len(sys.argv) > 3 else None),
                       tipo=(sys.argv[4] if len(sys.argv) > 4 else "info"))
        print("post_feed:", ok)
    else:
        rows = fetch_feed(limit=10)
        print("ultimas %d:" % len(rows))
        for r in rows:
            print(" -", r["ts"], r["agente"], "->", r.get("para"), ":", r["mensaje"][:60])
