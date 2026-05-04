# Formulário Online — Gestão de Pacientes

> Sistema web para gerenciamento de dados de pacientes com formulário público, painel administrativo e controle de acesso por níveis.

---

## Objetivo Geral

Sistema para gerenciamento de dados de pacientes, o link do formulário é enviado ao paciente, o mesmo preenchera os dados obrigatórios, aceitara o termo LGPD para uso dos dados para fins hospitalares. Ao final do preenchimento e aceite do termo, o paciente clica em enviar formulário, internamente um Perfil com os dados desse paciente é criado automaticamente, ficando disponível para visualização, edição e exportação em PDF.


## VISÃO GERAL

- Backend em Flask com SQLAlchemy.
- Frontend server-side com Jinja2, CSS e JavaScript puro.
- Banco principal via SQLAlchemy (SQLite por padrão, com suporte a DATABASE_URL).


## PRINCIPAIS FUNCIONALIDADES

1. Conta ADMIN principal criada a partir de VARIABLE com acesso a todas as funções
2. Criação de Perfil do Paciente criado a partir dos dados fornecidos pelo mesmo através do formulário principal
3. Acesso ADMIN:
    1. Exclusão de Perfil de paciente (Todo perfil de paciente excluído ficará em êxtase por 60 dias, até a exclusão definitiva)
    2. Recuperação de Perfil de paciente excluído dentro do prazo de 60 dias (exclusivo do ADMIN Nível 0)
    3. Criação de Login para novos Usuários (Com nível de acesso)
4. Perfil consolidado do Paciente com histórico, dados pessoais e campo para observações
    - Edições no campo de Observações ficam registradas no Log (data, horário e usuário responsável)
5. Exportação de todos os dados do Perfil do Paciente em PDF
6. Lista interna com nome de Médicos e CRM (entidade separada dos Usuários do sistema)
7. Logs, registrando login, quem leu o que, quem editou o que e quando o fez — visualizável pelos Níveis 0 e 1
8. Criar novos Perfis de Usuários


## NÍVEIS DE ACESSO

- ADMIN Nível 0:
    - Todas as ações de Gestão e Recepção
    - Recuperar Perfil de Paciente excluído (dentro do prazo de 60 dias)
- Gestão Nível 1:
    - Criar ou Excluir Usuários
    - Excluir ou Editar dados de Pacientes
    - Visualizar Logs de Ações
    - Imprimir dados do Paciente em PDF (todos os dados do perfil)
- Recepção Nível 2:
    - Visualizar ou Editar Perfil do Paciente
    - Imprimir dados do Paciente em PDF (todos os dados do perfil)


## AUTENTICAÇÃO E SENHAS

- Login por nome e senha
- Senhas armazenadas com hash seguro (Werkzeug)


## OBSERVAÇÕES

- Login e senha
    - Login: Nome curto
    - Senha: Senha forte de no mínimo 6 dígitos (Numérico ou Alfanumérico)
- Criação de Usuários:
    - Para que o Admin crie um novo usuário, ele deve fornecer Nome, Senha e Cargo (Gestão ou Recepção)
- Admin pode criar novos Cargos, definindo o Nível de acesso (níveis 0, 1 e 2)
- Lista de Médicos
    - Lista interna com nome de Médicos e seu CRM
        * Médicos são uma entidade separada dos Usuários do sistema. Usuários fazem login; Médicos são referências vinculadas ao perfil do paciente.
        * Paciente preenche o nome do médico no formulário e o sistema busca no banco o médico mais próximo, associando o Perfil do paciente a esse médico e separando os pacientes por médico.
        * O sistema deve reconhecer a string de várias formas, ignorando acentos e diferenças de maiúscula/minúscula (busca fuzzy). Exemplo:
            - Banco de Dados: Dr Waldecyr Castro
            - Sistema recebe: Waldeci, DR WALDECI, dr waldecir, dr Waldecyr Castro
        * Caso nenhum médico seja encontrado, o sistema alerta o usuário — o perfil é criado sem vínculo com médico até que seja corrigido manualmente.
- O paciente só pode enviar o formulário depois de aceitar o Termo de Uso de Dados conforme LGPD
- O aceite do Termo LGPD fica registrado no perfil do paciente com data e horário do preenchimento (visível ao Nível 0)
- O conteúdo do Termo LGPD é um texto fixo configurado no sistema
- Esqueci minha senha:
    - Não redefine a senha automaticamente
    - Envia uma notificação interna ao ADMIN e à Gestão
    - O responsável exclui o perfil atual e cria um novo com nova senha


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
