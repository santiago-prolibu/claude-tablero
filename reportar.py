#!/usr/bin/env python3
"""Reportero del tablero de cuentas de Claude. Solo stdlib."""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

GIST_ID = "5b820c7ae6023afbfb862b25b5e4c177"
GIST_FILE = "estado.json"
ANTHROPIC_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TABLERO_DIR = Path.home() / ".claude-tablero"
TOKEN_PATH = TABLERO_DIR / "token"
LOG_PATH = TABLERO_DIR / "reportar.log"
ISO = "%Y-%m-%dT%H:%M:%SZ"


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


def fusionar(estado, clave, cuenta, actividad, cupo, ahora):
    estado = dict(estado) if isinstance(estado, dict) else {}
    estado["version"] = 1
    maquinas = dict(estado.get("maquinas") or {})
    maquinas[clave] = {"cuenta": cuenta, "ultima_actividad": actividad, "reportado": ahora}
    estado["maquinas"] = maquinas
    cuentas = dict(estado.get("cuentas") or {})
    if cuenta and cupo:
        cuentas[cuenta] = {**cupo, "medido": ahora, "por": clave}
    estado["cuentas"] = cuentas
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

        return {
            "cinco_horas": {"pct": pct(fh), "resetea": fh.get("resets_at")},
            "semanal": {"pct": pct(sd), "resetea": sd.get("resets_at")},
        }
    except (KeyError, TypeError, ValueError):
        return None


def armar_reporte(claude_json, projects_dir, local_hostname, hostname_s, uso, ahora):
    clave = elegir_clave(local_hostname, hostname_s)
    cuenta = leer_cuenta(claude_json)
    actividad = ultima_actividad(projects_dir)
    cupo = parsear_cupo(uso) if (uso and cuenta) else None
    return clave, cuenta, actividad, cupo


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
    clave, cuenta, actividad, cupo = armar_reporte(
        claude_json, Path.home() / ".claude" / "projects",
        _scutil_localhostname(), hostname_s, uso, ahora)
    pat = TOKEN_PATH.read_text().strip() if TOKEN_PATH.exists() else None
    if not pat:
        _log("sin PAT; abortando")
        sys.exit(1)
    for intento in (1, 2):
        try:
            estado = fusionar(gist_get(pat), clave, cuenta, actividad, cupo, ahora)
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
