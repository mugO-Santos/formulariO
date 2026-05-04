from datetime import datetime, timezone
from flask import Blueprint, render_template, request, flash, redirect, url_for
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import Paciente, Log
from app.fuzzy import buscar_medico

bp = Blueprint("formulario", __name__)


@bp.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # Validação do aceite LGPD
        if not request.form.get("aceite_lgpd"):
            flash("Você precisa aceitar o Termo de Uso de Dados para continuar.", "danger")
            return render_template("formulario.html", dados=request.form)

        nome_medico = request.form.get("nome_medico", "").strip()
        medico = buscar_medico(nome_medico) if nome_medico else None

        paciente = Paciente(
            nome=request.form["nome"].strip(),
            nome_mae=request.form["nome_mae"].strip(),
            cpf=request.form["cpf"].strip(),
            rg=request.form.get("rg", "").strip() or None,
            data_nascimento=datetime.strptime(request.form["data_nascimento"], "%Y-%m-%d").date(),
            estado_civil=request.form["estado_civil"],
            profissao=request.form.get("profissao", "").strip() or None,
            email=request.form.get("email", "").strip() or None,
            telefone=request.form["telefone"].strip(),
            cep=request.form.get("cep", "").strip() or None,
            endereco=request.form.get("endereco", "").strip() or None,
            numero=request.form.get("numero", "").strip() or None,
            bairro=request.form.get("bairro", "").strip() or None,
            cidade=request.form.get("cidade", "").strip() or None,
            medico_id=medico.id if medico else None,
            nome_medico_digitado=nome_medico or None,
            forma_pagamento=request.form.get("forma_pagamento", "").strip() or None,
            aceite_lgpd=True,
            aceite_lgpd_em=datetime.now(timezone.utc),
        )
        db.session.add(paciente)
        try:
            db.session.flush()  # gera o id
        except IntegrityError:
            db.session.rollback()
            flash("Este CPF já está cadastrado no sistema.", "danger")
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
