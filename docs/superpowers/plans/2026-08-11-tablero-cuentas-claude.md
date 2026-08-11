# Tablero de cuentas de Claude — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tablero (web + terminal) que muestra el cupo de las 3 cuentas de Claude, qué compu está en qué cuenta y su última actividad, alimentado por un reportero launchd en cada Mac que publica a un gist.

**Architecture:** Cada Mac corre `reportar.py` cada 5 min (launchd): lee cuenta de `~/.claude.json`, cupo del endpoint OAuth de uso (token del Keychain), última actividad de `~/.claude/projects/`, y actualiza su entrada en un gist secreto (`estado.json`, bloques `maquinas` + `cuentas`). Lo leen una página estática en GitHub Pages y el comando `cuentas`.

**Tech Stack:** Python 3 stdlib (reportero y comando), JS vanilla + HTML (tablero), bash (instalador), launchd, API de gists de GitHub. Sin dependencias, sin build.

**Spec:** `docs/superpowers/specs/2026-08-11-tablero-cuentas-claude-design.md` (leerlo antes de cualquier task).

## Global Constraints

- Solo stdlib de python3 y JS vanilla; nada de pip/npm; sin paso de build.
- Al gist **nunca** van emails, tokens ni rutas completas — solo alias, LocalHostName, porcentajes, timestamps y basename del proyecto.
- Nombres exactos: gist file `estado.json`; label launchd `com.prolibu.claude-tablero`; dir instalado `~/.claude-tablero/`; comando `cuentas`; constante `GIST_ID` (placeholder `PENDIENTE_BOOTSTRAP` hasta el Task 3).
- Reglas compartidas (idénticas en Python y JS): frescura = 900 s; semáforo sobre `score = max(pct_5h, pct_semanal)`: `<50` verde, `<=80` amarillo, `>80` rojo; recomendada = menor `(score, pct_5h)` entre las frescas con cupo, fallback a las no-frescas con cupo (marcada con la edad del dato), `null` si ninguna tiene cupo.
- Timestamps en ISO-8601 UTC con sufijo `Z` (`%Y-%m-%dT%H:%M:%SZ`); las funciones puras reciben `ahora` como parámetro (nunca llaman al reloj adentro).
- Tests: `python3 -m unittest discover -s tests -v` y `node --test` (sin pasar el directorio como argumento: en Node 22 `node --test tests/` puede fallar con MODULE_NOT_FOUND).
- Textos de UI en español.
- Repo público `santiago-prolibu/claude-tablero`; Pages desde `main` / root.
- Este repo es nuevo y exclusivo del proyecto: se trabaja directo en `main`, sin worktree.

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `reportar.py` | Reportero completo: colectores + publicación al gist. Autocontenido (se copia solo a `~/.claude-tablero/`). |
| `cuentas.py` | Comando de terminal: fetch del gist + agregación + render. Autocontenido (se instala como `cuentas`). |
| `agregacion.js` | Reglas de agregación en JS (espejo de las de `cuentas.py`), usado por `index.html` y testeable con node. |
| `index.html` | Tablero web mobile-first (usa `agregacion.js`). |
| `com.prolibu.claude-tablero.plist` | Plantilla launchd (placeholder `__HOME__`). |
| `instalar.sh` | Instalador idempotente por compu. |
| `tests/test_reportar.py`, `tests/test_cuentas.py`, `tests/agregacion.test.js`, `tests/fixtures/uso_real.json` | Tests + fixture real del endpoint de uso. |
| `README.md` | Qué es, URL del tablero, cómo instalar un compu nuevo. |

---

### Task 1: Colectores puros del reportero

**Files:**
- Create: `reportar.py`
- Test: `tests/test_reportar.py`

**Interfaces:**
- Produces (usadas por Tasks 2 y 4, en `reportar.py`):
  - `elegir_clave(local_hostname: str|None, hostname_s: str) -> str`
  - `leer_cuenta(claude_json: dict) -> str|None` — alias público o `None` si deslogueado
  - `ultima_actividad(projects_dir: str|Path) -> dict|None` — `{"hace": iso, "proyecto": str|None}`
  - `fusionar(estado: dict, clave: str, cuenta: str|None, actividad: dict|None, cupo: dict|None, ahora: str) -> dict`
  - Constantes: `GIST_ID = "PENDIENTE_BOOTSTRAP"`, `GIST_FILE = "estado.json"`, `TABLERO_DIR = Path.home()/".claude-tablero"`

- [ ] **Paso 1: Escribir los tests que fallan**

```python
# tests/test_reportar.py
import json, os, sys, tempfile, time, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reportar


class TestElegirClave(unittest.TestCase):
    def test_prefiere_localhostname(self):
        self.assertEqual(reportar.elegir_clave("Mini-Oficina", "otro"), "Mini-Oficina")

    def test_fallback_hostname_s(self):
        self.assertEqual(reportar.elegir_clave(None, "mac-de-s"), "mac-de-s")
        self.assertEqual(reportar.elegir_clave("  ", "mac-de-s"), "mac-de-s")


class TestLeerCuenta(unittest.TestCase):
    def test_alias_de_displayname(self):
        cj = {"oauthAccount": {"displayName": "Gamma", "emailAddress": "x@y.com"}}
        self.assertEqual(reportar.leer_cuenta(cj), "Gamma")

    def test_deslogueado_devuelve_none(self):
        self.assertIsNone(reportar.leer_cuenta({}))
        self.assertIsNone(reportar.leer_cuenta({"oauthAccount": None}))

    def test_sin_displayname_usa_uuid_nunca_email(self):
        cj = {"oauthAccount": {"emailAddress": "x@y.com",
                               "accountUuid": "b62fc0b9-b7c7-423e"}}
        alias = reportar.leer_cuenta(cj)
        self.assertEqual(alias, "cuenta-b62fc0b9")
        self.assertNotIn("@", alias)


class TestUltimaActividad(unittest.TestCase):
    def _mk(self, base, carpeta, nombre, lineas, mtime):
        d = Path(base) / carpeta
        d.mkdir(parents=True, exist_ok=True)
        f = d / nombre
        f.write_text("\n".join(lineas))
        os.utime(f, (mtime, mtime))
        return f

    def test_toma_el_jsonl_mas_reciente_y_lee_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = time.time()
            self._mk(tmp, "-Users-x-viejo", "a.jsonl",
                     ['{"cwd": "/Users/x/viejo"}'], t - 9000)
            self._mk(tmp, "-Users-x-Documents-Prolibu-prolibu-front-v2", "b.jsonl",
                     ['{"type": "summary"}',
                      '{"cwd": "/Users/x/Documents/Prolibu/prolibu-front-v2", "type": "user"}'],
                     t - 60)
            act = reportar.ultima_actividad(tmp)
            self.assertEqual(act["proyecto"], "prolibu-front-v2")
            self.assertTrue(act["hace"].endswith("Z"))

    def test_sin_cwd_legible_proyecto_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "-Users-x-p", "a.jsonl", ["esto no es json"], time.time())
            act = reportar.ultima_actividad(tmp)
            self.assertIsNone(act["proyecto"])

    def test_dir_vacio_devuelve_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(reportar.ultima_actividad(tmp))


class TestFusionar(unittest.TestCase):
    AHORA = "2026-08-11T18:00:00Z"

    def test_crea_entrada_y_cupo_por_cuenta(self):
        cupo = {"cinco_horas": {"pct": 62, "resetea": "2026-08-11T20:00:00Z"},
                "semanal": {"pct": 31, "resetea": "2026-08-14T13:00:00Z"}}
        estado = reportar.fusionar({}, "Mini", "Gamma",
                                   {"hace": self.AHORA, "proyecto": "x"}, cupo, self.AHORA)
        self.assertEqual(estado["version"], 1)
        self.assertEqual(estado["maquinas"]["Mini"]["cuenta"], "Gamma")
        self.assertEqual(estado["cuentas"]["Gamma"]["cinco_horas"]["pct"], 62)
        self.assertEqual(estado["cuentas"]["Gamma"]["medido"], self.AHORA)
        self.assertEqual(estado["cuentas"]["Gamma"]["por"], "Mini")

    def test_no_pisa_otras_maquinas_ni_otras_cuentas(self):
        previo = {"version": 1,
                  "maquinas": {"Otro": {"cuenta": "Alpha", "ultima_actividad": None,
                                        "reportado": "2026-08-11T17:00:00Z"}},
                  "cuentas": {"Alpha": {"cinco_horas": {"pct": 10, "resetea": None},
                                        "semanal": {"pct": 5, "resetea": None},
                                        "medido": "2026-08-11T17:00:00Z", "por": "Otro"}}}
        estado = reportar.fusionar(previo, "Mini", "Gamma", None, None, self.AHORA)
        self.assertIn("Otro", estado["maquinas"])
        self.assertIn("Alpha", estado["cuentas"])
        self.assertIsNone(estado["maquinas"]["Mini"]["ultima_actividad"])

    def test_sin_cupo_no_actualiza_bloque_cuentas(self):
        estado = reportar.fusionar({}, "Mini", "Gamma", None, None, self.AHORA)
        self.assertNotIn("Gamma", estado.get("cuentas", {}))

    def test_cuenta_null_reporta_maquina_sin_tocar_cuentas(self):
        estado = reportar.fusionar({}, "Mini", None, None, None, self.AHORA)
        self.assertIsNone(estado["maquinas"]["Mini"]["cuenta"])
        self.assertEqual(estado.get("cuentas", {}), {})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Paso 2: Verificar que fallan**

Run: `cd ~/Documents/Prolibu/claude-tablero && python3 -m unittest discover -s tests -v`
Expected: ERROR con `ModuleNotFoundError: No module named 'reportar'`

- [ ] **Paso 3: Implementación mínima**

```python
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
```

- [ ] **Paso 4: Verificar que pasan**

Run: `python3 -m unittest discover -s tests -v`
Expected: `OK` (12 tests)

- [ ] **Paso 5: Commit**

```bash
git add reportar.py tests/test_reportar.py
git commit -m "feat: colectores puros del reportero (clave, cuenta, actividad, fusion)"
```

---

### Task 2: Probe del endpoint de uso y parser del cupo

**Files:**
- Modify: `reportar.py` (agregar `leer_token_anthropic`, `consultar_uso`, `parsear_cupo` y modo `--probe`)
- Create: `tests/fixtures/uso_real.json`
- Test: `tests/test_reportar.py` (agregar `TestParsearCupo`)

**Interfaces:**
- Consumes: constantes de Task 1.
- Produces (usadas por Task 4):
  - `leer_token_anthropic() -> str|None` — token OAuth del Keychain
  - `consultar_uso(token: str) -> dict` — respuesta cruda del endpoint (lanza excepción si falla)
  - `parsear_cupo(uso: dict) -> dict|None` — `{"cinco_horas": {"pct": int, "resetea": iso|None}, "semanal": {...}}`

**Nota de permisos:** leer el Keychain desde la sesión puede ser denegado por el clasificador. Si `security` falla por permisos, pedirle a Santiago que corra él mismo: `! python3 reportar.py --probe > tests/fixtures/uso_real.json` y continuar con ese fixture.

- [ ] **Paso 1: Implementar lectura de Keychain, fetch y modo probe**

Agregar a `reportar.py` (después de `fusionar`):

```python
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


if __name__ == "__main__":
    if "--probe" in sys.argv:
        tok = leer_token_anthropic()
        if not tok:
            print("sin token (Keychain denegado o vacío)", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(consultar_uso(tok), indent=2))
        sys.exit(0)
```

- [ ] **Paso 2: Capturar el fixture real en este compu**

Run: `python3 reportar.py --probe > tests/fixtures/uso_real.json && python3 -m json.tool tests/fixtures/uso_real.json | head -40`
Expected: JSON con los datos de uso de la cuenta Gamma. La hipótesis de forma (confirmar contra lo impreso): objetos `five_hour` y `seven_day` con `utilization` y `resets_at`.
**Si el Keychain es denegado:** pedir a Santiago que corra `! python3 reportar.py --probe > tests/fixtures/uso_real.json`.
**Antes de commitear el fixture:** revisarlo y borrar cualquier id de cuenta/org si aparece (dejar solo utilización y resets).

- [ ] **Paso 3: Escribir el test del parser contra el fixture (falla)**

Ajustar los campos del test a la forma REAL observada en el fixture; la intención de cada caso se mantiene:

```python
class TestParsearCupo(unittest.TestCase):
    def _fixture(self):
        p = Path(__file__).parent / "fixtures" / "uso_real.json"
        return json.loads(p.read_text())

    def test_fixture_real(self):
        cupo = reportar.parsear_cupo(self._fixture())
        for ventana in ("cinco_horas", "semanal"):
            self.assertIn(ventana, cupo)
            self.assertIsInstance(cupo[ventana]["pct"], int)
            self.assertTrue(0 <= cupo[ventana]["pct"] <= 100)

    def test_respuesta_rara_devuelve_none(self):
        self.assertIsNone(reportar.parsear_cupo({}))
        self.assertIsNone(reportar.parsear_cupo({"error": "x"}))
```

Run: `python3 -m unittest tests.test_reportar.TestParsearCupo -v`
Expected: ERROR `AttributeError: ... no attribute 'parsear_cupo'`

- [ ] **Paso 4: Implementar `parsear_cupo` según la forma real**

Plantilla (ajustar nombres de campos al fixture; si `utilization` viene 0–1, multiplicar por 100):

```python
def parsear_cupo(uso):
    try:
        fh, sd = uso["five_hour"], uso["seven_day"]

        def pct(ventana):
            v = float(ventana["utilization"])
            return round(v * 100) if v <= 1.0 else round(v)

        return {
            "cinco_horas": {"pct": pct(fh), "resetea": fh.get("resets_at")},
            "semanal": {"pct": pct(sd), "resetea": sd.get("resets_at")},
        }
    except (KeyError, TypeError, ValueError):
        return None
```

Ojo con la heurística `v <= 1.0`: decidirla mirando el fixture real (si el valor real es fracción 0–1, quitar el condicional y multiplicar siempre; si es 0–100, no multiplicar nunca). Dejar la decisión escrita en un comentario de una línea.

- [ ] **Paso 5: Verificar que pasan todos**

Run: `python3 -m unittest discover -s tests -v`
Expected: `OK` (14 tests)

- [ ] **Paso 6: Commit**

```bash
git add reportar.py tests/
git commit -m "feat: medicion de cupo via endpoint OAuth con fixture real"
```

---

### Task 3: Bootstrap — PAT, gist, repo GitHub y Pages

Pasos manuales de Santiago (el ejecutor los pide y espera confirmación) mezclados con comandos.

**Files:**
- Modify: `reportar.py` (GIST_ID real)

**Interfaces:**
- Produces: `GIST_ID` real commiteado (Tasks 4–7 lo usan); gist existente con `estado.json` vacío; PAT guardado en `~/.claude-tablero/token`; repo `git@github.com:santiago-prolibu/claude-tablero.git` con Pages activo.

- [ ] **Paso 1 (Santiago): crear el PAT**

Pedirle: en <https://github.com/settings/tokens> → "Generate new token (classic)" → nombre `claude-tablero`, expiración la que prefiera, **solo** el scope `gist` → copiar el token. (Classic y no fine-grained: los fine-grained no cubren gists de forma confiable.)

- [ ] **Paso 2: guardar el PAT en este compu**

Pedirle a Santiago que lo pegue él mismo para que no quede en el transcript:

```bash
! mkdir -p ~/.claude-tablero && read -r -s -p "PAT: " T && printf '%s' "$T" > ~/.claude-tablero/token && chmod 600 ~/.claude-tablero/token && echo listo
```

- [ ] **Paso 3: crear el gist**

```bash
curl -s -X POST https://api.github.com/gists \
  -H "Authorization: Bearer $(cat ~/.claude-tablero/token)" \
  -H "Accept: application/vnd.github+json" \
  -d '{"description":"claude-tablero: estado de cuentas","public":false,"files":{"estado.json":{"content":"{\"version\":1,\"maquinas\":{},\"cuentas\":{}}"}}}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])"
```

Expected: imprime el ID del gist (hex de 32 chars). Verificar con `curl -s https://api.github.com/gists/<ID> | head -5` (debe responder 200 sin auth).

- [ ] **Paso 4: fijar GIST_ID y commitear**

En `reportar.py`, reemplazar `GIST_ID = "PENDIENTE_BOOTSTRAP"` por el ID real.

```bash
git add reportar.py && git commit -m "chore: GIST_ID real del bootstrap"
```

- [ ] **Paso 5 (Santiago): crear el repo en GitHub y push**

Pedirle: crear repo **público** vacío `claude-tablero` en <https://github.com/new> (sin README ni .gitignore). Luego:

```bash
git remote add origin git@github.com:santiago-prolibu/claude-tablero.git
git push -u origin main
```

- [ ] **Paso 6 (Santiago): activar Pages**

Pedirle: en el repo → Settings → Pages → Source "Deploy from a branch" → branch `main`, carpeta `/ (root)` → Save. (La página servirá 404 hasta el Task 7; está bien.)

---

### Task 4: Publicación del reportero (gist + main + log)

**Files:**
- Modify: `reportar.py` (agregar `gist_get`, `gist_patch`, `armar_reporte`, `main`, log)
- Test: `tests/test_reportar.py` (agregar `TestArmarReporte`)

**Interfaces:**
- Consumes: todo lo de Tasks 1–2, `GIST_ID` real de Task 3.
- Produces (usadas por Task 8): CLI `python3 reportar.py` (reporta), `--dry-run` (imprime el estado fusionado sin publicar), `--probe` (Task 2).
  - `armar_reporte(claude_json: dict, projects_dir, local_hostname, hostname_s, uso: dict|None, ahora: str) -> tuple[str, str|None, dict|None, dict|None]` — `(clave, cuenta, actividad, cupo)`

- [ ] **Paso 1: Test de `armar_reporte` (falla)**

```python
class TestArmarReporte(unittest.TestCase):
    def test_integra_colectores_sin_tocar_red(self):
        with tempfile.TemporaryDirectory() as tmp:
            cj = {"oauthAccount": {"displayName": "Gamma"}}
            uso = json.loads((Path(__file__).parent / "fixtures" / "uso_real.json").read_text())
            clave, cuenta, actividad, cupo = reportar.armar_reporte(
                cj, tmp, "Mini", "mini", uso, "2026-08-11T18:00:00Z")
            self.assertEqual(clave, "Mini")
            self.assertEqual(cuenta, "Gamma")
            self.assertIsNone(actividad)
            self.assertIsInstance(cupo["cinco_horas"]["pct"], int)

    def test_deslogueado_y_sin_uso(self):
        with tempfile.TemporaryDirectory() as tmp:
            clave, cuenta, actividad, cupo = reportar.armar_reporte(
                {}, tmp, None, "mini", None, "2026-08-11T18:00:00Z")
            self.assertEqual(clave, "mini")
            self.assertIsNone(cuenta)
            self.assertIsNone(cupo)
```

Run: `python3 -m unittest tests.test_reportar.TestArmarReporte -v` → ERROR (no existe `armar_reporte`).

- [ ] **Paso 2: Implementar `armar_reporte`, gist y `main`**

Agregar a `reportar.py`:

```python
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
```

Y reemplazar el bloque `if __name__ == "__main__":` de Task 2 por:

```python
if __name__ == "__main__":
    if "--probe" in sys.argv:
        tok = leer_token_anthropic()
        if not tok:
            print("sin token (Keychain denegado o vacío)", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(consultar_uso(tok), indent=2))
    else:
        main(dry_run="--dry-run" in sys.argv)
```

- [ ] **Paso 3: Tests y dry-run real**

Run: `python3 -m unittest discover -s tests -v` → `OK` (16 tests)
Run: `python3 reportar.py --dry-run | head -30` → imprime el estado con la entrada de este compu (cuenta "Gamma", cupo con pcts).

- [ ] **Paso 4: Primer reporte real y verificación**

Run: `python3 reportar.py && curl -s https://api.github.com/gists/$(python3 -c "import reportar; print(reportar.GIST_ID)") | python3 -c "import sys,json; print(json.load(sys.stdin)['files']['estado.json']['content'])"`
Expected: el `estado.json` del gist contiene este compu bajo `maquinas` y "Gamma" bajo `cuentas`.

- [ ] **Paso 5: Commit y push**

```bash
git add reportar.py tests/test_reportar.py
git commit -m "feat: publicacion al gist con retry, log y modos probe/dry-run"
git push
```

---

### Task 5: Comando `cuentas` (agregación + render terminal)

**Files:**
- Create: `cuentas.py`
- Test: `tests/test_cuentas.py`

**Interfaces:**
- Consumes: `GIST_ID` real (copiar la constante; el archivo es autocontenido, sin imports de `reportar`).
- Produces (el espejo JS de Task 6 replica EXACTAMENTE estas reglas):
  - `agregar(estado: dict, ahora: str) -> dict` con la forma:
    `{"recomendada": {"alias": str, "dato_de_hace_s": float} | None, "cuentas": [ ... ], "sin_sesion": [ ... ]}`
    — cada cuenta: `{"alias", "cupo" (dict|None), "medido", "fresco" (bool), "score" (int|None), "semaforo" ("verde"|"amarillo"|"rojo"|None), "maquinas": [{"clave", "cuenta", "ultima_actividad", "reportado", "fresco"}]}`;
    cuentas ordenadas por (sin-cupo al final, score asc, alias); máquinas y sin_sesion por clave asc.
  - `humanizar(segundos: float) -> str` — `"hace un momento"` (<60), `"hace 4 min"`, `"hace 3 h"`, `"hace 2 d"`
  - `render(agregado: dict, ahora: str) -> str`

- [ ] **Paso 1: Tests de agregación (fallan)**

```python
# tests/test_cuentas.py
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cuentas

AHORA = "2026-08-11T18:00:00Z"


def estado_demo():
    return {
        "version": 1,
        "maquinas": {
            "Mini": {"cuenta": "Gamma",
                     "ultima_actividad": {"hace": "2026-08-11T17:58:00Z", "proyecto": "front-v2"},
                     "reportado": "2026-08-11T17:59:00Z"},
            "Air": {"cuenta": "Alpha", "ultima_actividad": None,
                    "reportado": "2026-08-11T17:58:00Z"},
            "Pro": {"cuenta": None,
                    "ultima_actividad": {"hace": "2026-08-11T15:00:00Z", "proyecto": "siteforge"},
                    "reportado": "2026-08-11T17:57:00Z"},
        },
        "cuentas": {
            "Gamma": {"cinco_horas": {"pct": 62, "resetea": "2026-08-11T20:00:00Z"},
                      "semanal": {"pct": 31, "resetea": "2026-08-14T13:00:00Z"},
                      "medido": "2026-08-11T17:59:00Z", "por": "Mini"},
            "Alpha": {"cinco_horas": {"pct": 15, "resetea": "2026-08-11T19:00:00Z"},
                      "semanal": {"pct": 48, "resetea": "2026-08-13T10:00:00Z"},
                      "medido": "2026-08-11T17:58:00Z", "por": "Air"},
            "Beta": {"cinco_horas": {"pct": 91, "resetea": "2026-08-11T18:30:00Z"},
                     "semanal": {"pct": 22, "resetea": "2026-08-12T09:00:00Z"},
                     "medido": "2026-08-11T17:00:00Z", "por": "Pro"},
        },
    }


class TestAgregar(unittest.TestCase):
    def test_recomendada_fresca_menor_score(self):
        agg = cuentas.agregar(estado_demo(), AHORA)
        self.assertEqual(agg["recomendada"]["alias"], "Alpha")  # score 48 < 62; Beta no fresca
        self.assertEqual(agg["recomendada"]["dato_de_hace_s"], 0)

    def test_semaforos_y_orden(self):
        agg = cuentas.agregar(estado_demo(), AHORA)
        por_alias = {c["alias"]: c for c in agg["cuentas"]}
        self.assertEqual(por_alias["Alpha"]["semaforo"], "verde")     # score 48
        self.assertEqual(por_alias["Gamma"]["semaforo"], "amarillo")  # score 62
        self.assertEqual(por_alias["Beta"]["semaforo"], "rojo")       # score 91
        self.assertEqual([c["alias"] for c in agg["cuentas"]], ["Alpha", "Gamma", "Beta"])

    def test_beta_no_fresca_pero_visible(self):
        agg = cuentas.agregar(estado_demo(), AHORA)
        beta = [c for c in agg["cuentas"] if c["alias"] == "Beta"][0]
        self.assertFalse(beta["fresco"])
        self.assertEqual(beta["maquinas"], [])  # Pro esta deslogueado

    def test_sin_sesion(self):
        agg = cuentas.agregar(estado_demo(), AHORA)
        self.assertEqual([m["clave"] for m in agg["sin_sesion"]], ["Pro"])

    def test_fallback_todas_viejas(self):
        e = estado_demo()
        for c in e["cuentas"].values():
            c["medido"] = "2026-08-11T08:00:00Z"
        agg = cuentas.agregar(e, AHORA)
        self.assertEqual(agg["recomendada"]["alias"], "Alpha")
        self.assertGreater(agg["recomendada"]["dato_de_hace_s"], 900)

    def test_sin_ningun_cupo(self):
        e = estado_demo()
        e["cuentas"] = {}
        agg = cuentas.agregar(e, AHORA)
        self.assertIsNone(agg["recomendada"])
        self.assertEqual(len(agg["cuentas"]), 2)  # aliases desde maquinas: Alpha y Gamma (Pro no aporta)

    def test_cuenta_solo_en_maquinas_aparece_sin_cupo(self):
        e = estado_demo()
        del e["cuentas"]["Alpha"]
        agg = cuentas.agregar(e, AHORA)
        alpha = [c for c in agg["cuentas"] if c["alias"] == "Alpha"][0]
        self.assertIsNone(alpha["cupo"])
        self.assertIsNone(alpha["semaforo"])
        self.assertEqual(agg["cuentas"][-1]["alias"], "Alpha")  # sin cupo al final


class TestHumanizar(unittest.TestCase):
    def test_rangos(self):
        self.assertEqual(cuentas.humanizar(30), "hace un momento")
        self.assertEqual(cuentas.humanizar(240), "hace 4 min")
        self.assertEqual(cuentas.humanizar(3600 * 3 + 100), "hace 3 h")
        self.assertEqual(cuentas.humanizar(86400 * 2 + 100), "hace 2 d")


class TestRender(unittest.TestCase):
    def test_render_contiene_lo_esencial(self):
        salida = cuentas.render(cuentas.agregar(estado_demo(), AHORA), AHORA)
        self.assertIn("→ Usa: Alpha", salida)
        self.assertIn("Gamma", salida)
        self.assertIn("Sin sesión", salida)
        self.assertIn("Pro", salida)

    def test_render_sin_dato(self):
        agg = cuentas.agregar({"maquinas": {}, "cuentas": {}}, AHORA)
        self.assertIn("Sin dato de cupo", cuentas.render(agg, AHORA))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Paso 2: Verificar que fallan**

Run: `python3 -m unittest tests.test_cuentas -v`
Expected: ERROR `ModuleNotFoundError: No module named 'cuentas'`

- [ ] **Paso 3: Implementar `cuentas.py`**

```python
#!/usr/bin/env python3
"""Comando `cuentas`: estado de las cuentas de Claude en la terminal."""
import json
import sys
import urllib.request
from datetime import datetime, timezone

GIST_ID = "PENDIENTE_BOOTSTRAP"  # mismo valor que reportar.py (Task 3)
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


def main():
    req = urllib.request.Request(
        f"https://api.github.com/gists/{GIST_ID}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "claude-tablero"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        estado = json.loads(json.load(resp)["files"][GIST_FILE]["content"])
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(render(agregar(estado, ahora), ahora))


if __name__ == "__main__":
    main()
```

Reemplazar `PENDIENTE_BOOTSTRAP` por el GIST_ID real (ya está en `reportar.py`).

- [ ] **Paso 4: Verificar que pasan + prueba real**

Run: `python3 -m unittest discover -s tests -v` → `OK` (todos)
Run: `python3 cuentas.py` → tabla real con Gamma y este compu.

- [ ] **Paso 5: Commit y push**

```bash
git add cuentas.py tests/test_cuentas.py
git commit -m "feat: comando cuentas con agregacion y render"
git push
```

---

### Task 6: Agregación en JS (espejo exacto)

**Files:**
- Create: `agregacion.js`
- Test: `tests/agregacion.test.js`

**Interfaces:**
- Consumes: las reglas de `cuentas.py` (Task 5) — misma semántica, mismos nombres de campos.
- Produces (usadas por `index.html` en Task 7): globals `agregar(estado, ahoraIso)`, `humanizar(segundos)`, `FRESCO_S`; y `module.exports = {agregar, humanizar, FRESCO_S}` para node.

- [ ] **Paso 1: Tests (fallan)**

Portar a JS los MISMOS casos de `TestAgregar` y `TestHumanizar` del Task 5 (mismo `estado_demo`, mismos asserts):

```js
// tests/agregacion.test.js
const { test } = require("node:test");
const assert = require("node:assert");
const { agregar, humanizar } = require("../agregacion.js");

const AHORA = "2026-08-11T18:00:00Z";

function estadoDemo() {
  return {
    version: 1,
    maquinas: {
      Mini: { cuenta: "Gamma", ultima_actividad: { hace: "2026-08-11T17:58:00Z", proyecto: "front-v2" }, reportado: "2026-08-11T17:59:00Z" },
      Air: { cuenta: "Alpha", ultima_actividad: null, reportado: "2026-08-11T17:58:00Z" },
      Pro: { cuenta: null, ultima_actividad: { hace: "2026-08-11T15:00:00Z", proyecto: "siteforge" }, reportado: "2026-08-11T17:57:00Z" },
    },
    cuentas: {
      Gamma: { cinco_horas: { pct: 62, resetea: "2026-08-11T20:00:00Z" }, semanal: { pct: 31, resetea: "2026-08-14T13:00:00Z" }, medido: "2026-08-11T17:59:00Z", por: "Mini" },
      Alpha: { cinco_horas: { pct: 15, resetea: "2026-08-11T19:00:00Z" }, semanal: { pct: 48, resetea: "2026-08-13T10:00:00Z" }, medido: "2026-08-11T17:58:00Z", por: "Air" },
      Beta: { cinco_horas: { pct: 91, resetea: "2026-08-11T18:30:00Z" }, semanal: { pct: 22, resetea: "2026-08-12T09:00:00Z" }, medido: "2026-08-11T17:00:00Z", por: "Pro" },
    },
  };
}

test("recomendada fresca de menor score", () => {
  const agg = agregar(estadoDemo(), AHORA);
  assert.equal(agg.recomendada.alias, "Alpha");
  assert.equal(agg.recomendada.dato_de_hace_s, 0);
});

test("semaforos y orden", () => {
  const agg = agregar(estadoDemo(), AHORA);
  const por = Object.fromEntries(agg.cuentas.map(c => [c.alias, c]));
  assert.equal(por.Alpha.semaforo, "verde");
  assert.equal(por.Gamma.semaforo, "amarillo");
  assert.equal(por.Beta.semaforo, "rojo");
  assert.deepEqual(agg.cuentas.map(c => c.alias), ["Alpha", "Gamma", "Beta"]);
});

test("beta no fresca pero visible, Pro sin sesion", () => {
  const agg = agregar(estadoDemo(), AHORA);
  const beta = agg.cuentas.find(c => c.alias === "Beta");
  assert.equal(beta.fresco, false);
  assert.deepEqual(beta.maquinas, []);
  assert.deepEqual(agg.sin_sesion.map(m => m.clave), ["Pro"]);
});

test("fallback todas viejas", () => {
  const e = estadoDemo();
  for (const c of Object.values(e.cuentas)) c.medido = "2026-08-11T08:00:00Z";
  const agg = agregar(e, AHORA);
  assert.equal(agg.recomendada.alias, "Alpha");
  assert.ok(agg.recomendada.dato_de_hace_s > 900);
});

test("sin ningun cupo", () => {
  const e = estadoDemo();
  e.cuentas = {};
  const agg = agregar(e, AHORA);
  assert.equal(agg.recomendada, null);
  assert.equal(agg.cuentas.length, 2);
});

test("cuenta sin cupo va al final", () => {
  const e = estadoDemo();
  delete e.cuentas.Alpha;
  const agg = agregar(e, AHORA);
  assert.equal(agg.cuentas[agg.cuentas.length - 1].alias, "Alpha");
  assert.equal(agg.cuentas[agg.cuentas.length - 1].semaforo, null);
});

test("humanizar", () => {
  assert.equal(humanizar(30), "hace un momento");
  assert.equal(humanizar(240), "hace 4 min");
  assert.equal(humanizar(3600 * 3 + 100), "hace 3 h");
  assert.equal(humanizar(86400 * 2 + 100), "hace 2 d");
});
```

Run: `node --test` → FAIL (no existe `agregacion.js`).

- [ ] **Paso 2: Implementar `agregacion.js`**

```js
// Reglas de agregación del tablero — espejo exacto de cuentas.py (§4.3 del spec).
const FRESCO_S = 900;

function edad(ahora, iso) {
  return (Date.parse(ahora) - Date.parse(iso)) / 1000;
}

function semaforo(score) {
  return score < 50 ? "verde" : score <= 80 ? "amarillo" : "rojo";
}

function agregar(estado, ahora) {
  const maquinas = estado.maquinas || {};
  const cupos = estado.cuentas || {};
  const aliases = [...new Set([
    ...Object.keys(cupos),
    ...Object.values(maquinas).map(m => m.cuenta).filter(Boolean),
  ])].sort();

  const maquina = (clave, m) => ({ clave, ...m, fresco: edad(ahora, m.reportado) <= FRESCO_S });
  const claves = Object.keys(maquinas).sort();

  const lista = aliases.map(alias => {
    const c = cupos[alias] || null;
    const item = {
      alias, cupo: null, medido: null, fresco: false, score: null, semaforo: null,
      maquinas: claves.filter(k => maquinas[k].cuenta === alias).map(k => maquina(k, maquinas[k])),
    };
    if (c) {
      const score = Math.max(c.cinco_horas.pct, c.semanal.pct);
      Object.assign(item, {
        cupo: c, medido: c.medido, fresco: edad(ahora, c.medido) <= FRESCO_S,
        score, semaforo: semaforo(score),
      });
    }
    return item;
  });

  const conCupo = lista.filter(c => c.cupo);
  const frescas = conCupo.filter(c => c.fresco);
  const pool = frescas.length ? frescas : conCupo;
  let recomendada = null;
  if (pool.length) {
    const elegida = [...pool].sort((a, b) =>
      a.score - b.score || a.cupo.cinco_horas.pct - b.cupo.cinco_horas.pct)[0];
    recomendada = {
      alias: elegida.alias,
      dato_de_hace_s: elegida.fresco ? 0 : edad(ahora, elegida.medido),
    };
  }

  lista.sort((a, b) =>
    (a.cupo === null) - (b.cupo === null) ||
    (a.score ?? 999) - (b.score ?? 999) ||
    // ordinal por codepoint — localeCompare divergiría del orden de Python
    (a.alias > b.alias) - (a.alias < b.alias));

  const sin_sesion = claves.filter(k => !maquinas[k].cuenta).map(k => maquina(k, maquinas[k]));
  return { recomendada, cuentas: lista, sin_sesion };
}

function humanizar(segundos) {
  if (segundos < 60) return "hace un momento";
  if (segundos < 3600) return `hace ${Math.floor(segundos / 60)} min`;
  if (segundos < 86400) return `hace ${Math.floor(segundos / 3600)} h`;
  return `hace ${Math.floor(segundos / 86400)} d`;
}

if (typeof module !== "undefined") module.exports = { agregar, humanizar, FRESCO_S };
```

- [ ] **Paso 3: Verificar que pasan**

Run: `node --test` → todos PASS. Y `python3 -m unittest discover -s tests -v` sigue `OK`.

- [ ] **Paso 4: Commit y push**

```bash
git add agregacion.js tests/agregacion.test.js
git commit -m "feat: agregacion en JS, espejo de cuentas.py"
git push
```

---

### Task 7: Tablero web (`index.html`)

**Files:**
- Create: `index.html`

**Interfaces:**
- Consumes: `agregar`/`humanizar`/`FRESCO_S` globals de `agregacion.js`; `GIST_ID` real.

**Nota:** antes de escribir el HTML, cargar el skill `dataviz` (hay barras/medidores) y seguir su sistema visual; si no está disponible, seguir el diseño de abajo tal cual.

- [ ] **Paso 1: Implementar la página**

Estructura obligatoria (el ejecutor puede mejorar el CSS, no el comportamiento):

```html
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tablero cuentas Claude</title>
<style>
  :root {
    --fondo: #f6f7f9; --tarjeta: #ffffff; --texto: #1a1d21; --sutil: #6b7280;
    --verde: #16a34a; --amarillo: #d97706; --rojo: #dc2626; --pista: #e5e7eb;
  }
  @media (prefers-color-scheme: dark) {
    :root { --fondo: #101418; --tarjeta: #1a2027; --texto: #e7eaee; --sutil: #94a3b8; --pista: #2b3440; }
  }
  * { box-sizing: border-box; margin: 0; }
  body { background: var(--fondo); color: var(--texto);
         font: 16px/1.5 -apple-system, system-ui, sans-serif; padding: 16px;
         max-width: 640px; margin: 0 auto; }
  .banner { border-radius: 12px; padding: 14px 16px; margin-bottom: 16px;
            background: var(--tarjeta); border-left: 5px solid var(--verde);
            font-size: 18px; font-weight: 600; }
  .banner.sin-dato { border-left-color: var(--sutil); color: var(--sutil); }
  .tarjeta { background: var(--tarjeta); border-radius: 12px; padding: 14px 16px;
             margin-bottom: 12px; }
  .tarjeta.vieja { opacity: .55; }
  .cabecera { display: flex; justify-content: space-between; align-items: baseline; }
  .alias { font-size: 17px; font-weight: 700; }
  .reset { color: var(--sutil); font-size: 13px; }
  .medidor { margin-top: 8px; }
  .medidor .etiqueta { display: flex; justify-content: space-between;
                       font-size: 13px; color: var(--sutil); }
  .pista { background: var(--pista); border-radius: 6px; height: 8px; margin-top: 3px; }
  .relleno { height: 100%; border-radius: 6px; }
  .verde .relleno { background: var(--verde); }
  .amarillo .relleno { background: var(--amarillo); }
  .rojo .relleno { background: var(--rojo); }
  .compus { margin-top: 10px; font-size: 14px; }
  .compu { display: flex; justify-content: space-between; padding: 3px 0; }
  .compu.viejo { color: var(--sutil); }
  h2 { font-size: 14px; color: var(--sutil); margin: 18px 0 8px; text-transform: uppercase; }
  .pie { color: var(--sutil); font-size: 13px; margin-top: 16px;
         display: flex; justify-content: space-between; align-items: center; }
  button { background: none; border: 1px solid var(--pista); color: var(--texto);
           border-radius: 8px; padding: 6px 12px; font-size: 13px; }
</style>
</head>
<body>
<div id="app">Cargando…</div>
<div class="pie"><span id="actualizado"></span><button onclick="cargar()">Refrescar</button></div>
<script src="agregacion.js"></script>
<script>
const GIST_ID = "PENDIENTE_BOOTSTRAP"; // mismo valor que reportar.py
let ultimoEstado = null;

function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function cuentaRegresiva(iso, ahora, viejo) {
  if (!iso) return "";
  const s = (Date.parse(iso) - Date.parse(ahora)) / 1000;
  if (s <= 0) return viejo ? "ventana reseteada" : "reseteando…";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `resetea en ${h} h ${m} m` : `resetea en ${m} m`;
}

function medidor(nombre, ventana, clase, ahora, viejo) {
  return `<div class="medidor ${clase}">
    <div class="etiqueta"><span>${nombre} · ${esc(String(ventana.pct))}%</span>
      <span>${esc(cuentaRegresiva(ventana.resetea, ahora, viejo))}</span></div>
    <div class="pista"><div class="relleno" style="width:${Math.min(ventana.pct, 100)}%"></div></div>
  </div>`;
}

function compuHtml(m, ahora) {
  const act = m.ultima_actividad;
  const det = act ? `${humanizar((Date.parse(ahora) - Date.parse(act.hace)) / 1000)} · ${esc(act.proyecto || "?")}`
                  : "sin actividad";
  const extra = m.fresco ? "" :
    ` · sin reporte ${humanizar((Date.parse(ahora) - Date.parse(m.reportado)) / 1000)}`;
  return `<div class="compu ${m.fresco ? "" : "viejo"}"><span>${esc(m.clave)}</span><span>${det}${extra}</span></div>`;
}

function pintar(estado) {
  const ahora = new Date().toISOString();
  const agg = agregar(estado, ahora);
  let html = "";
  const r = agg.recomendada;
  if (r === null) {
    html += `<div class="banner sin-dato">Sin dato de cupo</div>`;
  } else {
    const nota = r.dato_de_hace_s > FRESCO_S
      ? ` <small>(con dato de ${humanizar(r.dato_de_hace_s)})</small>` : "";
    html += `<div class="banner">→ Usa: ${esc(r.alias)}${nota}</div>`;
  }
  for (const c of agg.cuentas) {
    const vieja = c.cupo && !c.fresco;
    html += `<div class="tarjeta ${vieja ? "vieja" : ""}">
      <div class="cabecera"><span class="alias">${esc(c.alias)}</span>
        <span class="reset">${c.cupo && vieja ? "dato de " + humanizar((Date.parse(ahora) - Date.parse(c.medido)) / 1000) : ""}</span></div>`;
    if (c.cupo) {
      html += medidor("5 h", c.cupo.cinco_horas, c.semaforo, ahora, vieja);
      html += medidor("Semana", c.cupo.semanal, c.semaforo, ahora, vieja);
    } else {
      html += `<div class="reset">cupo desconocido</div>`;
    }
    if (c.maquinas.length) {
      html += `<div class="compus">${c.maquinas.map(m => compuHtml(m, ahora)).join("")}</div>`;
    }
    html += `</div>`;
  }
  if (agg.sin_sesion.length) {
    html += `<h2>Sin sesión</h2><div class="tarjeta"><div class="compus">
      ${agg.sin_sesion.map(m => compuHtml(m, ahora)).join("")}</div></div>`;
  }
  document.getElementById("app").innerHTML = html;
  document.getElementById("actualizado").textContent =
    "Actualizado " + new Date().toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });
}

async function cargar() {
  try {
    const resp = await fetch(`https://api.github.com/gists/${GIST_ID}`,
      { headers: { Accept: "application/vnd.github+json" } });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    ultimoEstado = JSON.parse((await resp.json()).files["estado.json"].content);
    pintar(ultimoEstado);
  } catch (e) {
    if (ultimoEstado) { pintar(ultimoEstado); }
    else { document.getElementById("app").textContent = `No se pudo cargar (${e.message}). Reintento en 2 min.`; }
  }
}

cargar();
setInterval(cargar, 120000);
</script>
</body>
</html>
```

Reemplazar `PENDIENTE_BOOTSTRAP` por el GIST_ID real.

- [ ] **Paso 2: Probar localmente**

Run: `cd ~/Documents/Prolibu/claude-tablero && python3 -m http.server 8765 &` y abrir `http://localhost:8765` con las herramientas de browser (claude-in-chrome). Verificar: banner con "→ Usa:", tarjeta de Gamma con dos barras, compu listado, sin errores en consola. Matar el server después (`kill %1`).

- [ ] **Paso 3: Commit, push y verificación en Pages**

```bash
git add index.html
git commit -m "feat: tablero web mobile-first"
git push
```

Esperar 1–2 min y abrir `https://santiago-prolibu.github.io/claude-tablero/` — debe mostrar el mismo tablero. Si 404, revisar que Pages quedó activado (Task 3 Paso 6).

---

### Task 8: launchd + instalador

**Files:**
- Create: `com.prolibu.claude-tablero.plist`
- Create: `instalar.sh`

**Interfaces:**
- Consumes: `reportar.py` y `cuentas.py` completos y pusheados (raw.githubusercontent los sirve).
- Produces: instalación reproducible por compu; este compu queda instalado de verdad.

- [ ] **Paso 1: Plantilla launchd**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.prolibu.claude-tablero</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>__HOME__/.claude-tablero/reportar.py</string>
  </array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>__HOME__/.claude-tablero/launchd.log</string>
  <key>StandardErrorPath</key><string>__HOME__/.claude-tablero/launchd.log</string>
</dict>
</plist>
```

- [ ] **Paso 2: Instalador**

```bash
#!/bin/bash
# Instala el reportero del tablero de cuentas de Claude en este Mac. Idempotente.
set -euo pipefail

RAW="https://raw.githubusercontent.com/santiago-prolibu/claude-tablero/main"
DIR="$HOME/.claude-tablero"
PLIST="$HOME/Library/LaunchAgents/com.prolibu.claude-tablero.plist"
LABEL="com.prolibu.claude-tablero"

mkdir -p "$DIR" "$HOME/Library/LaunchAgents"

# 1. PAT (solo la primera vez)
if [ ! -s "$DIR/token" ]; then
  printf "Pega el PAT de GitHub (scope gist): "
  read -r -s TOKEN < /dev/tty
  echo
  printf '%s' "$TOKEN" > "$DIR/token"
  chmod 600 "$DIR/token"
fi

# 2. Scripts
curl -fsSL "$RAW/reportar.py" -o "$DIR/reportar.py"
DESTINO_CMD="/usr/local/bin/cuentas"
if ! curl -fsSL "$RAW/cuentas.py" -o "$DESTINO_CMD" 2>/dev/null; then
  mkdir -p "$HOME/.local/bin"
  DESTINO_CMD="$HOME/.local/bin/cuentas"
  curl -fsSL "$RAW/cuentas.py" -o "$DESTINO_CMD"
  echo "aviso: instalado en $DESTINO_CMD — asegúrate de tener ~/.local/bin en el PATH"
fi
chmod +x "$DESTINO_CMD"

# 3. launchd
curl -fsSL "$RAW/com.prolibu.claude-tablero.plist" | sed "s|__HOME__|$HOME|g" > "$PLIST.tmp" && mv "$PLIST.tmp" "$PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

# 4. Primer reporte (aquí macOS pregunta por el Keychain → "Permitir siempre")
echo "Primer reporte…"
/usr/bin/python3 "$DIR/reportar.py" && echo "ok — mira el tablero" || echo "fallo; revisa $DIR/reportar.log"
```

- [ ] **Paso 3: Probar el instalador en este compu (instalación real)**

Run: `git add com.prolibu.claude-tablero.plist instalar.sh && git commit -m "feat: launchd e instalador" && git push`
Luego: `bash instalar.sh` (el PAT ya existe, no lo pide).
Expected: launchd cargado y primer reporte ok. Nota: el primer reporte puede pedir el permiso del Keychain en pantalla — avisar a Santiago que marque "Permitir siempre".

- [ ] **Paso 4: Verificar launchd**

Run: `launchctl print gui/$(id -u)/com.prolibu.claude-tablero | grep -E "state|interval"` y `tail -3 ~/.claude-tablero/reportar.log`
Expected: job cargado con interval 300; log con línea `ok <clave> cuenta=Gamma cupo=si`.

- [ ] **Paso 5: Probar `cuentas` instalado**

Run: `cuentas`
Expected: tabla real (mismo output que `python3 cuentas.py`).

---

### Task 9: README + verificación E2E

**Files:**
- Create: `README.md`

- [ ] **Paso 1: README**

```markdown
# claude-tablero

¿Cuál cuenta de Claude uso ahora? Tablero de cupo (5 h + semanal), mapeo
compu ↔ cuenta y última actividad de todos los Macs.

- **Tablero web:** https://santiago-prolibu.github.io/claude-tablero/
- **Terminal:** `cuentas`

## Instalar en un compu nuevo

```bash
curl -fsSL https://raw.githubusercontent.com/santiago-prolibu/claude-tablero/main/instalar.sh | bash
```

Pide el PAT de GitHub (scope `gist`) la primera vez y el permiso del
Keychain en el primer reporte (marcar "Permitir siempre"). Listo: reporta
cada 5 min vía launchd.

## Cómo funciona

Cada Mac corre `reportar.py` (launchd, cada 5 min): lee la cuenta activa de
`~/.claude.json`, el cupo del endpoint OAuth de uso y la última actividad de
`~/.claude/projects/`, y actualiza su entrada en un gist (`estado.json`).
La página y el comando `cuentas` leen ese gist. Diseño completo en
`docs/superpowers/specs/`.

## Tests

```bash
python3 -m unittest discover -s tests -v
node --test tests/
```
```

- [ ] **Paso 2: Verificación E2E completa**

1. `python3 -m unittest discover -s tests -v` → OK; `node --test tests/` → PASS.
2. `tail -5 ~/.claude-tablero/reportar.log` → reportes `ok` periódicos (esperar ≥5 min desde Task 8 para ver el segundo).
3. `cuentas` → muestra Gamma con cupo y este compu.
4. Abrir `https://santiago-prolibu.github.io/claude-tablero/` en el browser → banner, tarjeta Gamma, compu listado.
5. Confirmar que el gist NO contiene emails: `curl -s https://api.github.com/gists/<GIST_ID> | grep -c "@"` → `0` apariciones en el contenido de estado.json (el JSON del API incluye URLs con el user de GitHub; revisar solo el campo content).

- [ ] **Paso 3: Commit final y push**

```bash
git add README.md
git commit -m "docs: README con instalacion y funcionamiento"
git push
```

- [ ] **Paso 4: Entregar a Santiago los pasos para los otros compus**

Mensaje final con: la URL del tablero, y la línea para pegarle al agente de Claude de cada otro compu:

```
Corre: curl -fsSL https://raw.githubusercontent.com/santiago-prolibu/claude-tablero/main/instalar.sh | bash
— te va a pedir un PAT (te lo paso yo) y al final macOS pregunta por el Keychain: marca "Permitir siempre".
```

Recordarle que el PAT es el mismo para todos los compus.
