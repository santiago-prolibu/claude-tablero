const { test } = require("node:test");
const assert = require("node:assert");
const { agregar, humanizar, EN_USO_S } = require("../agregacion.js");

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

test("maquina sin reportar hace mas de un dia no se muestra", () => {
  const e = estadoDemo();
  e.maquinas.Fantasma = { cuenta: "Gamma", ultima_actividad: null, reportado: "2026-08-09T18:00:00Z" };
  e.maquinas.Pro.reportado = "2026-08-10T17:59:59Z"; // 1 d + 1 s → fuera
  const agg = agregar(e, AHORA);
  assert.deepEqual(agg.cuentas.find(c => c.alias === "Gamma").maquinas.map(m => m.clave), ["Mini"]);
  assert.deepEqual(agg.sin_sesion, []);
});

test("el borde del dia sigue adentro", () => {
  const e = estadoDemo();
  e.maquinas.Mini.reportado = "2026-08-10T18:00:00Z"; // exactamente EN_USO_S
  assert.equal(EN_USO_S, 86400);
  const agg = agregar(e, AHORA);
  assert.deepEqual(agg.cuentas.find(c => c.alias === "Gamma").maquinas.map(m => m.clave), ["Mini"]);
});

test("cuenta que solo existia por una maquina fantasma desaparece", () => {
  const e = estadoDemo();
  e.maquinas.Viejo = { cuenta: "Zeta", ultima_actividad: null, reportado: "2026-07-20T18:00:00Z" };
  const agg = agregar(e, AHORA);
  assert.ok(!agg.cuentas.some(c => c.alias === "Zeta"));
});

test("cuenta con cupo sobrevive aunque su maquina sea fantasma", () => {
  const e = estadoDemo();
  e.maquinas.Air.reportado = "2026-07-20T18:00:00Z";
  const alpha = agregar(e, AHORA).cuentas.find(c => c.alias === "Alpha");
  assert.deepEqual(alpha.maquinas, []);
  assert.equal(alpha.cupo.cinco_horas.pct, 15); // el cupo se sigue viendo: es lo que decide qué usar
});

test("reportado ilegible queda fuera en vez de romper el render", () => {
  const e = estadoDemo();
  e.maquinas.Mini.reportado = "no es fecha";
  const agg = agregar(e, AHORA);
  assert.deepEqual(agg.cuentas.find(c => c.alias === "Gamma").maquinas, []);
});

test("humanizar", () => {
  assert.equal(humanizar(30), "hace un momento");
  assert.equal(humanizar(240), "hace 4 min");
  assert.equal(humanizar(3600 * 3 + 100), "hace 3 h");
  assert.equal(humanizar(86400 * 2 + 100), "hace 2 d");
});

test("orden por codepoint con mayúsculas y tildes", () => {
  const ahora = "2026-08-11T18:00:00Z";
  const estado = {
    version: 1,
    maquinas: {},
    cuentas: {
      delta: { cinco_horas: { pct: 50, resetea: "2026-08-11T19:00:00Z" }, semanal: { pct: 40, resetea: "2026-08-12T10:00:00Z" }, medido: "2026-08-11T17:59:00Z", por: undefined },
      Gamma: { cinco_horas: { pct: 50, resetea: "2026-08-11T19:00:00Z" }, semanal: { pct: 40, resetea: "2026-08-12T10:00:00Z" }, medido: "2026-08-11T17:59:00Z", por: undefined },
      Ángela: { cinco_horas: { pct: 50, resetea: "2026-08-11T19:00:00Z" }, semanal: { pct: 40, resetea: "2026-08-12T10:00:00Z" }, medido: "2026-08-11T17:59:00Z", por: undefined },
      zulu: { cinco_horas: { pct: 50, resetea: "2026-08-11T19:00:00Z" }, semanal: { pct: 40, resetea: "2026-08-12T10:00:00Z" }, medido: "2026-08-11T17:59:00Z", por: undefined },
    },
  };
  const agg = agregar(estado, ahora);
  const orden = agg.cuentas.map(c => c.alias);
  assert.deepEqual(orden, ["Gamma", "delta", "zulu", "Ángela"]);
});

/* ─ consumo de tokens ─ */
const { consumo, humanizarTokens, familiaModelo, nombreModelo } = require("../agregacion.js");

const B = (msgs, salida) => ({ msgs, entrada: 10, salida, cache_escr: 100, cache_lect: 1000 });

function estadoConsumo() {
  const e = estadoDemo();
  e.maquinas.Mini.consumo = { dias: {
    "2026-08-11": { "claude-opus-5": B(2, 500), "claude-fable-5-1": B(1, 50) },
    "2026-08-10": { "claude-opus-5": B(1, 20) },
    "2026-08-01": { "claude-opus-5": B(9, 9999) },  // fuera de 7 días
  } };
  e.maquinas.Air.consumo = { dias: {
    "2026-08-11": { "claude-fable-5": B(4, 400) },
    "2026-08-09": { "claude-opus-4-8": B(1, 5), "basura": null },
  } };
  // Pro: sin sesión y sin consumo publicado (versión vieja del reportero).
  return e;
}

test("consumo: ventana de 7 días, totales y desglose por tipo", () => {
  const c = consumo(estadoConsumo(), "2026-08-11", 7);
  assert.equal(c.desde, "2026-08-05");
  assert.equal(c.hasta, "2026-08-11");
  // Mini 11 (2 modelos) + Mini 10 + Air 11 + Air 09 = 5 bloques; el del 01 queda fuera.
  assert.equal(c.msgs, 2 + 1 + 1 + 4 + 1);
  assert.equal(c.salida, 500 + 50 + 20 + 400 + 5);
  assert.equal(c.entrada, 5 * 110);        // input + cache de escritura
  assert.equal(c.cache, 5 * 1000);         // cache de lectura
  assert.equal(c.total, c.entrada + c.salida + c.cache);
});

test("consumo: por modelo ordenado desc con nombre legible y familia", () => {
  const c = consumo(estadoConsumo(), "2026-08-11", 7);
  assert.deepEqual(c.porModelo.map(m => [m.id, m.nombre, m.familia, m.msgs]), [
    ["claude-opus-5", "Opus 5", "Opus", 3],
    ["claude-fable-5", "Fable 5", "Fable", 4],
    ["claude-fable-5-1", "Fable 5.1", "Fable", 1],
    ["claude-opus-4-8", "Opus 4.8", "Opus", 1],
  ]);
  assert.deepEqual(c.porFamilia.map(f => f.familia), ["Opus", "Fable"]); // orden fijo, no por tamaño
});

test("consumo: por máquina y por cuenta (la cuenta actual del compu)", () => {
  const c = consumo(estadoConsumo(), "2026-08-11", 7);
  assert.deepEqual(c.porMaquina.map(m => [m.clave, m.cuenta, m.msgs]), [["Mini", "Gamma", 4], ["Air", "Alpha", 5]]);
  // Cada bloque suma 1110 + salida. Mini: Opus (500 y 20) + Fable (50); Air: Fable (400) + Opus (5).
  assert.deepEqual(c.porMaquina[0].porFamilia, { Opus: 1610 + 1130, Fable: 1160 });
  assert.deepEqual(c.porMaquina[1].porFamilia, { Opus: 1115, Fable: 1510 });
  const gamma = c.porCuenta.find(x => x.alias === "Gamma");
  assert.deepEqual(gamma.maquinas, ["Mini"]);
  assert.equal(gamma.total, c.porMaquina[0].total);
});

test("consumo: hoy = solo el día de hoy; la serie trae todos los días aunque estén en cero", () => {
  const hoy = consumo(estadoConsumo(), "2026-08-11", 1);
  assert.equal(hoy.msgs, 2 + 1 + 4);
  assert.deepEqual(hoy.porDia.map(d => d.dia), ["2026-08-11"]);
  const sem = consumo(estadoConsumo(), "2026-08-11", 7);
  assert.deepEqual(sem.porDia.map(d => d.dia), ["2026-08-05", "2026-08-06", "2026-08-07", "2026-08-08", "2026-08-09", "2026-08-10", "2026-08-11"]);
  assert.deepEqual(sem.porDia.map(d => d.msgs), [0, 0, 0, 0, 1, 1, 7]);
  assert.deepEqual(sem.porDia[6].porFamilia, { Opus: 1610, Fable: 1160 + 1510 });
});

test("consumo: sin datos de consumo no revienta", () => {
  const c = consumo(estadoDemo(), "2026-08-11", 7);
  assert.equal(c.total, 0);
  assert.deepEqual(c.porModelo, []);
  assert.deepEqual(c.porMaquina, []);
  assert.equal(c.porDia.length, 7);
  assert.equal(consumo({}, "2026-08-11", 14).porDia.length, 14);
});

test("familia y nombre de modelo", () => {
  assert.equal(familiaModelo("claude-opus-5[1m]"), "Opus");
  assert.equal(familiaModelo("claude-haiku-4-5-20251001"), "Haiku");
  assert.equal(familiaModelo("claude-sonnet-5"), "Sonnet");
  assert.equal(familiaModelo("gpt-9"), "Otro");
  assert.equal(nombreModelo("claude-opus-5[1m]"), "Opus 5 · 1M");
  assert.equal(nombreModelo("claude-haiku-4-5-20251001"), "Haiku 4.5");
  assert.equal(nombreModelo("claude-sonnet-5"), "Sonnet 5");
  assert.equal(nombreModelo("raro"), "raro");
});

test("humanizarTokens", () => {
  assert.equal(humanizarTokens(950), "950");
  assert.equal(humanizarTokens(12345), "12 k");
  assert.equal(humanizarTokens(1234), "1,2 k");
  assert.equal(humanizarTokens(4200000), "4,2 M");
  assert.equal(humanizarTokens(119684653), "120 M");
  assert.equal(humanizarTokens(2.4e9), "2.400 M");
  assert.equal(humanizarTokens(4.6e9), "4.600 M");
  assert.equal(humanizarTokens(undefined), "0");
});
