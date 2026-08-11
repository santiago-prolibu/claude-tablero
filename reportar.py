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


if __name__ == "__main__":
    if "--probe" in sys.argv:
        tok = leer_token_anthropic()
        if not tok:
            print("sin token (Keychain denegado o vacío)", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(consultar_uso(tok), indent=2))
        sys.exit(0)
