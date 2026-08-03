import os
import unittest

from app import create_app
from app.models import Paciente


class FormularioConvenioTestCase(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("SECRET_KEY", "test-secret")
        os.environ["DATABASE_URL"] = "sqlite:///:memory:"
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def test_formulario_salva_pagamento_e_aceita_particular_sem_detalhes(self):
        payload = {
            "nome": "Maria Silva",
            "nome_mae": "Ana Silva",
            "cpf": "123.456.789-09",
            "rg": "12345678",
            "data_nascimento": "1990-01-02",
            "estado_civil": "Solteiro",
            "email": "maria@example.com",
            "telefone": "(12) 99999-0000",
            "cep": "12242-840",
            "endereco": "Av. São João",
            "numero": "1522",
            "bairro": "Jardim Esplanada",
            "cidade": "São José dos Campos",
            "convenio_tipo": "Particular",
            "forma_pagamento": "Pix",
            "aceite_lgpd": "1",
        }

        response = self.client.post("/formulario", data=payload, follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            paciente = Paciente.query.order_by(Paciente.id.desc()).first()
        self.assertIsNotNone(paciente)
        self.assertIsNone(paciente.convenio_nome)
        self.assertIsNone(paciente.convenio_numero)
        self.assertEqual(paciente.forma_pagamento, "Pix")


if __name__ == "__main__":
    unittest.main()
