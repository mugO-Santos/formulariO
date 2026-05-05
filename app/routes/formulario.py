from datetime import date, datetime, timezone
import uuid
from flask import Blueprint, render_template, request, flash, redirect, url_for
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import Paciente, Log
from app.fuzzy import buscar_medico

bp = Blueprint("formulario", __name__)


@bp.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip() or "Não informado"
        nome_mae = request.form.get("nome_mae", "").strip() or "Não informado"
        cpf = request.form.get("cpf", "").strip()
        if not cpf:
            cpf = f"P{uuid.uuid4().hex[:13]}"
        telefone = request.form.get("telefone", "").strip() or "Não informado"
        estado_civil = request.form.get("estado_civil", "").strip() or "Não informado"
        data_nascimento_raw = request.form.get("data_nascimento", "").strip()
        if data_nascimento_raw:
            try:
                data_nascimento = datetime.strptime(data_nascimento_raw, "%Y-%m-%d").date()
            except ValueError:
                data_nascimento = date(1900, 1, 1)
        else:
            data_nascimento = date(1900, 1, 1)

        nome_medico = request.form.get("nome_medico", "").strip()
        medico = buscar_medico(nome_medico) if nome_medico else None

        paciente = Paciente(
            nome=nome,
            nome_mae=nome_mae,
            cpf=cpf,
            rg=request.form.get("rg", "").strip() or None,
            data_nascimento=data_nascimento,
            estado_civil=estado_civil,
            profissao=request.form.get("profissao", "").strip() or None,
            email=request.form.get("email", "").strip() or None,
            telefone=telefone,
            cep=request.form.get("cep", "").strip() or None,
            endereco=request.form.get("endereco", "").strip() or None,
            numero=request.form.get("numero", "").strip() or None,
            bairro=request.form.get("bairro", "").strip() or None,
            cidade=request.form.get("cidade", "").strip() or None,
            medico_id=medico.id if medico else None,
            nome_medico_digitado=nome_medico or None,
            forma_pagamento=request.form.get("forma_pagamento", "").strip() or None,
            aceite_lgpd=bool(request.form.get("aceite_lgpd")),
            aceite_lgpd_em=datetime.now(timezone.utc) if request.form.get("aceite_lgpd") else None,
        )
        db.session.add(paciente)
        try:
            db.session.flush()  # gera o id
        except IntegrityError:
            db.session.rollback()
            flash("Não foi possível salvar o perfil. Verifique se o CPF já existe e tente novamente.", "danger")
            return render_template("formulario.html", dados=request.form)

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
        return redirect(url_for("formulario.sucesso"))

    return render_template("formulario.html", dados={})


@bp.route("/sucesso")
def sucesso():
    return render_template("sucesso.html")
