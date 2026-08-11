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
