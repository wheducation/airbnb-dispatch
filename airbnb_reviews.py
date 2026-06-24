#!/usr/bin/env python3
"""
airbnb_reviews.py - Robot de reviews automaticas estilo "host de verdad".

CONTEXTO
--------
Beds24 ya postea la review automatica (campo "Auto Review Text", 5 estrellas)
~4 dias despues de cada checkout, personalizada con [GUESTFIRSTNAME] y
[PROPERTYCITY]. Eso ya quedo configurado en los 16 listings.

Este robot es la capa de AVISOS + GUARDIA por encima de eso:

  1) AVISOS (lo que pediste: "que me diga que review le puso a quien"):
     - host -> huesped : que review automatica salio, a que huesped, en que
                         apto, con que texto y rating.
     - huesped -> host : que review te dejo cada huesped, apto y rating.
     Cada aviso sale UNA sola vez (memoria en .reviews_seen.json).

  2) HEADS-UP DE GUARDIA (lo que pediste: "guardia para no resenar a un huesped
     problema"): antes de que se dispare la review automatica, lista los
     checkouts recientes que van a recibir 5 estrellas, CON EL TEXTO EXACTO que
     se va a postear (plantilla + nombre + ciudad), para que puedas vetar a
     alguien a tiempo.

  3) VETO (opcional y SEGURO por defecto): si pones un bookingId o un nombre en
     /opt/dispatch/projects/airbnb/no_review.txt, el robot lo detecta y te avisa
     para que le quites "Allow Review" en Beds24. Si activas la variable de
     entorno AIRBNB_REVIEWS_AUTODISABLE=1, ademas intenta desactivar la review
     automatica de esa reserva por API (ver _disable_auto_review).

Reusa airbnb_beds24.py (mismo cliente probado que ya usan watchdog y gaps).

USO
---
  python3 airbnb_reviews.py            # ciclo normal: avisos nuevos + heads-up
  python3 airbnb_reviews.py --quiet    # solo avisa si hay algo nuevo (ideal cron)
  python3 airbnb_reviews.py --probe    # imprime el JSON CRUDO de reviews/bookings
                                       #   (para confirmar nombres de campos)
  python3 airbnb_reviews.py --test     # muestra lo que haria, NO guarda estado
  python3 airbnb_reviews.py --days 30  # ventana de dias (def 21)
  python3 airbnb_reviews.py --backfill # marca como visto todo lo viejo sin avisar
                                       #   (corre esto UNA vez al instalar para no
                                       #    spamear con reviews historicas)
"""
import sys
import os
import json
import datetime
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import airbnb_beds24 as b  # mismo directorio

DAY = datetime.timedelta(days=1)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEEN_FILE = os.path.join(BASE_DIR, ".reviews_seen.json")
VETO_FILE = os.path.join(BASE_DIR, "no_review.txt")

# Beds24 postea la review automatica ~4 dias despues del checkout.
AUTO_REVIEW_DELAY_DAYS = 4

# Plantillas de Auto Review Text aplicadas en Beds24 (repartidas T1-T4 por listing).
# Sirven para PREVISUALIZAR el texto exacto que Beds24 va a postear, sin depender del
# endpoint de reviews. [GUESTFIRSTNAME] -> nombre real del huesped ; [PROPERTYCITY] ->
# ciudad del property (se resuelve por API; si no se puede, se deja el placeholder).
TEMPLATES = {
    "T1": ("It was a real pleasure hosting [GUESTFIRSTNAME] here in [PROPERTYCITY]! "
           "Super easy communication, treated the apartment with care, and left "
           "everything spotless. Any host would be lucky to have them. Come back "
           "anytime \U0001f64c"),
    "T2": ("[GUESTFIRSTNAME] was a wonderful guest during their stay in [PROPERTYCITY]. "
           "Respectful, tidy, and great to chat with throughout. Followed every house "
           "rule and left the place perfect. Highly recommended to other hosts ⭐ "
           "Hope to see you again!"),
    "T3": ("Hosting [GUESTFIRSTNAME] in [PROPERTYCITY] was a breeze! Clear communication, "
           "smooth check in, and real care for the space. Exactly the kind of guest you "
           "hope for. Welcome back whenever you're in [PROPERTYCITY] \U0001f306"),
    "T4": ("What a pleasure to have [GUESTFIRSTNAME] staying with us in [PROPERTYCITY]! "
           "Friendly, respectful, and left the apartment just as they found it. A genuine "
           "5-star guest from start to finish. Welcome back soon \U0001f64f"),
}

# roomId -> plantilla asignada (confirmado al guardar el Auto Review Text en cada listing).
ROOM_TEMPLATE = {
    "689885": "T1",  # 1105
    "689874": "T2",  # 1224
    "689884": "T3",  # 1922
    "690330": "T4",  # 207
    "689869": "T1",  # 2208
    "690345": "T2",  # 2208 (2)
    "689872": "T4",  # 2715
    "689873": "T1",  # 3301
    "689881": "T2",  # 402
    "689883": "T3",  # 4065
    "689866": "T4",  # 419
    "689879": "T1",  # 602
    "689878": "T2",  # 802
    "689887": "T3",  # 802 (2)
    "690344": "T4",  # 802 (3)
    "690346": "T3",  # 2523 (desconectado de Beds24)
}


# --------------------------------------------------------------------------
# Utilidades base (mismas que watchdog/gaps)
# --------------------------------------------------------------------------
def _opt(args, name, default=None):
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            return args[i + 1]
    return default


def _read_env(path="/opt/dispatch/bot/.env"):
    env = {}
    try:
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env


def _tg_send(text):
    env = _read_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TG_CHAT_ID") or env.get("ALLOWED_USER_ID")
    if not token or not chat:
        return
    data = json.dumps({"chat_id": chat, "text": text,
                       "disable_web_page_preview": True}).encode()
    req = urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % token,
                                 data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except Exception:
        pass


def _load_seen():
    try:
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    except Exception:
        return set()


def _save_seen(seen):
    try:
        with open(SEEN_FILE, "w") as f:
            json.dump(sorted(seen), f)
    except Exception:
        pass


def _load_veto():
    """Lista de bookingIds o nombres (lower) que NO deben recibir review."""
    out = set()
    try:
        for line in open(VETO_FILE):
            line = line.strip()
            if line and not line.startswith("#"):
                out.add(line.lower())
    except FileNotFoundError:
        pass
    return out


def _g(obj, *keys, default=None):
    """Devuelve el primer key presente y no vacio en obj (dict)."""
    if not isinstance(obj, dict):
        return default
    for k in keys:
        if k in obj and obj[k] not in (None, "", []):
            return obj[k]
    return default


def _as_list(res):
    if isinstance(res, dict):
        return res.get("data", res.get("reviews", res.get("bookings", []))) or []
    return res or []


# --------------------------------------------------------------------------
# Acceso a datos (defensivo: el endpoint de reviews puede variar campos)
# --------------------------------------------------------------------------
def fetch_reviews(params=None):
    params = params or {}
    try:
        res = b._request("GET", "/channels/airbnb/reviews",
                         headers=b._auth(), params=params)
        return _as_list(res)
    except BaseException as ex:
        print("WARN no pude leer reviews: %r" % ex)
        return []


def fetch_bookings(d0, d1):
    try:
        res = b._request("GET", "/bookings", headers=b._auth(),
                         params={"departureFrom": d0.isoformat(),
                                 "departureTo": d1.isoformat()})
        return _as_list(res)
    except BaseException as ex:
        print("WARN no pude leer bookings: %r" % ex)
        return []


def _room_labels():
    """roomId -> etiqueta legible (numero de apto)."""
    out = {}
    try:
        for r in b.fetch_rooms():
            out[str(r.get("roomId"))] = b._label(r)
    except BaseException:
        pass
    return out


# --------------------------------------------------------------------------
# Interpretacion de un review (tolerante a distintos nombres de campo)
# --------------------------------------------------------------------------
def _review_id(r):
    return str(_g(r, "id", "reviewId", "airbnbReviewId",
                  default=json.dumps(r, sort_keys=True)[:64]))


def _review_dir(r):
    """'host' = el host reseno al huesped ; 'guest' = el huesped reseno al host."""
    t = str(_g(r, "type", "reviewType", "direction", "role", default="")).lower()
    if "host" in t and "guest" in t:
        # ej "hostToGuest" / "guestToHost"
        return "host" if t.index("host") < t.index("guest") else "guest"
    if "host" in t:
        return "host"
    if "guest" in t:
        return "guest"
    # fallback: si tiene texto de respuesta del host o flag
    if _g(r, "isHostReview", "fromHost"):
        return "host"
    return "guest"


def _review_rating(r):
    return _g(r, "rating", "overall", "overallRating", "stars", "score", default="")


def _review_text(r):
    return _g(r, "publicReview", "comment", "text", "review", "message",
              "content", default="")


def _review_when(r):
    return _g(r, "created", "createdAt", "date", "submittedAt", "time", default="")


def _booking_id(r):
    return str(_g(r, "bookingId", "bookId", "reservationId", "bookid", default=""))


def _guest_name_from_review(r):
    return _g(r, "guestName", "revieweeName", "reviewerName", "authorName",
              "name", default="")


# --------------------------------------------------------------------------
# Indices de reservas
# --------------------------------------------------------------------------
def _index_bookings(bookings):
    by_id = {}
    for bk in bookings:
        bid = str(_g(bk, "id", "bookId", "bookingId", default=""))
        if bid:
            by_id[bid] = bk
    return by_id


def _guest_first(bk):
    fn = _g(bk, "firstName", "guestFirstName", default="")
    if fn:
        return str(fn).strip().split()[0] if str(fn).strip() else ""
    full = _g(bk, "guestName", "title", default="")
    return str(full).strip().split()[0] if str(full).strip() else ""


def _guest_full(bk):
    fn = str(_g(bk, "firstName", "guestFirstName", default="")).strip()
    ln = str(_g(bk, "lastName", "guestLastName", default="")).strip()
    full = (fn + " " + ln).strip()
    return full or str(_g(bk, "guestName", "title", default="")).strip() or "(sin nombre)"


def _booking_room_label(bk, labels):
    rid = str(_g(bk, "roomId", default=""))
    return labels.get(rid, "apto " + rid if rid else "apto ?")


def _property_cities():
    """propertyId -> ciudad, para resolver [PROPERTYCITY] en la previsualizacion."""
    out = {}
    try:
        res = b._request("GET", "/properties", headers=b._auth(), params={})
        for p in _as_list(res):
            pid = str(_g(p, "id", "propertyId", "propId", default=""))
            city = _g(p, "city", "town", default="")
            if pid and city:
                out[pid] = str(city)
    except BaseException:
        pass
    return out


def _render_review(bk, cities):
    """Texto EXACTO que Beds24 va a postear para esta reserva (preview).
    Vacio si el apto no tiene plantilla mapeada."""
    rid = str(_g(bk, "roomId", default=""))
    tkey = ROOM_TEMPLATE.get(rid)
    if not tkey:
        return ""
    text = TEMPLATES.get(tkey, "")
    if not text:
        return ""
    first = _guest_first(bk) or "your guest"
    text = text.replace("[GUESTFIRSTNAME]", first)
    pid = str(_g(bk, "propertyId", "propId", default=""))
    city = cities.get(pid, "")
    if city:
        text = text.replace("[PROPERTYCITY]", city)
    return text


# --------------------------------------------------------------------------
# Veto / desactivar review automatica
# --------------------------------------------------------------------------
def _is_vetoed(bk, veto):
    if not veto:
        return False
    bid = str(_g(bk, "id", "bookId", "bookingId", default="")).lower()
    if bid and bid in veto:
        return True
    full = _guest_full(bk).lower()
    for v in veto:
        if v and (v == bid or (len(v) > 2 and v in full)):
            return True
    return False


def _disable_auto_review(bk):
    """Intenta desactivar la review automatica de una reserva por API.
    SOLO se ejecuta si AIRBNB_REVIEWS_AUTODISABLE=1. Es best-effort: si el
    formato no es el correcto, lo reporta y no rompe nada (no toca otros campos).
    """
    bid = str(_g(bk, "id", "bookId", "bookingId", default=""))
    if not bid:
        return "sin-id"
    payload = [{"id": int(bid) if bid.isdigit() else bid,
                "actions": {"makeReview": False, "allowReview": False}}]
    try:
        b._request("POST", "/bookings", headers=b._auth(), data=payload)
        return "desactivada"
    except BaseException as ex:
        return "no-pude(%r)" % ex


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    quiet = "--quiet" in args
    probe = "--probe" in args
    test = "--test" in args
    backfill = "--backfill" in args
    window = int(_opt(args, "--days", 21))
    autodisable = os.environ.get("AIRBNB_REVIEWS_AUTODISABLE") == "1"

    b.get_token()
    today = datetime.date.today()
    d0 = today - datetime.timedelta(days=window)
    d1 = today + datetime.timedelta(days=2)

    # -------- PROBE: volcar crudo para confirmar campos --------
    if probe:
        revs = fetch_reviews()
        bks = fetch_bookings(d0, d1)
        print("=== REVIEWS (%d) - primeros 3 crudos ===" % len(revs))
        for r in revs[:3]:
            print(json.dumps(r, indent=2, ensure_ascii=False)[:2000])
        print("\n=== BOOKINGS (%d) - primeros 2 crudos ===" % len(bks))
        for bk in bks[:2]:
            print(json.dumps(bk, indent=2, ensure_ascii=False)[:2000])
        return

    labels = _room_labels()
    cities = _property_cities()
    bookings = fetch_bookings(d0, d1)
    by_id = _index_bookings(bookings)
    reviews = fetch_reviews()
    seen = _load_seen()
    veto = _load_veto()

    # -------- BACKFILL: marcar todo lo viejo como visto, sin avisar --------
    if backfill:
        for r in reviews:
            seen.add(_review_id(r))
        _save_seen(seen)
        print("Backfill OK: %d reviews marcadas como vistas. No se enviaron avisos." % len(reviews))
        return

    # ---------------- 1) AVISOS de reviews nuevas ----------------
    nuevos_host = []   # host -> huesped
    nuevos_guest = []  # huesped -> host
    for r in reviews:
        rid = _review_id(r)
        if rid in seen:
            continue
        bk = by_id.get(_booking_id(r), {})
        nombre = _guest_first(bk) or _guest_name_from_review(r) or "tu huesped"
        apto = _booking_room_label(bk, labels) if bk else (
            "apto " + str(_g(r, "roomId", default="?")))
        rating = _review_rating(r)
        texto = _review_text(r)
        when = _review_when(r)
        item = {"rid": rid, "nombre": nombre, "apto": apto,
                "rating": rating, "texto": texto, "when": when}
        if _review_dir(r) == "host":
            nuevos_host.append(item)
        else:
            nuevos_guest.append(item)
        if not test:
            seen.add(rid)

    msgs = []
    for it in nuevos_host:
        linea = "✅ Review tuya publicada → %s (%s)" % (it["nombre"], it["apto"])
        if it["rating"]:
            linea += "  %s★" % it["rating"]
        if it["texto"]:
            linea += "\n   \"%s\"" % it["texto"]
        msgs.append(linea)
    for it in nuevos_guest:
        linea = "⭐ %s te reseñó (%s)" % (it["nombre"], it["apto"])
        if it["rating"]:
            linea += "  %s★" % it["rating"]
        if it["texto"]:
            linea += "\n   \"%s\"" % it["texto"]
        msgs.append(linea)

    # ---------------- 2) HEADS-UP de guardia ----------------
    # Checkouts dentro de la ventana de los ultimos AUTO_REVIEW_DELAY_DAYS dias:
    # son los que TODAVIA no han recibido la review automatica (puedes vetarlos).
    pend_ini = today - datetime.timedelta(days=AUTO_REVIEW_DELAY_DAYS)
    proximos = []
    vetados_detectados = []
    for bk in bookings:
        st = (str(_g(bk, "status", default="")) + " " +
              str(_g(bk, "subStatus", default=""))).lower()
        if "cancel" in st:
            continue
        try:
            dep = datetime.date.fromisoformat(str(_g(bk, "departure", default="")))
        except Exception:
            continue
        if not (pend_ini <= dep <= today):
            continue
        nombre = _guest_full(bk)
        apto = _booking_room_label(bk, labels)
        post_date = dep + datetime.timedelta(days=AUTO_REVIEW_DELAY_DAYS)
        if _is_vetoed(bk, veto):
            estado = "\U0001f6ab VETADO"
            if autodisable and not test:
                estado += " (" + _disable_auto_review(bk) + ")"
            vetados_detectados.append("%s %s (%s) checkout %s"
                                      % (estado, nombre, apto, dep.isoformat()))
        else:
            linea = ("• %s (%s) — checkout %s → 5★ el %s"
                     % (nombre, apto, dep.isoformat(), post_date.isoformat()))
            preview = _render_review(bk, cities)
            if preview:
                linea += "\n   «" + preview + "»"
            proximos.append(linea)

    # ---------------- Construir y enviar ----------------
    bloques = []
    if msgs:
        bloques.append("\U0001f5e3️ Reviews (novedades):\n\n" + "\n\n".join(msgs))
    if vetados_detectados:
        bloques.append("\U0001f6ab Huespedes vetados (no recibiran 5★):\n" +
                       "\n".join(vetados_detectados))
    if proximos:
        bloques.append("\U0001f4cb Reviews automaticas 5★ por salir (puedes vetar a alguien "
                       "agregando su nombre o bookingId a no_review.txt, o "
                       "quitando 'Allow Review' en Beds24):\n" + "\n".join(proximos))

    salida = "\n\n— — —\n\n".join(bloques) if bloques else ""
    if salida:
        print(salida)
        if not test:
            _tg_send(salida)
            _save_seen(seen)
    else:
        print("Sin novedades de reviews ni checkouts pendientes.")
        if not quiet and not test:
            _tg_send("\U0001f5e3️ Reviews: sin novedades hoy. Todo al dia.")


if __name__ == "__main__":
    main()
