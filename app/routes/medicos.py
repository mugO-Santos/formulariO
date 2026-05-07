from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import current_user, login_required
from app.extensions import db
from app.models import Clinica, Log, Medico, Paciente
from app.decorators import superadmin_required
from app.scope import pode_acessar_medico, scoped_medicos, sincronizar_clinica_pacientes_do_medico

bp = Blueprint("medicos", __name__, url_prefix="/painel/medicos")


@bp.route("/")
@login_required
@superadmin_required
def index():
    medicos = scoped_medicos(Medico.query.filter_by(ativo=True), current_user).order_by(Medico.nome).all()
    contagem = {
        m.id: Paciente.query.filter_by(medico_id=m.id).filter(
            Paciente.excluido_em.is_(None)
        ).count()
        for m in medicos
    }
    if current_user.acesso_global:
        clinicas = Clinica.query.filter_by(ativo=True).order_by(Clinica.nome).all()
    else:
        clinicas = [current_user.clinica] if current_user.clinica else []
    return render_template("painel/medicos.html", medicos=medicos, contagem=contagem, clinicas=clinicas)


@bp.route("/novo", methods=["POST"])
@login_required
@superadmin_required
def novo():
    nome = request.form.get("nome", "").strip()
    crm = request.form.get("crm", "").strip()
    clinica_id_raw = request.form.get("clinica_id", "").strip()
    if not nome or not crm:
        flash("Nome e CRM são obrigatórios.", "danger")
        return redirect(url_for("medicos.index"))
    if Medico.query.filter_by(crm=crm).first():
        flash("CRM já cadastrado.", "danger")
        return redirect(url_for("medicos.index"))

    clinica_id = None
    if current_user.acesso_global:
        if clinica_id_raw:
            clinica_id = Clinica.query.get_or_404(int(clinica_id_raw)).id
    else:
        clinica_id = current_user.clinica_id

    db.session.add(Medico(nome=nome, crm=crm, clinica_id=clinica_id))
    db.session.add(Log(usuario_id=current_user.id, acao=f"Médico cadastrado: {nome} CRM {crm}"))
    db.session.commit()
    flash("Médico adicionado.", "success")
    return redirect(url_for("medicos.index"))


@bp.route("/<int:mid>/editar", methods=["POST"])
@login_required
@superadmin_required
def editar(mid):
    medico = Medico.query.get_or_404(mid)
    if not pode_acessar_medico(current_user, medico):
        return redirect(url_for("medicos.index"))

    medico.nome = request.form.get("nome", medico.nome).strip()
    medico.crm = request.form.get("crm", medico.crm).strip()

    if current_user.acesso_global:
        clinica_id_raw = request.form.get("clinica_id", "").strip()
        medico.clinica_id = Clinica.query.get_or_404(int(clinica_id_raw)).id if clinica_id_raw else None
    elif current_user.clinica_id:
        medico.clinica_id = current_user.clinica_id

    sincronizar_clinica_pacientes_do_medico(medico)
    db.session.commit()
    flash("Médico atualizado.", "success")
    return redirect(url_for("medicos.index"))
