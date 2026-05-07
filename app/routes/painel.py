from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, request, flash, redirect, url_for, abort, make_response
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from app.extensions import db
from app.models import Clinica, Encaminhamento, Paciente, Log
from app.decorators import nivel_minimo
from app.scope import pode_gerenciar_paciente, scoped_pacientes

bp = Blueprint("painel", __name__, url_prefix="/painel")


def _paciente_query():
    return scoped_pacientes(Paciente.query, current_user)


def _get_paciente_or_404(pid):
    return _paciente_query().filter(Paciente.id == pid).first_or_404()


def _requer_gerencia_paciente(paciente):
    if pode_gerenciar_paciente(current_user, paciente):
        return True
    flash("Este perfil foi compartilhado com sua clínica para consulta. Edições ficam com a clínica de origem.", "warning")
    return False


@bp.route("/")
@login_required
def index():
    from app.models import Medico
    from sqlalchemy import func, select

    base_pacientes = scoped_pacientes(Paciente.query, current_user).filter(
        Paciente.excluido_em.is_(None),
        Paciente.concluido_em.is_(None),
    )
    pacientes_sem_medico = (
        base_pacientes
        .filter(Paciente.medico_id.is_(None))
        .order_by(Paciente.criado_em.desc())
        .all()
    )

    base_ids = select(base_pacientes.with_entities(Paciente.id).subquery().c.id)

    # Médicos que têm ao menos 1 paciente ativo, ordenados pelo paciente mais recente
    medicos_com_pacientes = db.session.query(Medico, func.max(Paciente.criado_em).label("ultimo")).join(
        Paciente, Paciente.medico_id == Medico.id
    )
    medicos_com_pacientes = medicos_com_pacientes.filter(Paciente.id.in_(base_ids))
    medicos_com_pacientes = medicos_com_pacientes.group_by(Medico.id).order_by(
        func.max(Paciente.criado_em).desc()
    ).all()

    grupos = []
    for m, _ in medicos_com_pacientes:
        pacs = (
            scoped_pacientes(Paciente.query, current_user)
            .filter_by(medico_id=m.id)
            .filter(Paciente.excluido_em.is_(None), Paciente.concluido_em.is_(None))
            .order_by(Paciente.criado_em.desc())
            .all()
        )
        grupos.append({"medico": m, "pacientes": pacs})

    return render_template(
        "painel/index.html",
        grupos=grupos,
        pacientes_sem_medico=pacientes_sem_medico,
    )


@bp.route("/paciente/<int:pid>")
@login_required
def ver_paciente(pid):
    paciente = _get_paciente_or_404(pid)
    if paciente.excluido:
        abort(404)
    db.session.add(Log(usuario_id=current_user.id, paciente_id=pid, acao="Visualizou perfil"))
    db.session.commit()

    pode_gerenciar = _requer_gerencia_paciente(paciente)
    hospitais_destino = []
    if pode_gerenciar:
        hospitais_destino = (
            Clinica.query
            .filter(Clinica.ativo.is_(True), Clinica.eh_hospital.is_(True), Clinica.id != paciente.clinica_origem_id)
            .order_by(Clinica.nome)
            .all()
        )

    return render_template(
        "painel/perfil.html",
        paciente=paciente,
        pode_gerenciar=pode_gerenciar,
        hospitais_destino=hospitais_destino,
    )


@bp.route("/paciente/<int:pid>/encaminhar", methods=["POST"])
@login_required
def encaminhar_hospital(pid):
    paciente = _get_paciente_or_404(pid)
    if not _requer_gerencia_paciente(paciente):
        return redirect(url_for("painel.ver_paciente", pid=pid))

    clinica_destino_id = request.form.get("clinica_destino_id", "").strip()
    observacao = request.form.get("observacao", "").strip() or None
    if not clinica_destino_id:
        flash("Selecione o hospital de destino.", "danger")
        return redirect(url_for("painel.ver_paciente", pid=pid))

    try:
        destino_id = int(clinica_destino_id)
    except ValueError:
        flash("Destino inválido. Selecione um hospital ativo.", "danger")
        return redirect(url_for("painel.ver_paciente", pid=pid))

    destino = Clinica.query.filter_by(id=destino_id, ativo=True).first()
    if destino is None or not destino.eh_hospital:
        flash("Destino inválido. Selecione um hospital ativo.", "danger")
        return redirect(url_for("painel.ver_paciente", pid=pid))

    if destino.id == paciente.clinica_origem_id:
        flash("Não é possível encaminhar para a própria clínica de origem.", "danger")
        return redirect(url_for("painel.ver_paciente", pid=pid))

    encaminhamento = Encaminhamento.query.filter_by(
        paciente_id=pid,
        clinica_destino_id=destino.id,
    ).first()
    if encaminhamento:
        encaminhamento.status = "enviado"
        encaminhamento.observacao = observacao
        encaminhamento.enviado_por_usuario_id = current_user.id
    else:
        encaminhamento = Encaminhamento(
            paciente_id=pid,
            clinica_destino_id=destino.id,
            enviado_por_usuario_id=current_user.id,
            status="enviado",
            observacao=observacao,
        )
        db.session.add(encaminhamento)

    db.session.add(Log(
        usuario_id=current_user.id,
        paciente_id=pid,
        acao=f"Encaminhou paciente para hospital: {destino.nome}",
    ))
    db.session.commit()
    flash(f"Perfil encaminhado para {destino.nome}.", "success")
    return redirect(url_for("painel.ver_paciente", pid=pid))


@bp.route("/paciente/<int:pid>/observacoes", methods=["POST"])
@login_required
def editar_observacoes(pid):
    paciente = _get_paciente_or_404(pid)
    if paciente.excluido:
        abort(404)
    if not _requer_gerencia_paciente(paciente):
        return redirect(url_for("painel.ver_paciente", pid=pid))
    paciente.observacoes = request.form.get("observacoes", "").strip() or None
    db.session.add(Log(
        usuario_id=current_user.id,
        paciente_id=pid,
        acao="Editou campo Observações",
    ))
    db.session.commit()
    flash("Observações salvas.", "success")
    return redirect(url_for("painel.ver_paciente", pid=pid))


@bp.route("/paciente/<int:pid>/editar", methods=["GET", "POST"])
@login_required
@nivel_minimo(1)
def editar_paciente(pid):
    paciente = _get_paciente_or_404(pid)
    if paciente.excluido:
        abort(404)
    if not _requer_gerencia_paciente(paciente):
        return redirect(url_for("painel.ver_paciente", pid=pid))
    if request.method == "POST":
        paciente.nome = request.form["nome"].strip()
        paciente.nome_mae = request.form["nome_mae"].strip()
        paciente.telefone = request.form["telefone"].strip()
        paciente.email = request.form.get("email", "").strip() or None
        paciente.profissao = request.form.get("profissao", "").strip() or None
        paciente.estado_civil = request.form["estado_civil"]
        paciente.endereco = request.form.get("endereco", "").strip() or None
        paciente.numero = request.form.get("numero", "").strip() or None
        paciente.bairro = request.form.get("bairro", "").strip() or None
        paciente.cidade = request.form.get("cidade", "").strip() or None
        paciente.cep = request.form.get("cep", "").strip() or None
        db.session.add(Log(
            usuario_id=current_user.id,
            paciente_id=pid,
            acao="Editou dados do paciente",
        ))
        db.session.commit()
        flash("Dados atualizados.", "success")
        return redirect(url_for("painel.ver_paciente", pid=pid))
    return render_template("painel/editar_paciente.html", paciente=paciente)


@bp.route("/paciente/<int:pid>/excluir", methods=["POST"])
@login_required
@nivel_minimo(1)
def excluir_paciente(pid):
    paciente = _get_paciente_or_404(pid)
    if not _requer_gerencia_paciente(paciente):
        return redirect(url_for("painel.ver_paciente", pid=pid))
    paciente.excluido_em = datetime.now(timezone.utc)
    db.session.add(Log(
        usuario_id=current_user.id,
        paciente_id=pid,
        acao="Excluiu perfil (soft delete, 60 dias)",
    ))
    db.session.commit()
    flash("Perfil excluído. Pode ser recuperado em até 60 dias.", "warning")
    return redirect(url_for("painel.index"))


@bp.route("/paciente/<int:pid>/concluir", methods=["POST"])
@login_required
def concluir_paciente(pid):
    paciente = _get_paciente_or_404(pid)
    if paciente.excluido:
        abort(404)
    if not _requer_gerencia_paciente(paciente):
        return redirect(url_for("painel.ver_paciente", pid=pid))
    paciente.concluido_em = datetime.now(timezone.utc)
    db.session.add(Log(
        usuario_id=current_user.id,
        paciente_id=pid,
        acao="Marcou perfil como concluído",
    ))
    db.session.commit()
    flash(f"Perfil de {paciente.nome} concluído e movido para a aba Pacientes.", "success")
    return redirect(url_for("painel.index"))


@bp.route("/paciente/<int:pid>/desconcluir", methods=["POST"])
@login_required
def desconcluir_paciente(pid):
    paciente = _get_paciente_or_404(pid)
    if not _requer_gerencia_paciente(paciente):
        return redirect(url_for("painel.ver_paciente", pid=pid))
    paciente.concluido_em = None
    db.session.add(Log(
        usuario_id=current_user.id,
        paciente_id=pid,
        acao="Reabriu perfil concluído para triagem",
    ))
    db.session.commit()
    flash(f"Perfil de {paciente.nome} movido de volta para triagem.", "info")
    return redirect(url_for("painel.pacientes_concluidos"))


@bp.route("/pacientes")
@login_required
def pacientes_concluidos():
    from app.models import Medico
    from sqlalchemy import func, select

    base_pacientes = scoped_pacientes(Paciente.query, current_user).filter(
        Paciente.excluido_em.is_(None),
        Paciente.concluido_em.isnot(None),
    )
    pacientes_sem_medico = (
        base_pacientes
        .filter(Paciente.medico_id.is_(None))
        .order_by(Paciente.concluido_em.desc())
        .all()
    )

    base_ids = select(base_pacientes.with_entities(Paciente.id).subquery().c.id)

    medicos_com_pacientes = db.session.query(Medico, func.max(Paciente.concluido_em).label("ultimo")).join(
        Paciente, Paciente.medico_id == Medico.id
    )
    medicos_com_pacientes = medicos_com_pacientes.filter(Paciente.id.in_(base_ids))
    medicos_com_pacientes = medicos_com_pacientes.group_by(Medico.id).order_by(
        func.max(Paciente.concluido_em).desc()
    ).all()

    grupos = []
    for m, _ in medicos_com_pacientes:
        pacs = (
            scoped_pacientes(Paciente.query, current_user)
            .filter_by(medico_id=m.id)
            .filter(Paciente.excluido_em.is_(None), Paciente.concluido_em.isnot(None))
            .order_by(Paciente.concluido_em.desc())
            .all()
        )
        grupos.append({"medico": m, "pacientes": pacs})

    return render_template(
        "painel/pacientes.html",
        grupos=grupos,
        pacientes_sem_medico=pacientes_sem_medico,
    )


@bp.route("/excluidos")
@login_required
@nivel_minimo(0)
def excluidos():
    limite = datetime.now(timezone.utc) - timedelta(days=60)
    pacientes = (
        Paciente.query
        .filter(Paciente.excluido_em >= limite)
        .order_by(Paciente.excluido_em.desc())
        .all()
    )
    return render_template("painel/excluidos.html", pacientes=pacientes)


@bp.route("/paciente/<int:pid>/recuperar", methods=["POST"])
@login_required
@nivel_minimo(0)
def recuperar_paciente(pid):
    paciente = _get_paciente_or_404(pid)
    if not _requer_gerencia_paciente(paciente):
        return redirect(url_for("painel.ver_paciente", pid=pid))
    paciente.excluido_em = None
    db.session.add(Log(
        usuario_id=current_user.id,
        paciente_id=pid,
        acao="Recuperou perfil excluído",
    ))
    db.session.commit()
    flash("Perfil recuperado com sucesso.", "success")
    return redirect(url_for("painel.excluidos"))


@bp.route("/paciente/<int:pid>/pdf")
@login_required
def exportar_pdf(pid):
    paciente = _get_paciente_or_404(pid)
    if paciente.excluido:
        abort(404)
    try:
        from weasyprint import HTML
    except (ImportError, OSError):
        flash(
            "Não foi possível gerar PDF neste ambiente. Instale as bibliotecas nativas do WeasyPrint.",
            "danger",
        )
        return redirect(url_for("painel.ver_paciente", pid=pid))

    db.session.add(Log(
        usuario_id=current_user.id,
        paciente_id=pid,
        acao="Exportou perfil em PDF",
    ))
    db.session.commit()
    html = render_template("painel/pdf_perfil.html", paciente=paciente)
    try:
        pdf = HTML(string=html).write_pdf()
    except OSError:
        flash(
            "Falha ao gerar PDF: dependências nativas do WeasyPrint não encontradas.",
            "danger",
        )
        return redirect(url_for("painel.ver_paciente", pid=pid))

    response = make_response(pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = (
        f"inline; filename=paciente_{paciente.id}.pdf"
    )
    return response


@bp.route("/perfil", methods=["GET", "POST"])
@login_required
def meu_perfil():
    if request.method == "POST":
        nova_senha = request.form.get("nova_senha", "")
        if len(nova_senha) < 6:
            flash("A senha deve ter no mínimo 6 caracteres.", "danger")
            return redirect(url_for("painel.meu_perfil"))
        current_user.senha_hash = generate_password_hash(nova_senha)
        db.session.commit()
        flash("Senha alterada com sucesso.", "success")
    return render_template("painel/meu_perfil.html")
