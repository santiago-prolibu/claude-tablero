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


class TestEnUso(unittest.TestCase):
    def test_maquina_sin_reportar_hace_mas_de_un_dia_no_se_lista(self):
        e = estado_demo()
        e["maquinas"]["Fantasma"] = {"cuenta": "Gamma", "ultima_actividad": None,
                                     "reportado": "2026-08-09T18:00:00Z"}
        e["maquinas"]["Pro"]["reportado"] = "2026-08-10T17:59:59Z"  # 1 d + 1 s → fuera
        agg = cuentas.agregar(e, AHORA)
        gamma = [c for c in agg["cuentas"] if c["alias"] == "Gamma"][0]
        self.assertEqual([m["clave"] for m in gamma["maquinas"]], ["Mini"])
        self.assertEqual(agg["sin_sesion"], [])

    def test_el_borde_del_dia_sigue_adentro(self):
        e = estado_demo()
        e["maquinas"]["Mini"]["reportado"] = "2026-08-10T18:00:00Z"  # exactamente EN_USO_S
        self.assertEqual(cuentas.EN_USO_S, 86400)
        gamma = [c for c in cuentas.agregar(e, AHORA)["cuentas"] if c["alias"] == "Gamma"][0]
        self.assertEqual([m["clave"] for m in gamma["maquinas"]], ["Mini"])

    def test_cuenta_que_solo_existia_por_maquina_fantasma_desaparece(self):
        e = estado_demo()
        e["maquinas"]["Viejo"] = {"cuenta": "Zeta", "ultima_actividad": None,
                                  "reportado": "2026-07-20T18:00:00Z"}
        agg = cuentas.agregar(e, AHORA)
        self.assertNotIn("Zeta", [c["alias"] for c in agg["cuentas"]])

    def test_cuenta_con_cupo_sobrevive_aunque_su_maquina_sea_fantasma(self):
        e = estado_demo()
        e["maquinas"]["Air"]["reportado"] = "2026-07-20T18:00:00Z"
        alpha = [c for c in cuentas.agregar(e, AHORA)["cuentas"] if c["alias"] == "Alpha"][0]
        self.assertEqual(alpha["maquinas"], [])
        self.assertEqual(alpha["cupo"]["cinco_horas"]["pct"], 15)  # el cupo decide qué usar: se conserva

    def test_reportado_ilegible_queda_fuera_en_vez_de_romper_el_render(self):
        e = estado_demo()
        e["maquinas"]["Mini"]["reportado"] = "no es fecha"
        agg = cuentas.agregar(e, AHORA)
        gamma = [c for c in agg["cuentas"] if c["alias"] == "Gamma"][0]
        self.assertEqual(gamma["maquinas"], [])
        cuentas.render(agg, AHORA)  # antes reventaba con ValueError


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

    def test_render_fable_solo_si_la_cuenta_lo_tiene(self):
        estado = estado_demo()
        estado["cuentas"]["Gamma"]["modelos"] = {"Fable": {"pct": 39, "resetea": None}}
        salida = cuentas.render(cuentas.agregar(estado, AHORA), AHORA)
        gamma = next(l for l in salida.splitlines() if "Gamma" in l)
        alpha = next(l for l in salida.splitlines() if "Alpha" in l)
        self.assertIn("fab ████░░░░░░  39%", gamma)
        self.assertNotIn("fab", alpha)

    def test_render_sin_dato(self):
        agg = cuentas.agregar({"maquinas": {}, "cuentas": {}}, AHORA)
        self.assertIn("Sin dato de cupo", cuentas.render(agg, AHORA))


class TestSesionNoReportada(unittest.TestCase):
    def _estado(self):
        return {"maquinas": {}, "cuentas": {
            "Alpha": {"cinco_horas": {"pct": 0, "resetea": None, "no_reportado": True},
                      "semanal": {"pct": 11, "resetea": "2026-08-14T13:00:00Z"},
                      "medido": "2026-08-11T17:59:00Z"},
            "Zeta": {"cinco_horas": {"pct": 4, "resetea": "2026-08-11T19:00:00Z"},
                     "semanal": {"pct": 2, "resetea": "2026-08-14T13:00:00Z"},
                     "medido": "2026-08-11T17:59:00Z"}}}

    def test_el_score_sale_del_semanal(self):
        agregado = cuentas.agregar(self._estado(), AHORA)
        alpha = next(c for c in agregado["cuentas"] if c["alias"] == "Alpha")
        self.assertEqual(alpha["score"], 11)
        self.assertEqual(agregado["recomendada"]["alias"], "Zeta")

    def test_en_un_empate_gana_la_sesion_medida(self):
        estado = self._estado()
        estado["cuentas"]["Zeta"]["semanal"]["pct"] = 11
        estado["cuentas"]["Zeta"]["cinco_horas"]["pct"] = 5
        self.assertEqual(cuentas.agregar(estado, AHORA)["recomendada"]["alias"], "Zeta")

    def test_las_columnas_quedan_alineadas(self):
        filas = cuentas.render(cuentas.agregar(self._estado(), AHORA), AHORA).splitlines()
        alpha = next(f for f in filas if "Alpha" in f)
        zeta = next(f for f in filas if "Zeta" in f)
        self.assertEqual(alpha.index(" sem "), zeta.index(" sem "))

    def test_render_no_pinta_un_cero_falso(self):
        filas = cuentas.render(cuentas.agregar(self._estado(), AHORA), AHORA).splitlines()
        alpha = next(f for f in filas if "Alpha" in f)
        self.assertIn("5h no reportado", alpha)
        self.assertNotIn("0%  sem", alpha)
        self.assertIn(" 11%", alpha)
        self.assertIn("4%", next(f for f in filas if "Zeta" in f))


if __name__ == "__main__":
    unittest.main()
