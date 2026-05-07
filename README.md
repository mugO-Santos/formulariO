# FormulariO — Gestão de Pacientes

> Sistema web para gerenciamento de dados de pacientes com formulário público, painel administrativo e controle de acesso por níveis.

---

## Objetivo Geral

O link do formulário é enviado ao paciente, que preenche os dados obrigatórios e aceita o Termo LGPD. Ao enviar, um Perfil é criado automaticamente no sistema, ficando disponível para visualização, edição e exportação em PDF pela equipe interna.

---

## Stack

| Camada | Tecnologia |
|---|---|
| Backend | Python 3.13 · Flask 3.1 · SQLAlchemy 2.0 |
| Frontend | Jinja2 · CSS puro · JavaScript puro |
| Banco local | SQLite |
| Banco produção | PostgreSQL (Neon) via pg8000 |
| Deploy | Railway · Gunicorn |
| PDF | WeasyPrint |
| Busca fuzzy | rapidfuzz |

---

## Funcionalidades

- **Formulário público** com lookup de CEP automático e modal de aceite LGPD obrigatório
- **Perfil do Paciente** gerado automaticamente com dados pessoais, médico vinculado e campo de observações
- **Triagem / Pacientes** — perfis recém-cadastrados ficam na tela inicial (Início) para análise; ao clicar em **Concluído** o perfil é movido para a aba **Pacientes**, separando quem já foi atendido de quem ainda está pendente. A ação pode ser desfeita via botão "Reabrir"
- **Exportação PDF** com todos os dados do perfil
- **Busca fuzzy de médicos** — reconhece variações de nome (acentos, maiúsculas, abreviações)
- **Exclusão suave** — perfis excluídos ficam retidos por 60 dias antes da remoção definitiva (recuperável pelo Nível 0)
- **Logs de auditoria** — registra login, leitura, edição (data, hora e usuário)
- **Notificações internas** — pedidos de redefinição de senha alertam o ADMIN e a Gestão
- **Admin inicial** criado automaticamente via variáveis de ambiente

---

## Níveis de Acesso

| Nível | Cargo | Permissões |
|---|---|---|
| 0 | ADMIN | Tudo + recuperar perfis excluídos |
| 1 | Gestão | Criar/excluir usuários, editar/excluir pacientes, logs, PDF |
| 2 | Recepção | Visualizar/editar perfil, PDF |

---

## Variáveis de Ambiente

| Variável | Descrição |
|---|---|
| `SECRET_KEY` | Chave secreta Flask |
| `DATABASE_URL` | URL do banco PostgreSQL (Neon) |
| `ADMIN_USER` | Login do admin inicial |
| `ADMIN_PASS` | Senha do admin inicial |
| `DB_POOL_RECYCLE` | Segundos para reciclar conexões ociosas do pool (padrão: 300) |
| `DB_POOL_TIMEOUT` | Tempo máximo para aguardar conexão do pool (padrão: 30) |

---

## Rodando Localmente

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
# Copie .env.example para .env e ajuste os valores
python run.py
```

Acesse `http://localhost:5000` — login padrão: `admin` / `admin123` (conforme `.env`).

---

## Estrutura

```
app/
├── __init__.py          # Factory da aplicação
├── models.py            # Cargo, Usuario, Medico, Paciente, Log, Notificacao
├── extensions.py        # SQLAlchemy, LoginManager
├── decorators.py        # @nivel_minimo(n)
├── fuzzy.py             # Busca fuzzy de médicos (rapidfuzz)
├── routes/
│   ├── formulario.py    # Formulário público
│   ├── auth.py          # Login / logout / esqueci-senha
│   ├── painel.py        # Dashboard, perfil, PDF
│   ├── medicos.py       # CRUD de médicos
│   ├── usuarios.py      # Gestão de usuários
│   └── logs.py          # Visualização de logs
├── templates/
└── static/
run.py                   # Entry point
Procfile                 # gunicorn run:app
requirements.txt
```

---

## Observações

- Senhas armazenadas com hash seguro (Werkzeug `generate_password_hash`)
- "Esqueci minha senha" não redefine automaticamente — gera notificação interna para o responsável criar um novo login
- Médicos são entidade separada dos Usuários (não fazem login)
- O aceite do Termo LGPD fica registrado no perfil com data e hora (visível ao Nível 0)
- Em produção (Railway), o PDF depende de bibliotecas nativas do WeasyPrint. O arquivo `nixpacks.toml` já inclui os pacotes Linux necessários para evitar erro na geração de PDF.

### Railway e PDF (WeasyPrint)

Se aparecer a mensagem "Não foi possível gerar PDF neste ambiente", confirme que o deploy está usando o arquivo `nixpacks.toml` da raiz e faça um novo deploy.


## PÁGINAS

## Formulário
1. Layout simples em formato de cartão de visita A4
2. Div com Box de aceite do Termo LGPD no final do formulário
3. Div com Endereço da Clínica e link do Maps depois do Termo LGPD
    1. Endereço: Av. São João, 1522 - Jardim Esplanada, São José dos Campos - SP, 12242-840
4. Header fino horizontal com botão Área de Login — hidden, visível somente ao passar o mouse
5. Footer elegante, sem background, © 2026 Todos os direitos reservados a '<mugO Santos>'
6. Dados do Formulário
    1. Nome Paciente
    2. Nome da Mãe
    3. CPF
    4. RG
    5. Data de Nascimento
    6. Estado Civil
        1. Casado
        2. Solteiro
        3. Divorciado
        4. Viúvo
7. Profissão
8. E-mail
9. Telefone
10. CEP (com lupa de pesquisa para preencher os campos de endereço automaticamente)
11. Endereço
12. N°
13. Bairro
14. Cidade
15. Nome do Médico

## Área de Login
- Background Azul Hospitalar
- DIV background branco com solicitação de Login e Senha
    * Senha com opção de visualização
    * Esqueci minha senha
        * Envia notificação interna ao ADMIN e à Gestão — não redefine senha automaticamente

## ADMIN
- Layout moderno
- Cabeçalho com menu visual
    - Perfil (pop-up): visualizar senha atual e definir Nova Senha
    - Usuários (pop-up)
        * Lista com usuários ativos com opção de Exclusão
        * Novo Usuário
        * Novo Cargo
    - Médicos (pop-up)
        * Lista de Médicos no BD
        * Add Novo Médico, CRM (alfanumérico), obrigatório
        * Editar Médico
        * Quantidade de pacientes registrados
    - Logout

## RECEPÇÃO
- Layout moderno
- Cabeçalho com menu visual
    - Logout

## GESTÃO
- Layout moderno
- Cabeçalho com menu visual
    - Perfil (pop-up): visualizar senha atual e definir Nova Senha
    - Usuários (pop-up)
        * Lista com usuários ativos com opção de Exclusão
        * Novo Usuário
        * Novo Cargo
    - Médicos (pop-up)
        * Lista de Médicos no BD
        * Add Novo Médico, CRM (alfanumérico), obrigatório
        * Editar Médico
        * Quantidade de pacientes registrados
    - Logout

### VISÃO GERAL
Todos os perfis logados terão o mesmo design: uma lista de pacientes separados por médico, mostrando o nome do paciente e a opção Ver Perfil.
Ao clicar em Ver Perfil, será aberta uma nova aba com o Perfil do Paciente, exibindo todos os dados e a opção de imprimir em PDF (todos os dados do perfil). Todos os níveis podem visualizar e editar o campo de Observações — alterações ficam registradas no Log.

## Logs
- Página exclusiva para Nível 0 e Nível 1
- Registra: login de usuários, leitura de perfis, edições de dados e edições do campo Observações
- Cada entrada exibe: usuário responsável, ação realizada, data e horário


## Layout


- Cores Gerais:
    - Branco e Azul Hospitalar

---

## Licença

© 2026 Todos os direitos reservados a `<mugO Santos>`
