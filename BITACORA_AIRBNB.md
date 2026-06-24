# Bitácora Airbnb / Beds24 / Dispatch

_Última actualización: 23 jun 2026_

Resumen de todo el sistema de automatización de los Airbnb (Medellín + Texas),
para que quede en el cajón de Airbnb y nadie tenga que reconstruirlo de memoria.

---

## 1. Panorama general

- **~16 listings de Airbnb** gestionados con **Beds24** (channel manager).
- Beds24 sincroniza precios, disponibilidad y reservas con Airbnb.
- Todo se opera por **Telegram** a través de **Dispatch** (bot con Claude headless
  en el server Hetzner `167.233.48.33`, usuario `dispatch`).
- Scripts de Airbnb viven en: `/opt/dispatch/projects/airbnb/`.

---

## 2. Reviews automáticas (estilo "host de verdad") — LISTO ✅

Beds24 postea sola una review de **5★ personalizada ~4 días después de cada
checkout**, usando el campo **"Auto Review Text"** de cada listing.

- Variables que rellena Beds24: `[GUESTFIRSTNAME]` (nombre del huésped) y
  `[PROPERTYCITY]` (ciudad del apto).
- Se cargaron **4 plantillas distintas (T1–T4)** repartidas entre los 16 listings
  para que no se vean clonadas. (Texto completo de las plantillas: ver el robot
  `airbnb_reviews.py`, sección `TEMPLATES`.)

### Mapa apto → plantilla (roomId)

| Apto | roomId | Plantilla | Apto | roomId | Plantilla |
|------|--------|-----------|------|--------|-----------|
| 1105 | 689885 | T1 | 419 | 689866 | T4 |
| 1224 | 689874 | T2 | 602 | 689879 | T1 |
| 1922 | 689884 | T3 | 802 | 689878 | T2 |
| 207 | 690330 | T4 | 802 (2) | 689887 | T3 |
| 2208 | 689869 | T1 | 802 (3) | 690344 | T4 |
| 2208 (2) | 690345 | T2 | 3301 | 689873 | T1 |
| 2715 | 689872 | T4 | 402 | 689881 | T2 |
| 4065 | 689883 | T3 | 2523 | 690346 | T3 (desconectado) |

> Para **vetar** a un huésped (que NO reciba la 5★): abre su reserva en Beds24 →
> Mail & Actions → desmarca **"Allow Review"**. O usa el archivo de veto del robot
> (ver abajo).

---

## 3. Robot de avisos + guardia: `airbnb_reviews.py`

Capa de **avisos por Telegram + guardia** encima de los auto-reviews.

### Qué hace
- **Heads-up diario:** lista los checkouts recientes que están por recibir su 5★,
  **con el texto literal** que se va a postear (nombre + ciudad reales). Así puedes
  vetar a alguien a tiempo.
- **Veto:** si pones un bookingId o nombre en
  `/opt/dispatch/projects/airbnb/no_review.txt`, el robot lo detecta y te avisa.
  Por defecto **solo avisa** (seguro). Si activas `AIRBNB_REVIEWS_AUTODISABLE=1`,
  además intenta desactivar la review por API.
- **Lectura de reviews (huésped→host): NO funciona** — Beds24 no expone el texto
  por API (ver hallazgos). Queda en silencio (solo un WARN en el log).

### Modos
```
python3 airbnb_reviews.py            # ciclo normal (avisa novedades + heads-up)
python3 airbnb_reviews.py --quiet    # solo avisa si hay algo (lo que corre el cron)
python3 airbnb_reviews.py --test     # muestra sin enviar ni guardar
python3 airbnb_reviews.py --probe    # vuelca JSON crudo de la API (debug)
python3 airbnb_reviews.py --backfill # marca lo viejo como visto (1 sola vez al instalar)
python3 airbnb_reviews.py --days 30  # ventana de días (def 21)
```

### Archivos
- Estado (memoria anti-spam): `/opt/dispatch/projects/airbnb/.reviews_seen.json`
- Lista de veto: `/opt/dispatch/projects/airbnb/no_review.txt`
- Log: `/opt/dispatch/projects/airbnb/reviews.log`

### Despliegue / actualización (vía GitHub)
Repo: **https://github.com/wheducation/airbnb-dispatch** (público, sin secretos).
```
curl -fsSL https://raw.githubusercontent.com/wheducation/airbnb-dispatch/main/airbnb_reviews.py -o /opt/dispatch/projects/airbnb/airbnb_reviews.py
python3 -m py_compile /opt/dispatch/projects/airbnb/airbnb_reviews.py && echo COMPILA_OK
```

### Cron (usuario `dispatch`, ~7:30am hora TX)
```
30 12 * * * /usr/bin/flock -n /tmp/airbnb_reviews.lock /usr/bin/python3 /opt/dispatch/projects/airbnb/airbnb_reviews.py --quiet >> /opt/dispatch/projects/airbnb/reviews.log 2>&1
```

---

## 4. Hallazgo clave: Beds24 NO entrega el texto de las reviews

- `GET /channels/airbnb/reviews` → **HTTP 400 "Invalid data"**.
- `GET /channels/airbnb/review?bookingId=X` → **null en todas las reservas**.
- El panel web (Channel Manager → Airbnb → **Ratings**) solo muestra **ratings
  agregados** (promedio, categorías), NO el comentario escrito de cada huésped.
- **Conclusión:** Beds24 no guarda el texto de las reviews de Airbnb. La dirección
  huésped→host hay que leerla de **Airbnb directo** (fase 2, vía navegador).

### Dato de calidad (de la página Ratings)
- Promedio general: **3.92** (Beds24 lo marca "más bajo que otros hosts").
- 21 reservas con incidencias. Categorías flojas: **Comunicación, Check-in,
  Precisión**. Lo más repetido: "respuesta lenta, instrucciones poco claras".
- Aptos más golpeados: 690344 (Skyline 3BR) y varios en ~4.5–4.6.

---

## 5. Facturación Beds24 — IMPORTANTE 💳

- La **prueba gratis se venció** (23 jun). Se **pagó** (saldo pasó de 1 → 76 EUR).
  Sin pago, Beds24 deja de sincronizar y se cae TODO (auto-reviews, disponibilidad).
- **Costo: ~70.55 EUR/mes** = cuenta 12.90 + propiedades 49.40 (17 props / 19 rooms)
  + channel management 8.25 (15 links).
- **76 EUR cubre ~1 mes.** Recomendado: activar **auto-recargo** (Setup Automatic
  Payments) para no recaer.
- **Revisar:** Beds24 cobra por **17 propiedades / 19 rooms** pero solo hay 16
  listings de Airbnb. Probablemente hay rooms/props duplicados o de prueba (ej.
  rooms sueltos del 2523) que se están pagando de más. Limpiarlos baja la mensualidad.
- "Links" (15) = conexiones activas apto↔Airbnb (16 listings − 2523 desconectado).

---

## 6. Caso 2523 (sin resolver, workaround activo)

- El listing 2523 manda **Inventory=0** a Airbnb por una corrupción a **nivel
  listing** en Beds24 (sigue al listing incluso copiando el room). No es bug de
  configuración.
- **Workaround:** desconectado de Beds24; se maneja **directo en Airbnb**.
- Rooms sueltos a limpiar: **695315 y 695318** (borrar); **690346** se conserva.
- Reintentar reconexión en unos días / abrir ticket a soporte Beds24.

---

## 7. Otros agentes y herramientas (server)

- **`airbnb_watchdog.py`** — vigila a diario que no haya noches ocupadas sin
  reserva (riesgo de doble booking). Cron ~7am.
- **`airbnb_gaps.py`** — optimiza noches huérfanas (baja minStay de huecos atrapados).
  Tiene red de seguridad: trata `numAvail<=0` como ocupado.
- **`/usr/local/bin/dispatch-redeploy`** — reinicio propio y diferido de Dispatch.
- **`/usr/local/bin/agentes-deploy`** — despliega scripts de circuito-pdfs desde el Taller.
- **Taller / Control Room** — desde `/proyecto taller` en Telegram se arreglan,
  mejoran y reinician los agentes con permisos de dispatch.

---

## 8. Bug de Dispatch detectado (23 jun) — pendiente de arreglo de fondo

- **Síntoma:** `[Errno 7] Argument list too long: '/usr/bin/claude'` en CADA mensaje
  (cientos de errores en "Dispatch Logs").
- **Causa:** Dispatch le pasa a `claude` el contexto/historial **como argumento de
  línea de comando**; al crecer el historial cruza el límite del SO (~128 KB/arg).
- **Parche rápido:** resetear la sesión/contexto de Dispatch (`/reset`, `/new`…).
- **Arreglo de fondo:** que Dispatch pase el prompt por **stdin** (`claude -p` lee de
  stdin) o por archivo temporal, en vez de argv. Cambio de 1–2 líneas en el launcher.

---

## 9. Pendientes

- [ ] **Fase 2:** leer reviews escritas de huéspedes desde Airbnb directo (Beds24 no las da).
- [ ] Arreglar de fondo el bug de Dispatch (prompt por stdin/archivo).
- [ ] Activar auto-recargo de Beds24 para no recaer en el vencimiento.
- [ ] Revisar/limpiar las 17 propiedades y 19 rooms (duplicados → bajar mensualidad).
- [ ] Limpiar rooms sueltos del 2523 (695315, 695318); reintentar 2523 + ticket Beds24.
