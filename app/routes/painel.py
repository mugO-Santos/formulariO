from collections import defaultdict
from datetime import datetime, timezone, timedelta
from io import BytesIO
import textwrap
import os
import re
import unicodedata
from urllib.parse import quote
from flask import Blueprint, current_app, render_template, request, flash, redirect, url_for, abort, make_response
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from sqlalchemy import String, cast, func, or_
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import load_only, selectinload
from app.extensions import db
from app.models import Agendamento, Clinica, Encaminhamento, Paciente, Log
from app.decorators import nivel_minimo
from app.routes.formulario import _salvar_formulario
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


def _nome_arquivo_pdf_paciente(paciente):
    nome_base = (paciente.nome or "").strip()
    if not nome_base:
        return f"paciente_{paciente.id}.pdf"

    # Remove acentos e limita a caracteres seguros para nome de arquivo.
    nome_ascii = unicodedata.normalize("NFKD", nome_base).encode("ascii", "ignore").decode("ascii")
    nome_limpo = re.sub(r"[^A-Za-z0-9_-]+", "_", nome_ascii).strip("_")
    nome_limpo = re.sub(r"_+", "_", nome_limpo)
    if not nome_limpo:
        nome_limpo = f"paciente_{paciente.id}"

    return f"{nome_limpo[:80]}.pdf"


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

    base_pacientes = scoped_pacientes(Paciente.query, current_user).filter(
        Paciente.excluido_em.is_(None),
        Paciente.concluido_em.is_(None),
    ).options(selectinload(Paciente.medico))
    pacientes_sem_medico = (
        base_pacientes
        .filter(Paciente.medico_id.is_(None))
        .order_by(Paciente.criado_em.desc())
        .all()
    )

    pacientes_por_medico = (
        base_pacientes
        .filter(Paciente.medico_id.isnot(None))
        .order_by(Paciente.criado_em.desc())
        .all()
    )
    mapa_pacientes = defaultdict(list)
    ultimo_por_medico = {}
    for p in pacientes_por_medico:
        mapa_pacientes[p.medico_id].append(p)
        ultimo_por_medico.setdefault(p.medico_id, p.criado_em)

    medicos = {
        m.id: m
        for m in Medico.query.filter(Medico.id.in_(mapa_pacientes.keys())).all()
    }
    grupos = []
    for medico_id, _ in sorted(ultimo_por_medico.items(), key=lambda item: item[1], reverse=True):
        medico = medicos.get(medico_id)
        if medico:
            grupos.append({"medico": medico, "pacientes": mapa_pacientes[medico_id]})

    pacientes_para_agenda = (
        scoped_pacientes(Paciente.query, current_user)
        .options(load_only(Paciente.id, Paciente.nome, Paciente.telefone, Paciente.cpf))
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


@bp.route("/pacientes/novo", methods=["GET", "POST"])
@login_required
def cadastrar_paciente():
    dados = request.form.to_dict(flat=True) if request.method == "POST" else {}

    if request.method == "POST":
        clinica_id = current_user.clinica_id
        nome_medico = request.form.get("nome_medico", "").strip()

        if clinica_id is None and not nome_medico:
            flash("Informe um médico ou acesse uma clínica para vincular o paciente corretamente.", "danger")
            return render_template("painel/cadastrar_paciente.html", dados=dados)

        for tentativa in range(2):
            try:
                paciente = _salvar_formulario(
                    request.form,
                    usuario_id=current_user.id,
                    clinica_id=clinica_id,
                    acao="Perfil criado via painel",
                )
                flash(f"Paciente {paciente.nome} cadastrado com sucesso.", "success")
                if request.form.get("acao") == "salvar_pdf":
                    return redirect(url_for("painel.exportar_pdf", pid=paciente.id))
                return redirect(url_for("painel.ver_paciente", pid=paciente.id))
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
                return render_template("painel/cadastrar_paciente.html", dados=dados)
            except IntegrityError:
                db.session.rollback()
                flash("Não foi possível salvar o perfil. Verifique se o CPF já existe e tente novamente.", "danger")
                return render_template("painel/cadastrar_paciente.html", dados=dados)
            except (OperationalError, InterfaceError) as exc:
                db.session.rollback()
                current_app.logger.warning(
                    "Falha transitória ao salvar formulário interno. tentativa=%s",
                    tentativa + 1,
                    exc_info=exc,
                )
                if tentativa == 0:
                    continue
                flash(
                    "Houve uma instabilidade temporária ao salvar o cadastro. Os dados continuam preenchidos para nova tentativa.",
                    "danger",
                )
                return render_template("painel/cadastrar_paciente.html", dados=dados)
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception("Erro inesperado ao salvar cadastro interno de paciente.")
                flash(
                    "Não foi possível concluir o cadastro agora. Os dados continuam preenchidos para nova tentativa.",
                    "danger",
                )
                return render_template("painel/cadastrar_paciente.html", dados=dados)

    return render_template("painel/cadastrar_paciente.html", dados=dados)


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

    busca = request.args.get("q", "").strip()

    base_pacientes = scoped_pacientes(Paciente.query, current_user).filter(
        Paciente.excluido_em.is_(None),
        Paciente.concluido_em.isnot(None),
    ).options(selectinload(Paciente.medico))
    if busca:
        base_pacientes = base_pacientes.filter(_filtro_busca_paciente(busca))

    pacientes_sem_medico = (
        base_pacientes
        .filter(Paciente.medico_id.is_(None))
        .order_by(Paciente.concluido_em.desc())
        .all()
    )

    pacientes_por_medico = (
        base_pacientes
        .filter(Paciente.medico_id.isnot(None))
        .order_by(Paciente.concluido_em.desc())
        .all()
    )
    mapa_pacientes = defaultdict(list)
    ultimo_por_medico = {}
    for p in pacientes_por_medico:
        mapa_pacientes[p.medico_id].append(p)
        ultimo_por_medico.setdefault(p.medico_id, p.concluido_em)

    medicos = {
        m.id: m
        for m in Medico.query.filter(Medico.id.in_(mapa_pacientes.keys())).all()
    }
    grupos = []
    for medico_id, _ in sorted(ultimo_por_medico.items(), key=lambda item: item[1], reverse=True):
        medico = medicos.get(medico_id)
        if medico:
            grupos.append({"medico": medico, "pacientes": mapa_pacientes[medico_id]})

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


_AGENDA_POR_PAGINA = 15


@bp.route("/agendamentos")
@login_required
def agendamentos():
    busca = request.args.get("q", "").strip()
    try:
        pagina = max(1, int(request.args.get("pagina", 1)))
    except (TypeError, ValueError):
        pagina = 1

    query = _agendamento_query().filter(
        Agendamento.status == "agendado",
        Agendamento.excluido_em.is_(None),
        Agendamento.concluido_em.is_(None),
    )
    if busca:
        query = query.filter(_filtro_busca_agendamento(busca))

    query = query.order_by(Agendamento.agendado_para.asc(), Agendamento.id.asc())
    total = query.count()
    total_paginas = max(1, -(-total // _AGENDA_POR_PAGINA))  # ceil sem import
    pagina = min(pagina, total_paginas)
    agendamentos_lista = query.offset((pagina - 1) * _AGENDA_POR_PAGINA).limit(_AGENDA_POR_PAGINA).all()

    pacientes_para_agenda = (
        scoped_pacientes(Paciente.query, current_user)
        .options(load_only(Paciente.id, Paciente.nome, Paciente.telefone, Paciente.cpf))
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
        pagina=pagina,
        total_paginas=total_paginas,
        total=total,
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
        .options(load_only(Paciente.id, Paciente.nome, Paciente.telefone, Paciente.cpf))
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
        margem_y = 24
        area_largura = largura - (margem_x * 2)
        topo = altura - margem_y

        def clean(valor):
            if valor in (None, ""):
                return "-"
            return str(valor)

        def fmt_data(dt):
            return dt.strftime("%d/%m/%Y") if dt else "-"

        def calcular_idade(dt_nascimento):
            if not dt_nascimento:
                return ""
            hoje = datetime.now().date()
            idade = hoje.year - dt_nascimento.year
            if (hoje.month, hoje.day) < (dt_nascimento.month, dt_nascimento.day):
                idade -= 1
            return str(max(idade, 0))

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

        # ── Ficha de Atendimento (estilo cartão físico para impressão) ────────
        ficha_x = margem_x
        ficha_w = area_largura
        linha_h = 22
        pad_x = 8
        fsize = 10

        y_ficha_topo = topo

        # Calcula altura total da ficha: 10 linhas de dados + medicamento + observacoes (4 linhas)
        ficha_h = 15 * linha_h + 10

        # Verifica se cabe na página; se não, cria nova página
        if y_ficha_topo - ficha_h < margem_y:
            c.showPage()
            y_ficha_topo = altura - margem_y

        # Borda externa
        c.setStrokeColor(colors.HexColor("#111111"))
        c.setLineWidth(0.9)
        c.rect(ficha_x, y_ficha_topo - ficha_h, ficha_w, ficha_h, fill=0, stroke=1)

        y = y_ficha_topo - linha_h + 4

        def linha_sep(y_pos):
            c.setStrokeColor(colors.HexColor("#111111"))
            c.setLineWidth(0.8)
            c.line(ficha_x, y_pos, ficha_x + ficha_w, y_pos)

        def campo_ficha(x, y_pos, label, valor, col_end, cor_label=None, destaque_valor=False):
            """Desenha label: valor — ou sublinhado tracejado se vazio."""
            c.setFillColor(cor_label or colors.HexColor("#1a1a2e"))
            c.setFont("Helvetica-Bold", fsize)
            c.drawString(x + pad_x, y_pos, f"{label}:")
            lw = c.stringWidth(f"{label}:", "Helvetica-Bold", fsize)
            val_x = x + pad_x + lw + 3
            available = col_end - val_x - pad_x
            if valor:
                val_size = 11
                c.setFillColor(colors.HexColor("#000000"))
                c.setFont("Helvetica", val_size)
                txt = valor
                while c.stringWidth(txt, "Helvetica", val_size) > available and len(txt) > 1:
                    txt = txt[:-1]
                if txt != valor:
                    txt = txt[:-1] + "…"

                if destaque_valor:
                    txt_w = c.stringWidth(txt, "Helvetica", val_size)
                    c.setFillColor(colors.HexColor("#FFF7C2"))
                    c.roundRect(val_x - 2, y_pos - 2, txt_w + 4, val_size + 3, 2, fill=1, stroke=0)

                c.setFillColor(colors.HexColor("#000000"))
                c.drawString(val_x, y_pos, txt)
            else:
                c.setStrokeColor(colors.HexColor("#111111"))
                c.setLineWidth(0.8)
                c.line(val_x, y_pos - 1, col_end - pad_x, y_pos - 1)

        mid = ficha_x + ficha_w / 2
        t1  = ficha_x + ficha_w / 3
        t2  = ficha_x + 2 * ficha_w / 3
        end = ficha_x + ficha_w

        # Linha 1: NOME
        campo_ficha(ficha_x, y, "NOME", clean(paciente.nome), end, destaque_valor=True)
        linha_sep(y - 6); y -= linha_h

        # Linha 2: Endereço
        end_str = f"{paciente.endereco}, {paciente.numero or 's/n'}" if paciente.endereco else ""
        campo_ficha(ficha_x, y, "End", end_str, end)
        linha_sep(y - 6); y -= linha_h

        # Linha 3: Bairro | Cidade | CEP
        campo_ficha(ficha_x, y, "Bairro", paciente.bairro or "", t1)
        campo_ficha(t1,       y, "Cidade",  paciente.cidade  or "", t2)
        campo_ficha(t2,       y, "CEP",     paciente.cep     or "", end)
        linha_sep(y - 6); y -= linha_h

        # Linha 4: Telefone
        campo_ficha(ficha_x, y, "Telefone", paciente.telefone or "", end)
        linha_sep(y - 6); y -= linha_h

        # Linha 5: RG | CPF
        campo_ficha(ficha_x, y, "RG", paciente.rg or "", mid)
        campo_ficha(mid, y, "CPF", paciente.cpf or "", end)
        linha_sep(y - 6); y -= linha_h

        # Linha 6: Data Nasc. | Idade
        campo_ficha(ficha_x, y, "Data Nasc.", fmt_data(paciente.data_nascimento), mid)
        campo_ficha(mid, y, "Idade", calcular_idade(paciente.data_nascimento), end)
        linha_sep(y - 6); y -= linha_h

        # Linha 7: Profissão | Indicação | Estado Civil
        campo_ficha(ficha_x, y, "Profissão", paciente.profissao or "", t1)
        campo_ficha(t1, y, "Indicação", paciente.indicacao or "", t2)
        campo_ficha(t2, y, "Estado Civil", paciente.estado_civil or "", end)
        linha_sep(y - 6); y -= linha_h

        # Linha 8: Data da Primeira Consulta (branco) | E-mail
        campo_ficha(ficha_x, y, "Data da primeira consulta", "", mid)
        campo_ficha(mid,      y, "E-mail", paciente.email or "",  end)
        linha_sep(y - 6); y -= linha_h

        # Linha 9: Convênio | N° | Validade
        campo_ficha(ficha_x, y, "Convênio", paciente.convenio_nome or "", t1)
        campo_ficha(t1, y, "N°", paciente.convenio_numero or "", t2)
        campo_ficha(t2, y, "Validade", fmt_data(paciente.convenio_validade), end)
        linha_sep(y - 6); y -= linha_h

        # Linha 10: Faz uso de algum medicamento (rótulo vermelho, campo branco)
        campo_ficha(ficha_x, y, "Faz uso de algum medicamento", "",
                    end, cor_label=colors.HexColor("#CC0000"))
        linha_sep(y - 6); y -= linha_h

        # Linha 11: Observações
        campo_ficha(ficha_x, y, "Observações", "", end)
        linha_sep(y - 6); y -= linha_h

        # 4 linhas em branco para observações manuais
        for _ in range(4):
            linha_sep(y - 6)
            y -= linha_h

        c.save()
        buffer.seek(0)
    except Exception:
        flash("Falha ao gerar PDF do paciente.", "danger")
        return redirect(url_for("painel.ver_paciente", pid=pid))

    response = make_response(buffer.getvalue())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["X-PDF-Layout-Version"] = "2026-06-19-v2"
    nome_arquivo = _nome_arquivo_pdf_paciente(paciente)
    response.headers["Content-Disposition"] = (
        f"attachment; filename=\"{nome_arquivo}\"; filename*=UTF-8''{quote(nome_arquivo)}"
    )
    return response


@bp.route("/formulario-em-branco/pdf")
@login_required
def formulario_em_branco_pdf():
    """Gera PDF do formulário de cadastro em branco para preenchimento manual."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib import colors
    except ImportError:
        flash("Dependência ReportLab não encontrada.", "danger")
        return redirect(url_for("painel.index"))

    buffer = BytesIO()
    try:
        c = canvas.Canvas(buffer, pagesize=A4)
        largura, altura = A4
        margem_x = 36
        margem_y = 36
        area_largura = largura - (margem_x * 2)
        topo = altura - margem_y

        fsize = 10
        linha_h = 22
        pad_x = 8
        ficha_x = margem_x
        ficha_w = area_largura

        # Header
        c.setFillColor(colors.HexColor("#4A9ACB"))
        c.roundRect(margem_x, topo - 70, area_largura, 58, 12, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(margem_x + 16, topo - 36, "Formulário de Cadastro de Paciente")

        # Logo/nome da clínica
        clinica = current_user.clinica
        if clinica:
            if clinica.logo_path:
                import os as _os
                from flask import current_app
                logo_abs = _os.path.join(current_app.static_folder, clinica.logo_path.lstrip("/\\"))
                if _os.path.isfile(logo_abs):
                    try:
                        from reportlab.lib.utils import ImageReader
                        img = ImageReader(logo_abs)
                        iw, ih = img.getSize()
                        escala = min(125 / iw, 50 / ih, 1.0)
                        dw, dh = iw * escala, ih * escala
                        c.drawImage(logo_abs, margem_x + area_largura - dw - 10, topo - 12 - dh,
                                    width=dw, height=dh, mask="auto")
                    except Exception:
                        pass
            nome_clinica = clinica.nome_impresso or clinica.nome
            c.setFillColor(colors.HexColor("#4A9ACB"))
            c.setFont("Helvetica-Bold", 8)
            label = nome_clinica[:50]
            tw = c.stringWidth(label, "Helvetica-Bold", 8)
            c.drawString(margem_x + area_largura - tw - 10, topo - 78, label)

        def linha_sep(y_pos):
            c.setStrokeColor(colors.HexColor("#111111"))
            c.setLineWidth(0.8)
            c.line(ficha_x, y_pos, ficha_x + ficha_w, y_pos)

        def campo(x, y_pos, label, col_end):
            c.setFillColor(colors.HexColor("#1a1a2e"))
            c.setFont("Helvetica-Bold", fsize)
            c.drawString(x + pad_x, y_pos, f"{label}:")
            lw = c.stringWidth(f"{label}:", "Helvetica-Bold", fsize)
            val_x = x + pad_x + lw + 3
            c.setStrokeColor(colors.HexColor("#111111"))
            c.setLineWidth(0.8)
            c.line(val_x, y_pos - 1, col_end - pad_x, y_pos - 1)

        y_ficha_topo = topo - 92
        ficha_h = 26 + 17 * linha_h + 10 + linha_h + 8 * linha_h

        # Borda externa
        c.setStrokeColor(colors.HexColor("#111111"))
        c.setLineWidth(0.9)
        c.rect(ficha_x, y_ficha_topo - ficha_h, ficha_w, ficha_h, fill=0, stroke=1)

        # Título
        c.setFillColor(colors.HexColor("#4A9ACB"))
        c.rect(ficha_x, y_ficha_topo - 26, ficha_w, 26, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(ficha_x + pad_x, y_ficha_topo - 18, "Ficha de Atendimento")

        y = y_ficha_topo - 26 - linha_h + 4
        mid = ficha_x + ficha_w / 2
        t1  = ficha_x + ficha_w / 3
        t2  = ficha_x + 2 * ficha_w / 3
        end = ficha_x + ficha_w

        # Linha 1: NOME | MÃE
        campo(ficha_x, y, "NOME",   mid)
        campo(mid,      y, "Mãe",   end)
        linha_sep(y - 6); y -= linha_h

        # Linha 2: Endereço
        campo(ficha_x, y, "End", end)
        linha_sep(y - 6); y -= linha_h

        # Linha 3: Bairro | Cidade | CEP
        campo(ficha_x, y, "Bairro", t1)
        campo(t1,       y, "Cidade", t2)
        campo(t2,       y, "CEP",    end)
        linha_sep(y - 6); y -= linha_h

        # Linha 4: Tel.Res | Cel
        campo(ficha_x, y, "Tel.Res", mid)
        campo(mid,      y, "Cel",    end)
        linha_sep(y - 6); y -= linha_h

        # Linha 5: RG | Data Nascimento | Idade
        campo(ficha_x, y, "RG",              t1)
        campo(t1,       y, "Data Nascimento", t2)
        campo(t2,       y, "Idade",           end)
        linha_sep(y - 6); y -= linha_h

        # Linha 6: CPF | Profissão
        campo(ficha_x, y, "CPF",      mid)
        campo(mid,      y, "Profissão", end)
        linha_sep(y - 6); y -= linha_h

        # Linha 7: Indicação | Est. Civil
        campo(ficha_x, y, "Indicação",  mid)
        campo(mid,      y, "Est. Civil", end)
        linha_sep(y - 6); y -= linha_h

        # Linha 8: Data primeira consulta | E-mail
        campo(ficha_x, y, "Data da primeira consulta", mid)
        campo(mid,      y, "E-mail",                   end)
        linha_sep(y - 6); y -= linha_h

        # Linha 9: Convênio | N° | Validade
        campo(ficha_x, y, "Convênio", t1)
        campo(t1,       y, "N°",       t2)
        campo(t2,       y, "Validade", end)
        linha_sep(y - 6); y -= linha_h

        # Linha 10: Médico
        campo(ficha_x, y, "Médico", end)
        linha_sep(y - 6); y -= linha_h

        # Linha 11: Faz uso de algum medicamento
        c.setFillColor(colors.HexColor("#CC0000"))
        c.setFont("Helvetica-Bold", fsize)
        label_med = "Faz uso de algum medicamento:"
        c.drawString(ficha_x + pad_x, y, label_med)
        lw2 = c.stringWidth(label_med, "Helvetica-Bold", fsize)
        c.setStrokeColor(colors.HexColor("#111111"))
        c.setLineWidth(0.8)
        c.line(ficha_x + pad_x + lw2 + 3, y - 1, end - pad_x, y - 1)
        linha_sep(y - 6); y -= linha_h

        # Linhas extras para medicamentos
        for _ in range(3):
            linha_sep(y - 6)
            y -= linha_h

        # Anotações
        campo(ficha_x, y, "Anotações", end)
        linha_sep(y - 6); y -= linha_h

        # 8 linhas em branco
        for _ in range(8):
            linha_sep(y - 6)
            y -= linha_h

        c.save()
        buffer.seek(0)
    except Exception:
        flash("Falha ao gerar PDF do formulário em branco.", "danger")
        return redirect(url_for("painel.index"))

    response = make_response(buffer.getvalue())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = "attachment; filename=formulario_em_branco.pdf"
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
