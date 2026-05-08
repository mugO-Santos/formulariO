from datetime import datetime, timezone, timedelta
from io import BytesIO
import textwrap
import os
from flask import Blueprint, render_template, request, flash, redirect, url_for, abort, make_response
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from sqlalchemy import String, cast, func, or_
from app.extensions import db
from app.models import Agendamento, Clinica, Encaminhamento, Paciente, Log
from app.decorators import nivel_minimo
from app.scope import pode_gerenciar_paciente, scoped_agendamentos, scoped_pacientes

bp = Blueprint("painel", __name__, url_prefix="/painel")


def _paciente_query():
    return scoped_pacientes(Paciente.query, current_user)


def _get_paciente_or_404(pid):
    return _paciente_query().filter(Paciente.id == pid).first_or_404()


def _agendamento_query():
    return scoped_agendamentos(Agendamento.query, current_user)


def _get_agendamento_or_404(aid):
    return _agendamento_query().filter(Agendamento.id == aid).first_or_404()


def _requer_gerencia_paciente(paciente):
    if pode_gerenciar_paciente(current_user, paciente):
        return True
    flash("Este perfil foi compartilhado com sua clínica para consulta. Edições ficam com a clínica de origem.", "warning")
    return False


def _filtro_busca_paciente(texto_busca):
    filtros = [
        Paciente.nome.ilike(f"%{texto_busca}%"),
        Paciente.cpf.ilike(f"%{texto_busca}%"),
    ]
    if texto_busca.isdigit():
        filtros.append(cast(Paciente.id, String) == texto_busca)
    return or_(*filtros)


def _filtro_busca_agendamento(texto_busca):
    filtros = [
        Agendamento.paciente_nome.ilike(f"%{texto_busca}%"),
        Agendamento.paciente_cpf.ilike(f"%{texto_busca}%"),
        cast(Agendamento.id, String) == texto_busca,
    ]
    if texto_busca.isdigit():
        filtros.append(cast(Agendamento.paciente_id, String) == texto_busca)
    return or_(*filtros)


def _parse_data_hora(data_raw, hora_raw):
    try:
        return datetime.strptime(f"{data_raw} {hora_raw}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _parse_data_convenio(data_raw):
    if not data_raw:
        return None
    try:
        return datetime.strptime(data_raw, "%Y-%m-%d").date()
    except ValueError:
        return "invalid"


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

    pacientes_para_agenda = (
        scoped_pacientes(Paciente.query, current_user)
        .filter(Paciente.excluido_em.is_(None))
        .order_by(Paciente.nome.asc())
        .limit(250)
        .all()
    )

    proximos_agendamentos = (
        _agendamento_query()
        .filter(
            Agendamento.status == "agendado",
            Agendamento.excluido_em.is_(None),
            Agendamento.concluido_em.is_(None),
        )
        .order_by(Agendamento.agendado_para.asc(), Agendamento.id.asc())
        .limit(8)
        .all()
    )

    return render_template(
        "painel/index.html",
        grupos=grupos,
        pacientes_sem_medico=pacientes_sem_medico,
        pacientes_para_agenda=pacientes_para_agenda,
        proximos_agendamentos=proximos_agendamentos,
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

    busca = request.args.get("q", "").strip()

    base_pacientes = scoped_pacientes(Paciente.query, current_user).filter(
        Paciente.excluido_em.is_(None),
        Paciente.concluido_em.isnot(None),
    )
    if busca:
        base_pacientes = base_pacientes.filter(_filtro_busca_paciente(busca))

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

    agendamentos_concluidos = (
        _agendamento_query()
        .filter(
            Agendamento.status == "concluido",
            Agendamento.excluido_em.is_(None),
            Agendamento.concluido_em.isnot(None),
        )
    )
    if busca:
        agendamentos_concluidos = agendamentos_concluidos.filter(_filtro_busca_agendamento(busca))
    agendamentos_concluidos = agendamentos_concluidos.order_by(
        Agendamento.concluido_em.desc(),
        Agendamento.id.desc(),
    ).all()

    return render_template(
        "painel/pacientes.html",
        grupos=grupos,
        pacientes_sem_medico=pacientes_sem_medico,
        agendamentos_concluidos=agendamentos_concluidos,
        q=busca,
    )


@bp.route("/agendamentos")
@login_required
def agendamentos():
    busca = request.args.get("q", "").strip()

    query = _agendamento_query().filter(
        Agendamento.status == "agendado",
        Agendamento.excluido_em.is_(None),
        Agendamento.concluido_em.is_(None),
    )
    if busca:
        query = query.filter(_filtro_busca_agendamento(busca))

    agendamentos_lista = query.order_by(Agendamento.agendado_para.asc(), Agendamento.id.asc()).all()
    pacientes_para_agenda = (
        scoped_pacientes(Paciente.query, current_user)
        .filter(Paciente.excluido_em.is_(None))
        .order_by(Paciente.nome.asc())
        .limit(250)
        .all()
    )
    return render_template(
        "painel/agendamentos.html",
        agendamentos=agendamentos_lista,
        pacientes_para_agenda=pacientes_para_agenda,
        q=busca,
    )


@bp.route("/agendamentos/novo", methods=["POST"])
@login_required
@nivel_minimo(1)
def novo_agendamento():
    paciente_id_raw = request.form.get("paciente_id", "").strip()
    data_agendamento = request.form.get("data_agendamento", "").strip()
    hora_agendamento = request.form.get("hora_agendamento", "").strip()

    paciente = None
    if paciente_id_raw:
        try:
            paciente_id = int(paciente_id_raw)
        except ValueError:
            flash("Perfil selecionado é inválido.", "danger")
            return redirect(request.referrer or url_for("painel.agendamentos"))
        paciente = _paciente_query().filter(Paciente.id == paciente_id).first()
        if paciente is None:
            flash("Perfil selecionado não está disponível para sua clínica.", "danger")
            return redirect(request.referrer or url_for("painel.agendamentos"))

    nome_paciente = request.form.get("nome_paciente", "").strip() or (paciente.nome if paciente else "")
    telefone_paciente = request.form.get("telefone_paciente", "").strip() or (paciente.telefone if paciente else "")
    cpf_paciente = request.form.get("cpf_paciente", "").strip() or (paciente.cpf if paciente else "") or None

    if not nome_paciente or not telefone_paciente:
        flash("Nome e Telefone são obrigatórios para agendar.", "danger")
        return redirect(request.referrer or url_for("painel.agendamentos"))

    agendado_para = _parse_data_hora(data_agendamento, hora_agendamento)
    if agendado_para is None:
        flash("Informe data e horário válidos.", "danger")
        return redirect(request.referrer or url_for("painel.agendamentos"))

    convenio_validade = _parse_data_convenio(request.form.get("convenio_validade", "").strip())
    if convenio_validade == "invalid":
        flash("Data de validade do convênio inválida.", "danger")
        return redirect(request.referrer or url_for("painel.agendamentos"))

    clinica_id = current_user.clinica_id
    if clinica_id is None and paciente is not None:
        clinica_id = paciente.clinica_origem_id

    agendamento = Agendamento(
        clinica_id=clinica_id,
        paciente_id=paciente.id if paciente else None,
        criado_por_usuario_id=current_user.id,
        paciente_nome=nome_paciente,
        paciente_telefone=telefone_paciente,
        paciente_cpf=cpf_paciente,
        agendado_para=agendado_para,
        convenio_nome=request.form.get("convenio_nome", "").strip() or None,
        convenio_carteirinha=request.form.get("convenio_carteirinha", "").strip() or None,
        convenio_validade=convenio_validade,
        status="agendado",
    )
    db.session.add(agendamento)
    db.session.flush()
    db.session.add(Log(usuario_id=current_user.id, paciente_id=agendamento.paciente_id, acao=f"Criou agendamento #{agendamento.id}"))
    db.session.commit()
    flash(f"Agendamento #{agendamento.id} criado com sucesso.", "success")
    return redirect(url_for("painel.agendamentos"))


@bp.route("/agendamentos/<int:aid>/editar", methods=["GET", "POST"])
@login_required
@nivel_minimo(1)
def editar_agendamento(aid):
    agendamento = _get_agendamento_or_404(aid)
    if agendamento.status != "agendado" or agendamento.excluido_em is not None:
        flash("Apenas agendamentos ativos podem ser editados.", "warning")
        return redirect(url_for("painel.agendamentos"))

    if request.method == "POST":
        paciente_id_raw = request.form.get("paciente_id", "").strip()
        paciente = None
        if paciente_id_raw:
            try:
                paciente_id = int(paciente_id_raw)
            except ValueError:
                flash("Perfil selecionado é inválido.", "danger")
                return redirect(url_for("painel.editar_agendamento", aid=aid))
            paciente = _paciente_query().filter(Paciente.id == paciente_id).first()
            if paciente is None:
                flash("Perfil selecionado não está disponível para sua clínica.", "danger")
                return redirect(url_for("painel.editar_agendamento", aid=aid))

        agendamento.paciente_id = paciente.id if paciente else None
        agendamento.paciente_nome = request.form.get("nome_paciente", "").strip() or (paciente.nome if paciente else "")
        agendamento.paciente_telefone = request.form.get("telefone_paciente", "").strip() or (paciente.telefone if paciente else "")
        agendamento.paciente_cpf = request.form.get("cpf_paciente", "").strip() or (paciente.cpf if paciente else "") or None

        if not agendamento.paciente_nome or not agendamento.paciente_telefone:
            flash("Nome e Telefone são obrigatórios para agendar.", "danger")
            return redirect(url_for("painel.editar_agendamento", aid=aid))

        agendado_para = _parse_data_hora(
            request.form.get("data_agendamento", "").strip(),
            request.form.get("hora_agendamento", "").strip(),
        )
        if agendado_para is None:
            flash("Informe data e horário válidos.", "danger")
            return redirect(url_for("painel.editar_agendamento", aid=aid))

        convenio_validade = _parse_data_convenio(request.form.get("convenio_validade", "").strip())
        if convenio_validade == "invalid":
            flash("Data de validade do convênio inválida.", "danger")
            return redirect(url_for("painel.editar_agendamento", aid=aid))

        agendamento.agendado_para = agendado_para
        agendamento.convenio_nome = request.form.get("convenio_nome", "").strip() or None
        agendamento.convenio_carteirinha = request.form.get("convenio_carteirinha", "").strip() or None
        agendamento.convenio_validade = convenio_validade

        db.session.add(Log(usuario_id=current_user.id, paciente_id=agendamento.paciente_id, acao=f"Editou agendamento #{agendamento.id}"))
        db.session.commit()
        flash(f"Agendamento #{agendamento.id} atualizado.", "success")
        return redirect(url_for("painel.agendamentos"))

    pacientes_para_agenda = (
        scoped_pacientes(Paciente.query, current_user)
        .filter(Paciente.excluido_em.is_(None))
        .order_by(Paciente.nome.asc())
        .limit(250)
        .all()
    )
    return render_template(
        "painel/editar_agendamento.html",
        agendamento=agendamento,
        pacientes_para_agenda=pacientes_para_agenda,
    )


@bp.route("/agendamentos/<int:aid>/cancelar", methods=["POST"])
@login_required
@nivel_minimo(1)
def cancelar_agendamento(aid):
    agendamento = _get_agendamento_or_404(aid)
    if agendamento.status != "agendado" or agendamento.excluido_em is not None:
        flash("Agendamento já está encerrado.", "warning")
        return redirect(url_for("painel.agendamentos"))

    agendamento.status = "cancelado"
    agendamento.excluido_em = datetime.now(timezone.utc)
    db.session.add(Log(usuario_id=current_user.id, paciente_id=agendamento.paciente_id, acao=f"Cancelou agendamento #{agendamento.id}"))
    db.session.commit()
    flash(f"Agendamento #{agendamento.id} cancelado.", "info")
    return redirect(url_for("painel.agendamentos"))


@bp.route("/agendamentos/<int:aid>/concluir", methods=["POST"])
@login_required
@nivel_minimo(1)
def concluir_agendamento(aid):
    agendamento = _get_agendamento_or_404(aid)
    if agendamento.status != "agendado" or agendamento.excluido_em is not None:
        flash("Agendamento já está encerrado.", "warning")
        return redirect(url_for("painel.agendamentos"))

    agendamento.status = "concluido"
    agendamento.concluido_em = datetime.now(timezone.utc)
    db.session.add(Log(usuario_id=current_user.id, paciente_id=agendamento.paciente_id, acao=f"Concluiu agendamento #{agendamento.id}"))
    db.session.commit()
    flash(f"Agendamento #{agendamento.id} marcado como concluído.", "success")
    return redirect(url_for("painel.pacientes_concluidos"))


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
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError:
        flash("Falha ao gerar PDF neste ambiente. Dependência ReportLab não encontrada.", "danger")
        return redirect(url_for("painel.ver_paciente", pid=pid))

    db.session.add(Log(
        usuario_id=current_user.id,
        paciente_id=pid,
        acao="Exportou perfil em PDF",
    ))
    db.session.commit()

    buffer = BytesIO()
    try:
        from reportlab.lib import colors

        c = canvas.Canvas(buffer, pagesize=A4)
        largura, altura = A4
        margem_x = 36
        margem_y = 36
        area_largura = largura - (margem_x * 2)
        topo = altura - margem_y

        def clean(valor):
            if valor in (None, ""):
                return "-"
            return str(valor)

        def fmt_data(dt):
            return dt.strftime("%d/%m/%Y") if dt else "-"

        def draw_card(x, y_topo, card_largura, titulo, campos):
            linha_altura = 18
            titulo_altura = 28
            padding = 12
            card_altura = titulo_altura + (len(campos) * linha_altura) + (padding * 2)

            c.setFillColor(colors.HexColor("#F8FAFC"))
            c.roundRect(x, y_topo - card_altura, card_largura, card_altura, 10, fill=1, stroke=0)

            c.setFillColor(colors.HexColor("#E2E8F0"))
            c.roundRect(x, y_topo - titulo_altura - padding, card_largura, titulo_altura, 10, fill=1, stroke=0)

            c.setFillColor(colors.HexColor("#0F172A"))
            c.setFont("Helvetica-Bold", 11)
            c.drawString(x + padding, y_topo - titulo_altura + 6 - padding, titulo)

            y_linha = y_topo - titulo_altura - 14 - padding
            for rotulo, valor in campos:
                c.setFillColor(colors.HexColor("#334155"))
                c.setFont("Helvetica-Bold", 9)
                c.drawString(x + padding, y_linha, f"{rotulo}:")

                c.setFillColor(colors.HexColor("#0F172A"))
                c.setFont("Helvetica", 9)
                texto = clean(valor)
                linhas = textwrap.wrap(texto, width=42) or ["-"]
                c.drawString(x + 112, y_linha, linhas[0])
                y_linha -= linha_altura
                for extra in linhas[1:]:
                    c.drawString(x + 112, y_linha, extra)
                    y_linha -= linha_altura

            return card_altura

        # Header visual
        c.setFillColor(colors.HexColor("#0B3A5B"))
        c.roundRect(margem_x, topo - 70, area_largura, 58, 12, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(margem_x + 16, topo - 36, "Ficha do Paciente")
        c.setFont("Helvetica", 10)
        c.drawString(margem_x + 16, topo - 54, f"Emitido em {datetime.now().strftime('%d/%m/%Y %H:%M')}")

        y_inicio_cards = topo - 92
        # Logo e nome da clínica com fallback para registros antigos sem clinica_id.
        clinica = paciente.clinica
        if clinica is None and paciente.medico is not None:
            clinica = paciente.medico.clinica
        if clinica is None and current_user.clinica is not None:
            clinica = current_user.clinica

        if clinica and clinica.logo_path:
            from flask import current_app
            logo_rel = clinica.logo_path.lstrip("/\\")
            logo_abs = os.path.join(current_app.static_folder, logo_rel)
            current_app.logger.warning(
                "PDF logo debug: clinica=%s logo_path=%s logo_abs=%s exists=%s",
                clinica.id, clinica.logo_path, logo_abs, os.path.isfile(logo_abs),
            )
            if os.path.isfile(logo_abs):
                try:
                    from reportlab.lib.utils import ImageReader
                    img = ImageReader(logo_abs)
                    iw, ih = img.getSize()
                    max_w, max_h = 100, 40
                    escala = min(max_w / iw, max_h / ih, 1.0)
                    dw, dh = iw * escala, ih * escala
                    ix = margem_x + area_largura - dw - 10
                    iy = topo - 12 - dh
                    c.drawImage(logo_abs, ix, iy, width=dw, height=dh, mask="auto")
                except Exception as exc:
                    current_app.logger.warning("PDF logo draw error: %s", exc)
        if clinica and (clinica.nome_impresso or clinica.nome):
            nome_clinica = clinica.nome_impresso or clinica.nome
            # Texto abaixo do header, alinhado à direita
            c.setFillColor(colors.HexColor("#0B3A5B"))
            c.setFont("Helvetica-Bold", 8)
            label = nome_clinica[:50]
            tw = c.stringWidth(label, "Helvetica-Bold", 8)
            c.drawString(margem_x + area_largura - tw - 10, topo - 78, label)

        gap = 14
        card_largura = (area_largura - gap) / 2

        medico = "Nao vinculado"
        if paciente.medico:
            medico = f"{paciente.medico.nome} - CRM {paciente.medico.crm}"

        card1 = [
            ("Nome", paciente.nome),
            ("Nome da Mae", paciente.nome_mae),
            ("CPF", paciente.cpf),
            ("RG", paciente.rg),
            ("Nascimento", fmt_data(paciente.data_nascimento)),
            ("Estado Civil", paciente.estado_civil),
            ("Profissao", paciente.profissao),
        ]
        card2 = [
            ("Telefone", paciente.telefone),
            ("E-mail", paciente.email),
            ("CEP", paciente.cep),
            ("Endereco", f"{clean(paciente.endereco)}, {clean(paciente.numero) if paciente.numero else 's/n'}"),
            ("Bairro", paciente.bairro),
            ("Cidade", paciente.cidade),
            ("Medico", medico),
        ]

        draw_card(margem_x, y_inicio_cards, card_largura, "Dados Pessoais", card1)
        draw_card(margem_x + card_largura + gap, y_inicio_cards, card_largura, "Contato e Atendimento", card2)

        c.save()
        buffer.seek(0)
    except Exception:
        flash("Falha ao gerar PDF do paciente.", "danger")
        return redirect(url_for("painel.ver_paciente", pid=pid))

    response = make_response(buffer.getvalue())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = (
        f"attachment; filename=paciente_{paciente.id}.pdf"
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
