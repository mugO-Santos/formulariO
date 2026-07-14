from datetime import date, datetime, timezone
import uuid
from flask import Blueprint, current_app, render_template, request, flash, redirect, url_for
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError, SQLAlchemyError
from app.extensions import db
from app.models import Paciente, Log
from app.fuzzy import buscar_medico

bp = Blueprint("formulario", __name__)


def _validar_campos_obrigatorios(form_data):
    campos_obrigatorios = {
        "nome": "Nome do Paciente",
        "nome_mae": "Nome da Mãe",
        "cpf": "CPF",
        "rg": "RG",
        "data_nascimento": "Data de Nascimento",
        "estado_civil": "Estado Civil",
        "email": "E-mail",
        "telefone": "Telefone",
        "cep": "CEP",
        "endereco": "Endereço",
        "numero": "Número",
        "bairro": "Bairro",
        "cidade": "Cidade",
    }

    for campo, label in campos_obrigatorios.items():
        valor = (form_data.get(campo, "") or "").strip()
        if not valor:
            raise ValueError(f"O campo '{label}' é obrigatório.")

    if not form_data.get("aceite_lgpd"):
        raise ValueError("Você precisa aceitar o termo LGPD para continuar.")


def _validar_tamanhos_campos(form_data):
    labels = {
        "nome": "Nome do Paciente",
        "nome_mae": "Nome da Mãe",
        "cpf": "CPF",
        "rg": "RG",
        "estado_civil": "Estado Civil",
        "profissao": "Profissão",
        "email": "E-mail",
        "telefone": "Telefone",
        "cep": "CEP",
        "endereco": "Endereço",
        "numero": "Número",
        "bairro": "Bairro",
        "cidade": "Cidade",
        "convenio_nome": "Convênio",
        "convenio_numero": "N° da carteirinha",
        "indicacao": "Indicação",
    }

    for campo, label in labels.items():
        valor = (form_data.get(campo, "") or "").strip()
        if not valor:
            continue
        coluna = Paciente.__table__.columns.get(campo)
        limite = getattr(getattr(coluna, "type", None), "length", None)
        if limite and len(valor) > limite:
            raise ValueError(f"O campo '{label}' aceita no máximo {limite} caracteres.")

    nome_medico = (form_data.get("nome_medico", "") or "").strip()
    limite_nome_medico = getattr(Paciente.__table__.columns.nome_medico_digitado.type, "length", None)
    if nome_medico and limite_nome_medico and len(nome_medico) > limite_nome_medico:
        raise ValueError(
            f"O campo 'Médico' aceita no máximo {limite_nome_medico} caracteres."
        )


def _montar_paciente(form_data, medico, clinica_id=None):
    nome = form_data.get("nome", "").strip() or "Não informado"
    nome_mae = form_data.get("nome_mae", "").strip() or "Não informado"
    cpf = form_data.get("cpf", "").strip()
    if not cpf:
        cpf = f"P{uuid.uuid4().hex[:13]}"
    telefone = form_data.get("telefone", "").strip() or "Não informado"
    estado_civil = form_data.get("estado_civil", "").strip() or "Não informado"
    data_nascimento_raw = form_data.get("data_nascimento", "").strip()
    if data_nascimento_raw:
        try:
            data_nascimento = datetime.strptime(data_nascimento_raw, "%Y-%m-%d").date()
        except ValueError:
            data_nascimento = date(1900, 1, 1)
    else:
        data_nascimento = date(1900, 1, 1)

    convenio_validade_raw = form_data.get("convenio_validade", "").strip()
    if convenio_validade_raw:
        try:
            convenio_validade = datetime.strptime(convenio_validade_raw, "%Y-%m-%d").date()
        except ValueError:
            convenio_validade = None
    else:
        convenio_validade = None

    nome_medico = form_data.get("nome_medico", "").strip()
    return Paciente(
        nome=nome,
        nome_mae=nome_mae,
        cpf=cpf,
        rg=form_data.get("rg", "").strip() or None,
        data_nascimento=data_nascimento,
        estado_civil=estado_civil,
        profissao=form_data.get("profissao", "").strip() or None,
        email=form_data.get("email", "").strip() or None,
        telefone=telefone,
        cep=form_data.get("cep", "").strip() or None,
        endereco=form_data.get("endereco", "").strip() or None,
        numero=form_data.get("numero", "").strip() or None,
        bairro=form_data.get("bairro", "").strip() or None,
        cidade=form_data.get("cidade", "").strip() or None,
        convenio_nome=form_data.get("convenio_nome", "").strip() or None,
        convenio_numero=form_data.get("convenio_numero", "").strip() or None,
        convenio_validade=convenio_validade,
        indicacao=form_data.get("indicacao", "").strip() or None,
        medico_id=medico.id if medico else None,
        clinica_id=medico.clinica_id if medico else clinica_id,
        nome_medico_digitado=nome_medico or None,
        aceite_lgpd=bool(form_data.get("aceite_lgpd")),
        aceite_lgpd_em=datetime.now(timezone.utc) if form_data.get("aceite_lgpd") else None,
    )


def _salvar_formulario(form_data, *, usuario_id=None, clinica_id=None, acao="Perfil criado via formulário público"):
    _validar_campos_obrigatorios(form_data)
    _validar_tamanhos_campos(form_data)
    nome_medico = form_data.get("nome_medico", "").strip()
    medico = buscar_medico(nome_medico) if nome_medico else None
    paciente = _montar_paciente(form_data, medico, clinica_id=clinica_id)

    db.session.add(paciente)
    db.session.flush()

    db.session.add(Log(
        usuario_id=usuario_id,
        paciente_id=paciente.id,
        acao=acao,
    ))

    if not medico and nome_medico:
        db.session.add(Log(
            usuario_id=usuario_id,
            paciente_id=paciente.id,
            acao=f"Médico não encontrado para: '{nome_medico}'",
        ))

    db.session.commit()
    return paciente


@bp.route("/", methods=["GET", "POST"])
def index():
    return render_template("inicio.html")


@bp.route("/formulario", methods=["GET", "POST"])
def preencher_formulario():
    if request.method == "POST":
        dados_formulario = request.form.to_dict(flat=True)
        for tentativa in range(2):
            try:
                _salvar_formulario(request.form)
                return redirect(url_for("formulario.sucesso"))
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
                return render_template("formulario.html", dados=dados_formulario)
            except IntegrityError:
                db.session.rollback()
                flash("Não foi possível salvar o perfil. Verifique se o CPF já existe e tente novamente.", "danger")
                return render_template("formulario.html", dados=dados_formulario)
            except (OperationalError, InterfaceError) as exc:
                db.session.rollback()
                current_app.logger.warning(
                    "Falha transitória ao salvar formulário público. tentativa=%s",
                    tentativa + 1,
                    exc_info=exc,
                )
                if tentativa == 0:
                    continue
                flash(
                    "Houve uma instabilidade temporária ao salvar seu formulário. Seus dados continuam na tela; tente enviar novamente em alguns segundos.",
                    "danger",
                )
                return render_template("formulario.html", dados=dados_formulario)
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception("Erro inesperado ao salvar formulário público.")
                flash(
                    "Não foi possível concluir o envio agora. Seus dados continuam preenchidos para uma nova tentativa.",
                    "danger",
                )
                return render_template("formulario.html", dados=dados_formulario)

    return render_template("formulario.html", dados={})


@bp.route("/sucesso")
def sucesso():
    return render_template("sucesso.html")
