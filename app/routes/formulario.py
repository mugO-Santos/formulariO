from datetime import date, datetime, timezone
import uuid
from flask import Blueprint, current_app, render_template, request, flash, redirect, url_for
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError, SQLAlchemyError
from app.extensions import db
from app.models import Paciente, Log
from app.fuzzy import buscar_medico

bp = Blueprint("formulario", __name__)


def _montar_paciente(form_data, medico):
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

    nome_medico = form_data.get("nome_medico", "").strip()

    convenio_validade_raw = form_data.get("convenio_validade", "").strip()
    if convenio_validade_raw:
        try:
            from datetime import datetime as _dt
            convenio_validade = _dt.strptime(convenio_validade_raw, "%Y-%m-%d").date()
        except ValueError:
            convenio_validade = None
    else:
        convenio_validade = None

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
        medico_id=medico.id if medico else None,
        clinica_id=medico.clinica_id if medico else None,
        nome_medico_digitado=nome_medico or None,
        aceite_lgpd=bool(form_data.get("aceite_lgpd")),
        aceite_lgpd_em=datetime.now(timezone.utc) if form_data.get("aceite_lgpd") else None,
    )


def _salvar_formulario(form_data):
    nome_medico = form_data.get("nome_medico", "").strip()
    medico = buscar_medico(nome_medico) if nome_medico else None
    paciente = _montar_paciente(form_data, medico)

    db.session.add(paciente)
    db.session.flush()

    db.session.add(Log(
        paciente_id=paciente.id,
        acao="Perfil criado via formulário público",
    ))

    if not medico and nome_medico:
        db.session.add(Log(
            paciente_id=paciente.id,
            acao=f"Médico não encontrado para: '{nome_medico}'",
        ))

    db.session.commit()


@bp.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        dados_formulario = request.form.to_dict(flat=True)
        for tentativa in range(2):
            try:
                _salvar_formulario(request.form)
                return redirect(url_for("formulario.sucesso"))
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
