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


if __name__ == "__main__":
    unittest.main()
