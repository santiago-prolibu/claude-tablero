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

Si la API no manda el límite de 5 h de una cuenta (`five_hour: null`), el
reporte guarda `cinco_horas: { pct: 0, resetea: null, no_reportado: true }`:
se pinta «no reportado» y la cuenta se ordena por su semanal. El `pct` sigue
siendo un número para no romper los `cuentas` ya instalados, que leen el mismo
gist (uno viejo muestra 0 % hasta actualizarlo). Una respuesta que no se pueda
interpretar deja `uso sin cupo legible` en `~/.claude-tablero/reportar.log`.

## Actualizar un compu ya instalado

`reportar.py` y `cuentas` se instalan por copia: publicar en `main` solo
actualiza la página. Para que un compu tome una versión nueva, vuelve a correr
el mismo comando de instalación (es idempotente y no pide el PAT otra vez).

Para probar la página con otro estado (p. ej. uno local) sin tocar el gist:
`index.html?estado=<url-del-json>`.

## Tests

```bash
python3 -m unittest discover -s tests -v
node --test tests/agregacion.test.js
```
