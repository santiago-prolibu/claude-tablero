import json, os, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

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


class TestPurga(unittest.TestCase):
    AHORA = "2026-08-11T18:00:00Z"

    def _previo(self, reportado, medido):
        return {"version": 1,
                "maquinas": {"Fantasma": {"cuenta": "Alpha", "ultima_actividad": None,
                                          "reportado": reportado}},
                "cuentas": {"Alpha": {"cinco_horas": {"pct": 10, "resetea": None},
                                      "semanal": {"pct": 5, "resetea": None},
                                      "medido": medido, "por": "Fantasma"}}}

    def test_borra_maquina_y_cuenta_de_hace_mas_de_una_semana(self):
        previo = self._previo("2026-08-04T17:59:59Z", "2026-08-04T17:59:59Z")
        estado = reportar.fusionar(previo, "Mini", "Gamma", None, None, self.AHORA)
        self.assertNotIn("Fantasma", estado["maquinas"])
        self.assertNotIn("Alpha", estado["cuentas"])
        self.assertIn("Mini", estado["maquinas"])

    def test_el_borde_de_la_semana_se_conserva(self):
        previo = self._previo("2026-08-04T18:00:00Z", "2026-08-04T18:00:00Z")
        estado = reportar.fusionar(previo, "Mini", "Gamma", None, None, self.AHORA)
        self.assertIn("Fantasma", estado["maquinas"])
        self.assertIn("Alpha", estado["cuentas"])

    def test_nunca_purga_el_reporte_propio(self):
        previo = self._previo("2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
        cupo = {"cinco_horas": {"pct": 1, "resetea": None}, "semanal": {"pct": 2, "resetea": None}}
        estado = reportar.fusionar(previo, "Mini", "Gamma", None, cupo, self.AHORA)
        self.assertIn("Mini", estado["maquinas"])
        self.assertIn("Gamma", estado["cuentas"])

    def test_fecha_ilegible_o_ausente_se_conserva(self):
        # Al escribir se conserva ante la duda: borrar del gist no tiene vuelta atrás.
        previo = self._previo("no es fecha", None)
        del previo["cuentas"]["Alpha"]["medido"]
        estado = reportar.fusionar(previo, "Mini", "Gamma", None, None, self.AHORA)
        self.assertIn("Fantasma", estado["maquinas"])
        self.assertIn("Alpha", estado["cuentas"])


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

    def _sin_sesion(self):
        p = Path(__file__).parent / "fixtures" / "uso_sin_sesion.json"
        return json.loads(p.read_text())

    def test_sin_limite_de_sesion_conserva_semanal_y_fable(self):
        # Respuesta real (nov 2026): `five_hour: null` y sin `session` en `limits`.
        cupo = reportar.parsear_cupo(self._sin_sesion())
        self.assertEqual(cupo["semanal"]["pct"], 11)
        self.assertEqual(cupo["modelos"]["Fable"]["pct"], 5)

    def test_sin_limite_de_sesion_marca_la_ventana(self):
        # La ventana sigue existiendo con pct numerico: el gist es compartido y los `cuentas` y
        # las pestanas ya instalados leen `cinco_horas.pct` sin proteger.
        cupo = reportar.parsear_cupo(self._sin_sesion())
        self.assertEqual(cupo["cinco_horas"], {"pct": 0, "resetea": None, "no_reportado": True})

    def test_clave_five_hour_ausente_no_se_confunde_con_no_reportada(self):
        # Solo el null observado significa «no reportado». Si la API renombra el campo, la respuesta
        # es ilegible y queda en el log: tomarla por «sin sesión» escondería el cambio.
        uso = self._sin_sesion()
        del uso["five_hour"]
        self.assertIsNone(reportar.parsear_cupo(uso))

    def test_con_limite_de_sesion_no_lleva_la_marca(self):
        self.assertNotIn("no_reportado", reportar.parsear_cupo(self._fixture())["cinco_horas"])

    def test_ventanas_malformadas_siguen_dando_none(self):
        uso = self._sin_sesion()
        uso["five_hour"] = {}
        self.assertIsNone(reportar.parsear_cupo(uso))
        self.assertIsNone(reportar.parsear_cupo({"five_hour": None, "seven_day": None}))
        self.assertIsNone(reportar.parsear_cupo({"five_hour": None}))

    def test_limite_semanal_de_fable(self):
        # El fixture trae un `weekly_scoped` con scope.model.display_name = Fable al 17 %.
        cupo = reportar.parsear_cupo(self._fixture())
        self.assertEqual(cupo["modelos"]["Fable"]["pct"], 17)
        self.assertTrue(cupo["modelos"]["Fable"]["resetea"].startswith("2026-08-18"))

    def test_sin_limites_por_modelo_no_agrega_la_clave(self):
        uso = self._fixture()
        uso["limits"] = [l for l in uso["limits"] if l["kind"] != "weekly_scoped"]
        self.assertNotIn("modelos", reportar.parsear_cupo(uso))
        uso["limits"] = None
        self.assertNotIn("modelos", reportar.parsear_cupo(uso))

    def test_limite_malformado_no_tumba_el_cupo(self):
        uso = self._fixture()
        uso["limits"].append({"kind": "weekly_scoped", "scope": None, "percent": "x"})
        uso["limits"].append({"kind": "weekly_scoped", "scope": {"model": {"display_name": "Sonnet"}}, "percent": 42.4})
        cupo = reportar.parsear_cupo(uso)
        self.assertEqual(cupo["modelos"], {
            "Fable": {"pct": 17, "resetea": "2026-08-18T03:59:59.048890+00:00"},
            "Sonnet": {"pct": 42, "resetea": None}})


def _linea(modelo, uso, ts="2026-08-11T15:00:00.000Z", mid="msg_1", tipo="assistant"):
    return json.dumps({"type": tipo, "timestamp": ts, "requestId": "req_" + mid,
                       "message": {"id": mid, "model": modelo, "usage": uso}})


USO = {"input_tokens": 10, "output_tokens": 100, "cache_creation_input_tokens": 1000,
       "cache_read_input_tokens": 10000}
AHORA = reportar.datetime(2026, 8, 11, 18, 0, tzinfo=reportar.timezone.utc)
UTC = reportar.timezone.utc


class TestConsumoTokens(unittest.TestCase):
    def _escribir(self, tmp, rel, lineas, mtime=None):
        p = Path(tmp) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(lineas) + "\n")
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p

    def test_suma_por_dia_y_modelo_y_cuenta_mensajes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._escribir(tmp, "p/a.jsonl", [
                _linea("claude-opus-5", USO, mid="m1"),
                _linea("claude-fable-5-1", USO, mid="m2"),
                _linea("claude-opus-5", USO, ts="2026-08-10T15:00:00Z", mid="m3"),
                json.dumps({"type": "user", "timestamp": "2026-08-11T15:00:01Z", "message": {"role": "user"}}),
            ])
            c = reportar.consumo_tokens(tmp, AHORA, tz=UTC)
            self.assertEqual(sorted(c), ["2026-08-10", "2026-08-11"])
            self.assertEqual(c["2026-08-11"]["claude-opus-5"],
                             {"msgs": 1, "entrada": 10, "salida": 100, "cache_escr": 1000, "cache_lect": 10000})
            self.assertEqual(c["2026-08-11"]["claude-fable-5-1"]["msgs"], 1)
            self.assertEqual(c["2026-08-10"]["claude-opus-5"]["msgs"], 1)

    def test_por_message_id_manda_la_ultima_linea(self):
        # Claude Code escribe una línea por bloque; las primeras traen output_tokens provisional.
        with tempfile.TemporaryDirectory() as tmp:
            self._escribir(tmp, "p/a.jsonl", [
                _linea("claude-opus-5", {**USO, "output_tokens": 3}, mid="m1"),
                _linea("claude-opus-5", {**USO, "output_tokens": 3}, mid="m1"),
                _linea("claude-opus-5", {**USO, "output_tokens": 561}, mid="m1"),
            ])
            b = reportar.consumo_tokens(tmp, AHORA, tz=UTC)["2026-08-11"]["claude-opus-5"]
            self.assertEqual((b["msgs"], b["salida"], b["cache_escr"]), (1, 561, 1000))

    def test_ignora_synthetic_sin_usage_y_basura(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._escribir(tmp, "p/a.jsonl", [
                _linea("<synthetic>", USO, mid="m1"),
                json.dumps({"type": "assistant", "timestamp": "2026-08-11T15:00:00Z",
                            "message": {"id": "m2", "model": "claude-opus-5"}}),
                json.dumps({"type": "assistant", "timestamp": "2026-08-11T15:00:00Z",
                            "message": {"id": "m3", "model": "claude-opus-5", "usage": {"output_tokens": "raro"}}}),
                "esto no es json {",
                _linea("claude-opus-5", USO, mid="m4", tipo="user"),
            ])
            c = reportar.consumo_tokens(tmp, AHORA, tz=UTC)
            # m3 cuenta como mensaje pero sus campos ilegibles suman 0.
            self.assertEqual(c, {"2026-08-11": {"claude-opus-5": {
                "msgs": 1, "entrada": 0, "salida": 0, "cache_escr": 0, "cache_lect": 0}}})

    def test_incluye_subagentes_y_salta_archivos_viejos_sin_abrirlos(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._escribir(tmp, "p/s1/subagents/agent-x.jsonl", [_linea("claude-fable-5", USO, mid="m1")])
            viejo = (AHORA - reportar.timedelta(days=reportar.CONSUMO_DIAS + 1)).timestamp()
            # mtime viejo pero con una línea "de hoy": no se abre, así que no cuenta.
            self._escribir(tmp, "p/viejo.jsonl", [_linea("claude-opus-5", USO, mid="m2")], mtime=viejo)
            c = reportar.consumo_tokens(tmp, AHORA, tz=UTC)
            self.assertEqual(list(c["2026-08-11"]), ["claude-fable-5"])

    def test_fuera_de_ventana_por_timestamp_no_cuenta(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._escribir(tmp, "p/a.jsonl", [
                _linea("claude-opus-5", USO, ts="2026-07-01T15:00:00Z", mid="m1"),
                _linea("claude-opus-5", USO, ts="sin-fecha", mid="m2"),
                _linea("claude-opus-5", USO, mid="m3"),
            ])
            c = reportar.consumo_tokens(tmp, AHORA, tz=UTC)
            self.assertEqual(c["2026-08-11"]["claude-opus-5"]["msgs"], 1)
            self.assertEqual(len(c), 1)

    def test_dia_en_zona_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            # 02:00Z del 12 es todavía el 11 en Bogotá (UTC-5).
            self._escribir(tmp, "p/a.jsonl", [_linea("claude-opus-5", USO, ts="2026-08-12T02:00:00Z")])
            bogota = reportar.timezone(reportar.timedelta(hours=-5))
            self.assertEqual(list(reportar.consumo_tokens(tmp, AHORA, tz=bogota)), ["2026-08-11"])
            self.assertEqual(list(reportar.consumo_tokens(tmp, AHORA, tz=UTC)), ["2026-08-12"])

    def test_dir_inexistente_devuelve_vacio(self):
        self.assertEqual(reportar.consumo_tokens("/no/existe", AHORA, tz=UTC), {})


class TestFusionarConsumo(unittest.TestCase):
    def test_guarda_consumo_en_la_maquina_y_lo_omite_si_none(self):
        consumo = {"2026-08-11": {"claude-opus-5": {"msgs": 1, "entrada": 1, "salida": 2, "cache_escr": 3, "cache_lect": 4}}}
        e = reportar.fusionar({}, "Mini", "Gamma", None, None, "2026-08-11T18:00:00Z", consumo)
        self.assertEqual(e["maquinas"]["Mini"]["consumo"], {"dias": consumo})
        e = reportar.fusionar(e, "Otro", None, None, None, "2026-08-11T18:00:00Z")
        self.assertNotIn("consumo", e["maquinas"]["Otro"])
        self.assertEqual(e["maquinas"]["Mini"]["consumo"], {"dias": consumo})  # no pisa a los demás


class TestMainRegistraCupoIlegible(unittest.TestCase):
    def _correr(self, uso, cupo, cuenta="Alpha"):
        reporte = ("Mini", cuenta, None, cupo, {})
        with mock.patch.object(reportar, "leer_token_anthropic", return_value="t"), \
                mock.patch.object(reportar, "consultar_uso", return_value=uso), \
                mock.patch.object(reportar, "armar_reporte", return_value=reporte), \
                mock.patch.object(reportar, "gist_get", return_value={}), \
                mock.patch.object(reportar, "gist_patch"), \
                mock.patch.object(reportar.TOKEN_PATH.__class__, "exists", return_value=True), \
                mock.patch.object(reportar.TOKEN_PATH.__class__, "read_text", return_value="{}"), \
                mock.patch.object(reportar, "_log") as log:
            reportar.main()
        return [c.args[0] for c in log.call_args_list]

    def test_respuesta_sin_cupo_legible_deja_el_motivo_en_el_log(self):
        lineas = self._correr({"seven_day": None, "limits": [], "otra": None}, None)
        self.assertTrue(any(l.startswith("uso sin cupo legible") and "limits" in l for l in lineas), lineas)

    def test_respuesta_que_no_es_objeto_no_tumba_el_reporte(self):
        lineas = self._correr(["x"], None)
        self.assertTrue(any(l.startswith("uso sin cupo legible") for l in lineas), lineas)
        self.assertTrue(any(l.startswith("ok ") for l in lineas), lineas)

    def test_sin_sesion_local_no_acusa_a_la_api(self):
        lineas = self._correr({"seven_day": {}}, None, cuenta=None)
        self.assertFalse(any("sin cupo" in l for l in lineas), lineas)

    def test_cupo_legible_no_agrega_ruido(self):
        lineas = self._correr({"seven_day": {}}, {"semanal": {"pct": 1}})
        self.assertFalse(any("sin cupo" in l for l in lineas), lineas)


class TestArmarReporte(unittest.TestCase):
    def test_integra_colectores_sin_tocar_red(self):
        with tempfile.TemporaryDirectory() as tmp:
            cj = {"oauthAccount": {"displayName": "Gamma"}}
            uso = json.loads((Path(__file__).parent / "fixtures" / "uso_real.json").read_text())
            clave, cuenta, actividad, cupo, consumo = reportar.armar_reporte(
                cj, tmp, "Mini", "mini", uso, "2026-08-11T18:00:00Z")
            self.assertEqual(clave, "Mini")
            self.assertEqual(cuenta, "Gamma")
            self.assertIsNone(actividad)
            self.assertIsInstance(cupo["cinco_horas"]["pct"], int)
            self.assertEqual(consumo, {})

    def test_deslogueado_y_sin_uso(self):
        with tempfile.TemporaryDirectory() as tmp:
            clave, cuenta, actividad, cupo, consumo = reportar.armar_reporte(
                {}, tmp, None, "mini", None, "2026-08-11T18:00:00Z")
            self.assertEqual(clave, "mini")
            self.assertIsNone(cuenta)
            self.assertIsNone(cupo)
            self.assertEqual(consumo, {})


if __name__ == "__main__":
    unittest.main()
