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

GIST_ID = "PENDIENTE_BOOTSTRAP"
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
