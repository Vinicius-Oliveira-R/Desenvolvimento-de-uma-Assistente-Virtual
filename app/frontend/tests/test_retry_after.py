import unittest
from datetime import datetime, timezone

from assistant.retry_after import SEM_PRAZO, mensagem_de_espera, segundos_de_espera

AGORA = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)


class RetryAfterTests(unittest.TestCase):
    def test_segundos_e_data_http(self):
        self.assertEqual(segundos_de_espera("180", AGORA), 180)
        self.assertEqual(segundos_de_espera(" 45 ", AGORA), 45)
        self.assertEqual(segundos_de_espera("Thu, 26 Nov 2026 12:02:30 GMT", AGORA), 150)

    def test_valores_que_nao_dao_prazo(self):
        for valor in (None, "", "0", "-3", "1.5", "abc", "99999999", "Thu, 26 Nov 2026 11:00:00 GMT", "２０"):
            with self.subTest(valor=valor):
                self.assertIsNone(segundos_de_espera(valor, AGORA))

    def test_mensagem_arredonda_para_cima_com_singular_e_plural(self):
        self.assertEqual(mensagem_de_espera(1), "Muitas tentativas de entrada. Tente novamente em 1 minuto.")
        self.assertEqual(mensagem_de_espera(121), "Muitas tentativas de entrada. Tente novamente em 3 minutos.")
        self.assertEqual(mensagem_de_espera(3600), "Muitas tentativas de entrada. Tente novamente em 1 hora.")
        self.assertEqual(
            mensagem_de_espera(3601), "Muitas tentativas de entrada. Tente novamente em 1 hora e 1 minuto."
        )
        self.assertEqual(mensagem_de_espera(7200), "Muitas tentativas de entrada. Tente novamente em 2 horas.")
        self.assertEqual(mensagem_de_espera(None), SEM_PRAZO)


if __name__ == "__main__":
    unittest.main()
