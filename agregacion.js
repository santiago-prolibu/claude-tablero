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
    a.alias.localeCompare(b.alias));

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
