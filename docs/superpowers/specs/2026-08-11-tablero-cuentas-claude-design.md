# Tablero de cuentas de Claude — Diseño

**Fecha:** 2026-08-11
**Autor:** Santiago Forero (con Claude)
**Estado:** Aprobado en diseño conversacional; pendiente revisión del spec escrito.

## 1. Problema

Santiago tiene 3 cuentas de Claude (suscripciones independientes) repartidas entre varios computadores, con agentes de Claude Code trabajando en todos. Las cuentas rotan entre compus (logout/login según cupo) y a veces hay más compus que cuentas. Hoy no hay forma de saber, sin ir compu por compu:

- Cuál cuenta tiene cupo disponible (ventana de 5 horas y límite semanal).
- Qué cuenta está logueada en cada computador.
- Hace cuánto trabajó cada compu y en qué proyecto.

## 2. Objetivo y criterios de éxito

Un tablero consultable desde cualquier lado (web en el celular + comando de terminal) que responda de un vistazo: **"¿cuál cuenta uso ahora?"**.

Criterios de éxito:

1. Desde el celular, en menos de 5 segundos de abrir la URL, se ve qué cuenta tiene más cupo y cuál está agotada.
2. Al rotar una cuenta en un compu, el mapeo compu↔cuenta se corrige solo en ≤5 minutos.
3. `cuentas` en la terminal de cualquier compu instalado imprime la misma información.
4. Instalar el sistema en un compu nuevo toma una línea de comando y menos de 2 minutos.
5. Nunca se publica un dato sensible: ni emails, ni tokens, ni contenido de sesiones.

## 3. Decisiones de arquitectura

**Opción elegida: Gist de GitHub como almacén + página estática en GitHub Pages** (sobre Cloudflare Worker y Google Sheets, descartadas por requerir infra/cuentas nuevas o setup engorroso).

- Los compus solo tienen internet (sin red común ni VPN) → cada uno **publica** su estado a un punto común.
- El punto común es un **gist secreto** con un archivo `estado.json`. Escritura: solo con token de GitHub (PAT fine-grained con permiso únicamente de gists). Lectura: anónima para quien tenga la URL. Santiago aceptó explícitamente que la lectura sea pública-por-URL; se mitiga publicando solo alias y porcentajes.
- El código vive en un **repo público** `santiago-prolibu/claude-tablero` que además sirve el tablero web por GitHub Pages. El ID del gist va embebido en la página y en la config del repo (aceptado como público).

```
┌─ Compu 1 ─┐  ┌─ Compu 2 ─┐  ┌─ Compu N ─┐
│ reportero  │  │ reportero  │  │ reportero  │   cada 5 min (launchd)
└─────┬──────┘  └─────┬──────┘  └─────┬──────┘
      └───────────────┼───────────────┘
                      ▼  escribe (PAT solo-gists)
              Gist secreto: estado.json
                      │  lee (URL, sin auth)
        ┌─────────────┴─────────────┐
        ▼                           ▼
  Tablero web (GitHub Pages)   comando `cuentas`
```

## 4. Componentes

### 4.1 Reportero (`reportar.sh`)

Script bash + python3 (sin dependencias externas; ambos presentes en macOS con las herramientas de desarrollo). Instalado en `~/.claude-tablero/reportar.sh`. Cada ejecución:

1. **Identidad del compu:** la clave de la entrada es `scutil --get LocalHostName` (estable ante cambios de red, sin espacios; fallback `hostname -s` si viniera vacío). Nunca `hostname` a secas: su sufijo (`.local`/`.lan`) varía según la red y crearía entradas fantasma.
2. **Cuenta logueada:** lee `~/.claude.json` → `oauthAccount.emailAddress` y `oauthAccount.displayName`. El `displayName` (p. ej. "Gamma") es el **alias público**; el email jamás sale del compu. Si no hay `oauthAccount` (compu deslogueado durante una rotación), publica `cuenta: null` — el mapeo y la última actividad siguen valiendo.
3. **Cupo:** lee el token OAuth de Claude Code del Keychain de macOS (servicio `Claude Code-credentials`; primera lectura pide autorización → "Permitir siempre", una vez por compu) y consulta el endpoint de uso OAuth de Anthropic (el mismo que alimenta `/usage`; el binario instalado confirma `GET /api/oauth/usage`). Extrae: % usado de la ventana de 5 h, % del límite semanal, y timestamps de reset de ambas. El endpoint y los headers exactos se validan en la implementación en este compu antes de replicar a los demás; cualquier fallo (401 por token vencido, cambio de API, sin red, deslogueado) degrada a cupo no medido sin abortar el reporte.
4. **Última actividad:** busca el `.jsonl` más reciente bajo `~/.claude/projects/*/` → el timestamp es el mtime del archivo, y el nombre del proyecto es el **basename del campo `cwd`** que aparece en las primeras líneas de ese `.jsonl` (verificado en este compu). No se des-serializa el nombre de la carpeta: la codificación de `/` como `-` es ambigua frente a guiones reales (`-Users-agox-...-prolibu-front-v2` no permite recuperar `prolibu-front-v2` de forma unívoca).
5. **Publica:** GET del gist → en `estado.json` reemplaza **su propia entrada** en `maquinas` (clave: LocalHostName) y, si midió cupo, actualiza también `cuentas[<alias>]` (último cupo conocido de esa cuenta) → PATCH del gist con el PAT.

Programación: **launchd** (`~/Library/LaunchAgents/com.prolibu.claude-tablero.plist`), `StartInterval` 300, `RunAtLoad` true. Logs en `~/.claude-tablero/reportar.log` (truncado para no crecer sin límite).

### 4.2 Esquema de `estado.json`

```json
{
  "version": 1,
  "maquinas": {
    "MacBook-Pro-Santiago": {
      "cuenta": "Gamma",
      "ultima_actividad": { "hace": "2026-08-11T17:42:10Z", "proyecto": "prolibu-front-v2" },
      "reportado": "2026-08-11T17:45:02Z"
    },
    "Mini-Oficina": {
      "cuenta": null,
      "ultima_actividad": { "hace": "2026-08-11T15:10:00Z", "proyecto": "siteforge" },
      "reportado": "2026-08-11T17:44:31Z"
    }
  },
  "cuentas": {
    "Gamma": {
      "cinco_horas": { "pct": 62, "resetea": "2026-08-11T20:00:00Z" },
      "semanal":     { "pct": 31, "resetea": "2026-08-14T13:00:00Z" },
      "medido": "2026-08-11T17:45:02Z",
      "por": "MacBook-Pro-Santiago"
    }
  }
}
```

El cupo es propiedad de la **cuenta**, no del compu: vive en el bloque `cuentas`, que guarda el **último cupo conocido por alias** y sobrevive a las rotaciones (si todos los compus deslogean de "Beta", su última medición queda ahí con su `medido`). `maquinas.<clave>.cuenta` es `null` cuando el compu está deslogueado. Una cuenta que nunca ha sido medida simplemente no está en `cuentas`. Campos en ISO-8601 UTC; las vistas convierten a hora local.

### 4.3 Reglas de agregación (compartidas por web y terminal)

- **Lista de cuentas** = claves de `cuentas` ∪ alias no nulos en `maquinas` (no hay lista fija; una cuenta nueva aparece sola y una rotada no desaparece).
- **Cupo por cuenta** = `cuentas[<alias>]` (último conocido), con frescura dada por su `medido`.
- **Cuenta recomendada** = la de menor `max(pct_5h, pct_semanal)` entre las que tienen cupo **fresco** (`medido` ≤ 15 min). Empate: menor `pct_5h`. Una cuenta sin cupo medido nunca participa, aunque su reporte sea fresco. **Fallback:** si ninguna tiene cupo fresco, se recomienda sobre el cupo menos viejo, marcado "con dato de hace X"; si ninguna cuenta tiene cupo en absoluto, el banner y la línea `→ Usa:` muestran "sin dato de cupo".
- **Semáforo** (sobre `max(pct_5h, pct_semanal)`): 🟢 < 50 %, 🟡 50–80 %, 🔴 > 80 %.
- **Frescura:** un compu con `reportado` > 15 min se muestra gris ("sin reporte hace X"). Una cuenta con `medido` > 15 min muestra su cupo atenuado con "dato de hace X".
- **Compus deslogueados** (`cuenta: null`): se listan en una sección aparte "Sin sesión", con su última actividad y frescura.

### 4.4 Tablero web

Página estática (HTML/CSS/JS vanilla, un solo archivo) en el repo, servida por GitHub Pages: `https://santiago-prolibu.github.io/claude-tablero/`.

- Lee el gist por la API de GitHub (`https://api.github.com/gists/<ID>`, anónimo). Auto-refresh cada **2 minutos** (≈30 req/h, bajo el límite anónimo de 60/h por IP) + botón de refresco manual.
- **Mobile-first.** Tema claro/oscuro según el sistema.
- Layout: arriba, banner con la **cuenta recomendada** (o "sin dato de cupo", según el fallback de §4.3). Luego una tarjeta por cuenta: alias, semáforo, barra del cupo 5 h y barra del semanal, cuenta regresiva "resetea en 2 h 15 m" (si el reset ya pasó, "ventana reseteada · dato de hace X"). Dentro de cada tarjeta, los compus logueados en esa cuenta: nombre, "hace 4 min · prolibu-front-v2", y estado gris si el reporte está viejo. Al final, la sección **"Sin sesión"** con los compus deslogueados.

### 4.5 Comando `cuentas`

Script (bash + python3) que lee el mismo gist por la API y pinta la tabla en la terminal, con las mismas reglas de agregación (§4.3, incluidos los fallbacks) y la línea final `→ Usa: <alias>` (o `→ Sin dato de cupo`). Instalado por el instalador en `/usr/local/bin/cuentas` (fallback `~/.local/bin` si no hay permisos, avisando del PATH).

### 4.6 Instalador (`instalar.sh`)

Una línea en cualquier compu:

```bash
curl -fsSL https://raw.githubusercontent.com/santiago-prolibu/claude-tablero/main/instalar.sh | bash
```

Hace: (1) crea `~/.claude-tablero/`; (2) si no hay token guardado, pide pegar el PAT y lo guarda en `~/.claude-tablero/token` con `chmod 600`; (3) descarga/copia `reportar.sh` y `cuentas`; (4) instala y carga el launchd; (5) dispara el primer reporte (aquí macOS pregunta lo del Keychain → "Permitir siempre"). Idempotente: correrlo de nuevo actualiza los scripts sin pedir el token otra vez.

Bootstrap único (una sola vez, en el primer compu): crear el PAT fine-grained (permiso: solo Gists) y crear el gist inicial; el ID del gist queda embebido en el repo.

## 5. Seguridad y privacidad

- **Se publica** (legible por URL): alias de cuenta, nombre local del compu (LocalHostName), porcentajes de cupo, horas de reset, último proyecto (solo el basename del directorio de trabajo), timestamps.
- **Nunca se publica:** emails, tokens (ni de GitHub ni de Anthropic), contenido de sesiones, rutas completas.
- El PAT vive solo en cada compu (`chmod 600`) y solo puede editar gists — si se filtra, el daño posible es editar gists de Santiago.
- El token de Anthropic nunca sale del compu: se usa localmente contra el endpoint de uso y ya.

## 6. Manejo de errores y casos borde

| Caso | Comportamiento |
|---|---|
| Compu apagado/dormido | Su entrada envejece; el tablero la muestra gris con "sin reporte hace X". (launchd no recupera intervalos perdidos durante el sleep — cubierto por esta misma regla de frescura.) |
| Rotación de cuenta en un compu | El siguiente reporte (≤5 min) trae el alias nuevo; el mapeo se corrige solo. El cupo de la cuenta vieja **no se pierde**: queda en `cuentas[<alias>]` con su `medido`. |
| Compu deslogueado (más compus que cuentas) | Reporta `cuenta: null` con su última actividad; las vistas lo muestran en la sección "Sin sesión". |
| Dos compus en la misma cuenta | El cupo se muestra una vez por cuenta (la medición más fresca actualiza `cuentas[<alias>]`); ambos compus se listan bajo ella. |
| Cuenta sin ningún compu logueado | Se muestra su último cupo conocido (bloque `cuentas`), atenuado y con fecha del dato. |
| Ninguna cuenta con cupo fresco (p. ej. todos los Macs dormidos de noche) | Se recomienda sobre el cupo menos viejo, marcado "con dato de hace X"; sin ningún cupo, "sin dato de cupo". |
| Token de Anthropic vencido / endpoint cambia / sin red al medir | No se actualiza `cuentas[<alias>]`; el reporte sigue publicando mapeo y actividad; la vista muestra el último cupo conocido atenuado o "cupo desconocido" si nunca hubo. |
| Choque de escrituras al gist (dos compus en el mismo segundo) | Última escritura gana y puede pisar una entrada ajena recién puesta; el ciclo siguiente (≤5 min) la restaura. Aceptado por frecuencia baja e impacto trivial. |
| Falla el PATCH al gist (red, GitHub caído) | El reportero reintenta una vez; si falla, loguea y espera el próximo ciclo. |
| API anónima de GitHub rate-limitea la lectura | Refresh de 2 min deja margen 2×; ante 403, la página muestra el último dato en memoria y reintenta después. |

## 7. Fuera de alcance (YAGNI)

- Notificaciones (push/Telegram) cuando una cuenta se agote o libere.
- Icono en la barra de menú de macOS.
- Historial de consumo / gráficas en el tiempo.
- Detalle de sesiones/agentes activos por compu (se descartó en el diseño; solo "última actividad").
- Soporte Linux/Windows (todos los compus son Mac; si aparece uno Linux, el token está en `~/.claude/.credentials.json` en vez del Keychain — se anota como extensión futura).

## 8. Plan de entrega

1. Implementar y validar el **reportero completo en este compu** (incluida la llamada real al endpoint de uso).
2. Crear gist + PAT (bootstrap) y publicar el primer `estado.json` real.
3. Tablero web + GitHub Pages, leyendo datos reales.
4. Comando `cuentas`.
5. Instalador + prueba de instalación en un segundo compu (vía el agente de Claude de ese compu).
