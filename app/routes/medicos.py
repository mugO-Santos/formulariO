from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required
from app.extensions import db
from app.models import Medico, Log
from app.decorators import nivel_minimo

bp = Blueprint("medicos", __name__, url_prefix="/painel/medicos")


@bp.route("/")
@login_required
@nivel_minimo(1)
def index():
    from app.models import Paciente
    medicos = Medico.query.order_by(Medico.nome).all()
    contagem = {
        m.id: Paciente.query.filter_by(medico_id=m.id).filter(
            Paciente.excluido_em.is_(None)
        ).count()
        for m in medicos
    }
    return render_template("painel/medicos.html", medicos=medicos, contagem=contagem)


@bp.route("/novo", methods=["POST"])
@login_required
@nivel_minimo(1)
def novo():
    nome = request.form.get("nome", "").strip()
    crm = request.form.get("crm", "").strip()
    if not nome or not crm:
        flash("Nome e CRM são obrigatórios.", "danger")
        return redirect(url_for("medicos.index"))
    if Medico.query.filter_by(crm=crm).first():
        flash("CRM já cadastrado.", "danger")
        return redirect(url_for("medicos.index"))
    db.session.add(Medico(nome=nome, crm=crm))
    db.session.add(Log(usuario_id=None, acao=f"Médico cadastrado: {nome} CRM {crm}"))
    db.session.commit()
    flash("Médico adicionado.", "success")
    return redirect(url_for("medicos.index"))


@bp.route("/<int:mid>/editar", methods=["POST"])
@login_required
@nivel_minimo(1)
def editar(mid):
    medico = Medico.query.get_or_404(mid)
    medico.nome = request.form.get("nome", medico.nome).strip()
    medico.crm = request.form.get("crm", medico.crm).strip()
    db.session.commit()
    flash("Médico atualizado.", "success")
    return redirect(url_for("medicos.index"))
