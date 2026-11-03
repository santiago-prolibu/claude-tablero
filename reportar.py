#!/usr/bin/env python3
"""Reportero del tablero de cuentas de Claude. Solo stdlib."""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

GIST_ID = "5b820c7ae6023afbfb862b25b5e4c177"
GIST_FILE = "estado.json"
ANTHROPIC_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TABLERO_DIR = Path.home() / ".claude-tablero"
TOKEN_PATH = TABLERO_DIR / "token"
LOG_PATH = TABLERO_DIR / "reportar.log"
ISO = "%Y-%m-%dT%H:%M:%SZ"
# Toda entrada sin datos nuevos hace más de una semana se borra del gist. `fusionar` solo
# agregaba, así que el estado crecía para siempre: un compu renombrado dejaba un fantasma
# por cada nombre, y una cuenta que nadie volvió a usar seguía figurando con su cupo viejo.
PURGA_S = 7 * 86400
# Días de historial de tokens que cada compu publica. Cubre la ventana semanal entera
# más una semana de contexto; los .jsonl más viejos que esto ni se abren.
CONSUMO_DIAS = 14
CAMPOS_USO = (
    ("entrada", "input_tokens"), ("salida", "output_tokens"),
    ("cache_escr", "cache_creation_input_tokens"), ("cache_lect", "cache_read_input_tokens"),
)


def elegir_clave(local_hostname, hostname_s):
    lh = (local_hostname or "").strip()
    return lh if lh else hostname_s.strip()


def leer_cuenta(claude_json):
    cuenta = claude_json.get("oauthAccount") or {}
    if not cuenta:
        return None
    alias = (cuenta.get("displayName") or "").strip()
    if alias:
        return alias
    uuid = cuenta.get("accountUuid") or ""
    return f"cuenta-{uuid[:8]}" if uuid else None


def ultima_actividad(projects_dir):
    jsonls = list(Path(projects_dir).glob("*/*.jsonl"))
    if not jsonls:
        return None
    reciente = max(jsonls, key=lambda p: p.stat().st_mtime)
    proyecto = None
    with open(reciente, errors="replace") as fh:
        for i, linea in enumerate(fh):
            if i >= 25:
                break
            try:
                cwd = json.loads(linea).get("cwd")
            except (json.JSONDecodeError, AttributeError):
                continue
            if cwd:
                proyecto = os.path.basename(os.path.normpath(cwd))
                break
    hace = datetime.fromtimestamp(reciente.stat().st_mtime, timezone.utc).strftime(ISO)
    return {"hace": hace, "proyecto": proyecto}


def _momento_local(ts_iso, tz):
    try:
        return datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).astimezone(tz)
    except (TypeError, ValueError, AttributeError):
        return None


def consumo_tokens(projects_dir, ahora, dias=CONSUMO_DIAS, tz=None):
    """Tokens por día y modelo, leídos de los .jsonl de Claude Code (sesiones y subagentes).

    Cada mensaje del asistente trae `message.model` y `message.usage`. Claude Code escribe una
    línea por bloque de contenido y el usage de las primeras es provisional (output_tokens de
    3-6 mientras streamea), así que por cada `message.id` manda la última línea. Los días son
    locales del compu: "hoy" significa lo mismo que para quien mira el tablero.
    """
    desde = ahora - timedelta(days=dias)
    consumo = {}
    for f in Path(projects_dir).rglob("*.jsonl"):
        try:
            if f.stat().st_mtime < desde.timestamp():
                continue
            with open(f, errors="replace") as fh:
                mensajes = _mensajes_con_uso(fh)
        except OSError:
            continue
        for m in mensajes.values():
            cuando = _momento_local(m.get("timestamp"), tz)
            if cuando is None or cuando < desde:
                continue
            msg = m["message"]
            por_modelo = consumo.setdefault(cuando.strftime("%Y-%m-%d"), {})
            b = por_modelo.setdefault(msg["model"], {"msgs": 0, **{k: 0 for k, _ in CAMPOS_USO}})
            b["msgs"] += 1
            for campo, origen in CAMPOS_USO:
                try:
                    b[campo] += int(msg["usage"].get(origen) or 0)
                except (TypeError, ValueError):
                    pass
    return consumo


def _mensajes_con_uso(fh):
    """{message.id: última línea} de los mensajes del asistente con modelo y usage reales."""
    mensajes = {}
    for i, linea in enumerate(fh):
        # Prefiltro barato (casi todo el archivo es otra cosa) que no depende de cómo se
        # serialice el JSON; la comprobación real va sobre el objeto parseado.
        if "assistant" not in linea:
            continue
        try:
            m = json.loads(linea)
        except json.JSONDecodeError:
            continue
        if m.get("type") != "assistant":
            continue
        msg = m.get("message") or {}
        modelo = msg.get("model")
        if not isinstance(msg.get("usage"), dict) or not modelo or modelo.startswith("<"):
            continue  # <synthetic>: mensajes que Claude Code fabrica, no consumen
        mensajes[msg.get("id") or m.get("requestId") or f"linea-{i}"] = m
    return mensajes


def vigente(ahora, iso):
    """¿La entrada sigue dentro de la ventana de purga? Fecha ilegible: se conserva."""
    try:
        edad = (datetime.strptime(ahora, ISO) - datetime.strptime(iso, ISO)).total_seconds()
    except (TypeError, ValueError):
        return True
    return edad <= PURGA_S


def fusionar(estado, clave, cuenta, actividad, cupo, ahora, consumo=None):
    estado = dict(estado) if isinstance(estado, dict) else {}
    estado["version"] = 1
    maquinas = dict(estado.get("maquinas") or {})
    maquinas[clave] = {"cuenta": cuenta, "ultima_actividad": actividad, "reportado": ahora}
    if consumo is not None:
        maquinas[clave]["consumo"] = {"dias": consumo}
    cuentas = dict(estado.get("cuentas") or {})
    if cuenta and cupo:
        cuentas[cuenta] = {**cupo, "medido": ahora, "por": clave}
    # Lo recién escrito tiene fecha `ahora`, así que la purga nunca toca este reporte.
    estado["maquinas"] = {k: m for k, m in maquinas.items() if vigente(ahora, m.get("reportado"))}
    estado["cuentas"] = {k: c for k, c in cuentas.items() if vigente(ahora, c.get("medido"))}
    return estado


def leer_token_anthropic():
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return None
        return (json.loads(r.stdout.strip()).get("claudeAiOauth") or {}).get("accessToken")
    except Exception:
        return None


def consultar_uso(token):
    req = urllib.request.Request(ANTHROPIC_USAGE_URL, headers={
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": "claude-tablero",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def parsear_cupo(uso):
    try:
        fh, sd = uso["five_hour"], uso["seven_day"]

        # fixture real observado (tests/fixtures/uso_real.json): utilization ya viene en 0-100, no en fracción 0-1.
        def pct(ventana):
            return round(float(ventana["utilization"]))

        cupo = {
            # Hay cuentas a las que la API ya no les manda el límite de sesión
            # (tests/fixtures/uso_sin_sesion.json). `pct` sigue siendo un número porque el gist es
            # compartido y los `cuentas` y las pestañas ya instalados lo leen sin proteger.
            "cinco_horas": ({"pct": 0, "resetea": None, "no_reportado": True} if fh is None
                            else {"pct": pct(fh), "resetea": fh.get("resets_at")}),
            "semanal": {"pct": pct(sd), "resetea": sd.get("resets_at")},
        }
    except (KeyError, TypeError, ValueError):
        return None
    modelos = limites_por_modelo(uso)
    if modelos:
        cupo["modelos"] = modelos
    return cupo


def limites_por_modelo(uso):
    """Cupos semanales con alcance de modelo (`limits[]`, kind weekly_scoped): hoy solo Fable.

    Es un límite aparte del semanal general: una cuenta puede tener Fable agotado y seguir
    sirviendo para Opus. Un límite malformado se ignora sin tumbar el cupo general.
    """
    modelos = {}
    for lim in (uso.get("limits") or []) if isinstance(uso, dict) else []:
        try:
            if lim.get("kind") != "weekly_scoped":
                continue
            nombre = (lim["scope"]["model"] or {}).get("display_name")
            if nombre:
                modelos[nombre] = {"pct": round(float(lim["percent"])), "resetea": lim.get("resets_at")}
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return modelos


def armar_reporte(claude_json, projects_dir, local_hostname, hostname_s, uso, ahora):
    clave = elegir_clave(local_hostname, hostname_s)
    cuenta = leer_cuenta(claude_json)
    actividad = ultima_actividad(projects_dir)
    cupo = parsear_cupo(uso) if (uso and cuenta) else None
    consumo = consumo_tokens(projects_dir, datetime.strptime(ahora, ISO).replace(tzinfo=timezone.utc))
    return clave, cuenta, actividad, cupo, consumo


def _gh_headers(pat=None):
    h = {"Accept": "application/vnd.github+json", "User-Agent": "claude-tablero"}
    if pat:
        h["Authorization"] = f"Bearer {pat}"
    return h


def gist_get(pat=None):
    req = urllib.request.Request(
        f"https://api.github.com/gists/{GIST_ID}", headers=_gh_headers(pat))
    with urllib.request.urlopen(req, timeout=20) as resp:
        cuerpo = json.load(resp)
    try:
        return json.loads(cuerpo["files"][GIST_FILE]["content"])
    except (KeyError, json.JSONDecodeError):
        return {}


def gist_patch(pat, estado):
    datos = json.dumps({"files": {GIST_FILE: {
        "content": json.dumps(estado, indent=1, ensure_ascii=False)}}}).encode()
    req = urllib.request.Request(
        f"https://api.github.com/gists/{GIST_ID}", data=datos,
        headers=_gh_headers(pat), method="PATCH")
    with urllib.request.urlopen(req, timeout=20) as resp:
        resp.read()


def _log(msg):
    try:
        TABLERO_DIR.mkdir(exist_ok=True)
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 200_000:
            LOG_PATH.write_text("\n".join(LOG_PATH.read_text().splitlines()[-50:]) + "\n")
        with open(LOG_PATH, "a") as fh:
            fh.write(f"{datetime.now(timezone.utc).strftime(ISO)} {msg}\n")
    except OSError:
        pass


def _scutil_localhostname():
    try:
        r = subprocess.run(["scutil", "--get", "LocalHostName"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def main(dry_run=False):
    try:
        claude_json = json.loads((Path.home() / ".claude.json").read_text())
    except (OSError, json.JSONDecodeError):
        claude_json = {}
    hostname_s = subprocess.run(["hostname", "-s"], capture_output=True,
                                text=True).stdout.strip() or "desconocido"
    tok = leer_token_anthropic()
    uso = None
    if tok:
        try:
            uso = consultar_uso(tok)
        except Exception as e:
            _log(f"uso fallo: {e}")
    ahora = datetime.now(timezone.utc).strftime(ISO)
    clave, cuenta, actividad, cupo, consumo = armar_reporte(
        claude_json, Path.home() / ".claude" / "projects",
        _scutil_localhostname(), hostname_s, uso, ahora)
    if uso is not None and cuenta and not cupo:
        # Sin esto el reporte sale `ok … cupo=no` y la cuota se congela sin dejar rastro.
        presentes = sorted(k for k, v in uso.items() if v is not None) if isinstance(uso, dict) else []
        _log(f"uso sin cupo legible; claves con dato: {presentes}")
    pat = TOKEN_PATH.read_text().strip() if TOKEN_PATH.exists() else None
    if not pat:
        _log("sin PAT; abortando")
        sys.exit(1)
    for intento in (1, 2):
        try:
            estado = fusionar(gist_get(pat), clave, cuenta, actividad, cupo, ahora, consumo)
            if dry_run:
                print(json.dumps(estado, indent=2, ensure_ascii=False))
                return
            gist_patch(pat, estado)
            _log(f"ok {clave} cuenta={cuenta} cupo={'si' if cupo else 'no'}")
            return
        except Exception as e:
            _log(f"intento {intento} fallo: {e}")
    sys.exit(1)


if __name__ == "__main__":
    if "--probe" in sys.argv:
        tok = leer_token_anthropic()
        if not tok:
            print("sin token (Keychain denegado o vacío)", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(consultar_uso(tok), indent=2))
    else:
        main(dry_run="--dry-run" in sys.argv)
