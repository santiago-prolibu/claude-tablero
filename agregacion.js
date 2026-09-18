// Reglas de agregación del tablero — espejo exacto de cuentas.py (§4.3 del spec).
const FRESCO_S = 900;
// Una máquina que lleva más de un día sin reportar ya no está en uso: no se pinta.
// Sin esto el tablero arrastra fantasmas (un compu renombrado deja una entrada por nombre).
const EN_USO_S = 86400;

function edad(ahora, iso) {
  return (Date.parse(ahora) - Date.parse(iso)) / 1000;
}

// Fecha ilegible → fuera (NaN): pintarla no aporta nada y en cuentas.py `maquina()`
// la usaría para calcular `fresco`, reventando el render de la terminal.
function enUso(ahora, m) {
  return edad(ahora, m.reportado) <= EN_USO_S;
}

function semaforo(score) {
  return score < 50 ? "verde" : score <= 80 ? "amarillo" : "rojo";
}

function agregar(estado, ahora) {
  const maquinas = Object.fromEntries(
    Object.entries(estado.maquinas || {}).filter(([, m]) => enUso(ahora, m)));
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

/* ─ consumo de tokens (lo publica cada compu en maquinas[clave].consumo.dias) ─ */

// Orden fijo: la familia decide el color en todos los gráficos, así Fable siempre se ve igual.
const FAMILIAS = ["Opus", "Fable", "Sonnet", "Haiku", "Otro"];
const CAMPOS = ["msgs", "entrada", "salida", "cache_escr", "cache_lect"];

function familiaModelo(id) {
  const m = String(id).toLowerCase();
  return FAMILIAS.find(f => m.includes(f.toLowerCase())) || "Otro";
}

// "claude-opus-5" → "Opus 5"; "claude-fable-5-1" → "Fable 5.1"; "claude-opus-5[1m]" → "Opus 5 · 1M";
// "claude-haiku-4-5-20251001" → "Haiku 4.5". Lo que no encaje se muestra tal cual.
function nombreModelo(id) {
  const m = /^claude-([a-z]+)-(\d+)(?:-(\d+))?(?:-\d{8})?(\[1m\])?$/i.exec(String(id));
  if (!m) return String(id);
  const familia = m[1][0].toUpperCase() + m[1].slice(1);
  return `${familia} ${m[2]}${m[3] ? "." + m[3] : ""}${m[4] ? " · 1M" : ""}`;
}

function sumar(destino, b) {
  for (const k of CAMPOS) destino[k] = (destino[k] || 0) + (Number(b[k]) || 0);
  return destino;
}

function totales(b) {
  const entrada = (b.entrada || 0) + (b.cache_escr || 0);
  const salida = b.salida || 0, cache = b.cache_lect || 0;
  return { msgs: b.msgs || 0, entrada, salida, cache, total: entrada + salida + cache };
}

function diaMas(dia, n) {
  const d = new Date(dia + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

// `hoy` es la fecha local de quien mira (YYYY-MM-DD); la ventana son los `dias` días que
// terminan hoy. Los días del gist son locales de cada compu, así que "hoy" coincide para
// todos los que estén en la misma zona horaria.
function consumo(estado, hoy, dias) {
  const desde = diaMas(hoy, -(dias - 1));
  const enVentana = d => d >= desde && d <= hoy;
  const porDia = {}, porModelo = {}, porMaquina = {}, porCuenta = {}, porFamilia = {};
  const global = {};

  for (const [clave, m] of Object.entries(estado.maquinas || {})) {
    const diasM = (m.consumo && m.consumo.dias) || {};
    const maq = { clave, cuenta: m.cuenta || null, porFamilia: {}, acumulado: {} };
    for (const [dia, modelos] of Object.entries(diasM)) {
      if (!enVentana(dia) || !modelos || typeof modelos !== "object") continue;
      for (const [id, b] of Object.entries(modelos)) {
        if (!b || typeof b !== "object") continue;
        const fam = familiaModelo(id);
        sumar(global, b);
        sumar(maq.acumulado, b);
        sumar(maq.porFamilia[fam] = maq.porFamilia[fam] || {}, b);
        sumar(porModelo[id] = porModelo[id] || {}, b);
        sumar(porFamilia[fam] = porFamilia[fam] || {}, b);
        const pd = porDia[dia] = porDia[dia] || { porFamilia: {}, acumulado: {} };
        sumar(pd.acumulado, b);
        sumar(pd.porFamilia[fam] = pd.porFamilia[fam] || {}, b);
      }
    }
    if (maq.acumulado.msgs) porMaquina[clave] = maq;
  }

  for (const maq of Object.values(porMaquina)) {
    const alias = maq.cuenta || "sin sesión";
    const c = porCuenta[alias] = porCuenta[alias] || { alias, porFamilia: {}, acumulado: {}, maquinas: [] };
    sumar(c.acumulado, maq.acumulado);
    for (const [fam, b] of Object.entries(maq.porFamilia)) sumar(c.porFamilia[fam] = c.porFamilia[fam] || {}, b);
    c.maquinas.push(maq.clave);
  }

  const famTotales = pf => Object.fromEntries(FAMILIAS.filter(f => pf[f]).map(f => [f, totales(pf[f]).total]));
  const fila = (extra, acumulado, pf) => ({ ...extra, ...totales(acumulado), porFamilia: famTotales(pf) });
  const desc = (a, b) => b.total - a.total || (a.nombre || a.alias || a.clave).localeCompare(b.nombre || b.alias || b.clave);

  const listaDias = [];
  for (let d = desde; d <= hoy; d = diaMas(d, 1)) {
    const pd = porDia[d] || { porFamilia: {}, acumulado: {} };
    listaDias.push(fila({ dia: d }, pd.acumulado, pd.porFamilia));
  }

  return {
    desde, hasta: hoy, dias,
    ...totales(global),
    porDia: listaDias,
    porFamilia: FAMILIAS.filter(f => porFamilia[f]).map(f => ({ familia: f, ...totales(porFamilia[f]) })),
    porModelo: Object.entries(porModelo)
      .map(([id, b]) => ({ id, nombre: nombreModelo(id), familia: familiaModelo(id), ...totales(b) }))
      .sort(desc),
    porCuenta: Object.values(porCuenta).map(c => fila({ alias: c.alias, maquinas: c.maquinas.sort() }, c.acumulado, c.porFamilia)).sort(desc),
    porMaquina: Object.values(porMaquina).map(m => fila({ clave: m.clave, cuenta: m.cuenta }, m.acumulado, m.porFamilia)).sort(desc),
  };
}

// 950 → "950"; 12345 → "12 k"; 4200000 → "4,2 M"; 4.6e9 → "4.600 M". Un decimal solo bajo 10; formato es-CO.
// Por encima de mil millones se sigue en millones con separador de miles: "4.600 M" se lee sin pensar,
// "4,6 mil M" no.
function humanizarTokens(n) {
  n = Number(n) || 0;
  const f = (v, u) => v.toLocaleString("es-CO", { maximumFractionDigits: v < 10 ? 1 : 0 }) + u;
  if (n >= 1e6) return f(n / 1e6, " M");
  if (n >= 1e3) return f(n / 1e3, " k");
  return String(Math.round(n));
}

if (typeof module !== "undefined") module.exports = {
  agregar, humanizar, consumo, humanizarTokens, familiaModelo, nombreModelo, FAMILIAS, FRESCO_S, EN_USO_S,
};
