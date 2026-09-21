# claude-tablero

¿Cuál cuenta de Claude uso ahora? Tablero de cupo (5 h + semanal + Fable),
mapeo compu ↔ cuenta, última actividad de todos los Macs y consumo de tokens
por modelo, cuenta y máquina (hoy / 7 / 14 días, filtrable por cuenta o máquina).

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
`~/.claude.json`, el cupo del endpoint OAuth de uso (incluido el límite
semanal de Fable), la última actividad y los tokens por día y modelo de los
`.jsonl` de `~/.claude/projects/`, y actualiza su entrada en un gist
(`estado.json`). La página y el comando `cuentas` leen ese gist. Diseño
completo en `docs/superpowers/specs/`.

Para probar la página con otro estado (p. ej. uno local) sin tocar el gist:
`index.html?estado=<url-del-json>`.

## Tests

```bash
python3 -m unittest discover -s tests -v
node --test tests/agregacion.test.js
```
