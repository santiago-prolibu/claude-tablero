#!/usr/bin/env python3
"""Comando `cuentas`: estado de las cuentas de Claude en la terminal."""
import json
import sys
import urllib.request
from datetime import datetime, timezone

GIST_ID = "5b820c7ae6023afbfb862b25b5e4c177"  # mismo valor que reportar.py (Task 3)
GIST_FILE = "estado.json"
FRESCO_S = 900


def _ts(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _edad(ahora, iso):
    return (_ts(ahora) - _ts(iso)).total_seconds()


def _semaforo(score):
    return "verde" if score < 50 else ("amarillo" if score <= 80 else "rojo")


def agregar(estado, ahora):
    maquinas = estado.get("maquinas") or {}
    cupos = estado.get("cuentas") or {}
    aliases = sorted(set(cupos) | {m["cuenta"] for m in maquinas.values() if m.get("cuenta")})

    def maquina(clave, m):
        return {"clave": clave, **m, "fresco": _edad(ahora, m["reportado"]) <= FRESCO_S}

    lista = []
    for alias in aliases:
        c = cupos.get(alias)
        item = {"alias": alias, "cupo": None, "medido": None, "fresco": False,
                "score": None, "semaforo": None,
                "maquinas": [maquina(k, m) for k, m in sorted(maquinas.items())
                             if m.get("cuenta") == alias]}
        if c:
            score = max(c["cinco_horas"]["pct"], c["semanal"]["pct"])
            item.update(cupo=c, medido=c["medido"],
                        fresco=_edad(ahora, c["medido"]) <= FRESCO_S,
                        score=score, semaforo=_semaforo(score))
        lista.append(item)

    con_cupo = [c for c in lista if c["cupo"]]
    frescas = [c for c in con_cupo if c["fresco"]]
    pool = frescas or con_cupo
    recomendada = None
    if pool:
        elegida = min(pool, key=lambda c: (c["score"], c["cupo"]["cinco_horas"]["pct"]))
        recomendada = {"alias": elegida["alias"],
                       "dato_de_hace_s": 0 if elegida["fresco"] else _edad(ahora, elegida["medido"])}

    lista.sort(key=lambda c: (c["cupo"] is None, c["score"] if c["score"] is not None else 999, c["alias"]))
    sin_sesion = [maquina(k, m) for k, m in sorted(maquinas.items()) if not m.get("cuenta")]
    return {"recomendada": recomendada, "cuentas": lista, "sin_sesion": sin_sesion}


def humanizar(segundos):
    if segundos < 60:
        return "hace un momento"
    if segundos < 3600:
        return f"hace {int(segundos // 60)} min"
    if segundos < 86400:
        return f"hace {int(segundos // 3600)} h"
    return f"hace {int(segundos // 86400)} d"


def _barra(pct, ancho=10):
    llenos = round(pct / 100 * ancho)
    return "█" * llenos + "░" * (ancho - llenos)


LUZ = {"verde": "🟢", "amarillo": "🟡", "rojo": "🔴", None: "⚪"}


def render(agregado, ahora):
    filas = []
    for c in agregado["cuentas"]:
        if c["cupo"]:
            f5, fs = c["cupo"]["cinco_horas"], c["cupo"]["semanal"]
            cupo_txt = (f"5h {_barra(f5['pct'])} {f5['pct']:3d}%  "
                        f"sem {_barra(fs['pct'])} {fs['pct']:3d}%")
            if not c["fresco"]:
                cupo_txt += f"  (dato de {humanizar(_edad(ahora, c['medido']))})"
        else:
            cupo_txt = "cupo desconocido"
        filas.append(f"{LUZ[c['semaforo']]} {c['alias']:<10} {cupo_txt}")
        for m in c["maquinas"]:
            act = m.get("ultima_actividad")
            detalle = (f"{humanizar(_edad(ahora, act['hace']))} · {act['proyecto'] or '?'}"
                       if act else "sin actividad")
            frescura = "" if m["fresco"] else f"  [sin reporte {humanizar(_edad(ahora, m['reportado']))}]"
            filas.append(f"   └ {m['clave']}: {detalle}{frescura}")
    if agregado["sin_sesion"]:
        filas.append("Sin sesión:")
        for m in agregado["sin_sesion"]:
            act = m.get("ultima_actividad")
            detalle = (f"{humanizar(_edad(ahora, act['hace']))} · {act['proyecto'] or '?'}"
                       if act else "sin actividad")
            filas.append(f"   └ {m['clave']}: {detalle}")
    r = agregado["recomendada"]
    if r is None:
        filas.append("→ Sin dato de cupo")
    elif r["dato_de_hace_s"] > FRESCO_S:
        filas.append(f"→ Usa: {r['alias']} (con dato de {humanizar(r['dato_de_hace_s'])})")
    else:
        filas.append(f"→ Usa: {r['alias']}")
    return "\n".join(filas)


def _traer_estado():
    # Raw del CDN primero: sin límite de API (el anónimo de api.github.com es 60/h por IP
    # compartida). El ?t= esquiva el caché de 5 min. Fallback: la API clásica.
    ts = int(datetime.now(timezone.utc).timestamp())
    raw = urllib.request.Request(
        f"https://gist.githubusercontent.com/santiago-prolibu/{GIST_ID}/raw/{GIST_FILE}?t={ts}",
        headers={"User-Agent": "claude-tablero"})
    try:
        with urllib.request.urlopen(raw, timeout=20) as resp:
            return json.load(resp)
    except Exception:
        api = urllib.request.Request(
            f"https://api.github.com/gists/{GIST_ID}",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "claude-tablero"})
        with urllib.request.urlopen(api, timeout=20) as resp:
            return json.loads(json.load(resp)["files"][GIST_FILE]["content"])


def main():
    try:
        estado = _traer_estado()
    except Exception as e:
        print(f"No se pudo leer el estado ({e}). Reintenta en un momento.")
        raise SystemExit(1)
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(render(agregar(estado, ahora), ahora))


if __name__ == "__main__":
    main()
