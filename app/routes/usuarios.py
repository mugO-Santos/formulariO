from flask import Blueprint, abort, render_template, request, flash, redirect, url_for
import os, uuid
from werkzeug.utils import secure_filename
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from app.extensions import db
from app.models import Clinica, Cargo, Medico, Usuario, Log
from app.decorators import nivel_minimo, superadmin_required
from app.scope import pode_acessar_usuario, scoped_medicos, scoped_usuarios, sincronizar_clinica_pacientes_do_medico

bp = Blueprint("usuarios", __name__, url_prefix="/painel/usuarios")


@bp.route("/")
@login_required
@nivel_minimo(0)
def index():
    usuarios = scoped_usuarios(Usuario.query.filter_by(ativo=True), current_user).order_by(Usuario.nome).all()
    cargos = Cargo.query.order_by(Cargo.nivel).all()
    if current_user.acesso_global:
        clinicas = Clinica.query.filter_by(ativo=True).order_by(Clinica.nome).all()
        medicos = Medico.query.filter_by(ativo=True).order_by(Medico.nome).all()
    else:
        clinicas = [current_user.clinica] if current_user.clinica else []
        medicos = scoped_medicos(Medico.query.filter_by(ativo=True), current_user).order_by(Medico.nome).all()
    return render_template(
        "painel/usuarios.html",
        usuarios=usuarios,
        cargos=cargos,
        clinicas=clinicas,
        medicos=medicos,
    )


@bp.route("/novo", methods=["POST"])
@login_required
@nivel_minimo(0)
def novo():
    nome = request.form.get("nome", "").strip()
    senha = request.form.get("senha", "")
    cargo_id = request.form.get("cargo_id")
    clinica_id_raw = request.form.get("clinica_id", "").strip()

    if not nome or len(senha) < 6 or not cargo_id:
        flash("Nome, senha (mín. 6 caracteres) e cargo são obrigatórios.", "danger")
        return redirect(url_for("usuarios.index"))

    cargo = Cargo.query.get_or_404(int(cargo_id))

    # Apenas nível 0 pode criar cargos de nível 0
    if cargo.nivel == 0 and current_user.nivel != 0:
        flash("Sem permissão para criar usuários Admin.", "danger")
        return redirect(url_for("usuarios.index"))

    if Usuario.query.filter_by(nome=nome).first():
        flash("Nome de usuário já existe.", "danger")
        return redirect(url_for("usuarios.index"))

    clinica_id = None
    if current_user.is_superadmin:
        if not clinica_id_raw:
            flash("Selecione a clínica do usuário.", "danger")
            return redirect(url_for("usuarios.index"))
        clinica_id = Clinica.query.get_or_404(int(clinica_id_raw)).id
    else:
        clinica_id = current_user.clinica_id

    db.session.add(Usuario(
        nome=nome,
        senha_hash=generate_password_hash(senha),
        cargo_id=cargo.id,
        clinica_id=clinica_id,
    ))
    db.session.commit()
    flash(f"Usuário '{nome}' criado.", "success")
    return redirect(url_for("usuarios.index"))


@bp.route("/nova-clinica", methods=["POST"])
@login_required
@superadmin_required
def nova_clinica():
    nome = request.form.get("nome", "").strip()
    medico_id_raw = request.form.get("medico_responsavel_id", "").strip()
    eh_hospital = bool(request.form.get("eh_hospital"))

    if not nome:
        flash("Nome da clínica é obrigatório.", "danger")
        return redirect(url_for("usuarios.index"))

    if Clinica.query.filter_by(nome=nome).first():
        flash("Já existe uma clínica com esse nome.", "danger")
        return redirect(url_for("usuarios.index"))

    clinica = Clinica(nome=nome, eh_hospital=eh_hospital)
    db.session.add(clinica)
    db.session.flush()

    if medico_id_raw:
        medico = Medico.query.get_or_404(int(medico_id_raw))
        clinica.medico_responsavel_id = medico.id
        medico.clinica_id = clinica.id
        sincronizar_clinica_pacientes_do_medico(medico)

    db.session.add(Log(usuario_id=current_user.id, acao=f"Clínica cadastrada: {nome}"))
    db.session.commit()
    flash(f"Clínica '{nome}' criada.", "success")
    return redirect(url_for("usuarios.index"))


@bp.route("/clinica/<int:cid>/editar", methods=["POST"])
@login_required
@superadmin_required
def editar_clinica(cid):
    clinica = Clinica.query.get_or_404(cid)
    nome = request.form.get("nome", "").strip()
    medico_id_raw = request.form.get("medico_responsavel_id", "").strip()
    eh_hospital = bool(request.form.get("eh_hospital"))

    if not nome:
        flash("Nome da clínica é obrigatório.", "danger")
        return redirect(url_for("usuarios.index"))

    nome_existente = Clinica.query.filter(Clinica.nome == nome, Clinica.id != cid).first()
    if nome_existente:
        flash("Já existe outra clínica com esse nome.", "danger")
        return redirect(url_for("usuarios.index"))

    clinica.nome = nome
    clinica.eh_hospital = eh_hospital
    clinica.medico_responsavel_id = None
    if medico_id_raw:
        medico = Medico.query.get_or_404(int(medico_id_raw))
        clinica.medico_responsavel_id = medico.id
        medico.clinica_id = clinica.id
        sincronizar_clinica_pacientes_do_medico(medico)

    db.session.add(Log(usuario_id=current_user.id, acao=f"Clínica editada: {clinica.nome}"))
    db.session.commit()
    flash(f"Clínica '{clinica.nome}' atualizada.", "success")
    return redirect(url_for("usuarios.index"))


@bp.route("/<int:uid>/excluir", methods=["POST"])
@login_required
@nivel_minimo(0)
def excluir(uid):
    usuario = Usuario.query.get_or_404(uid)
    if not pode_acessar_usuario(current_user, usuario):
        abort(404)
    if usuario.id == current_user.id:
        flash("Você não pode excluir a si mesmo.", "danger")
        return redirect(url_for("usuarios.index"))
    if usuario.is_superadmin and not current_user.is_superadmin:
        flash("Sem permissão para excluir superadmin.", "danger")
        return redirect(url_for("usuarios.index"))
    usuario.ativo = False
    db.session.commit()
    flash(f"Usuário '{usuario.nome}' desativado.", "warning")
    return redirect(url_for("usuarios.index"))


@bp.route("/novo-cargo", methods=["POST"])
@login_required
@superadmin_required
def novo_cargo():
    nome = request.form.get("nome", "").strip()
    nivel = request.form.get("nivel", "").strip()
    if not nome or nivel not in ("0", "1", "2"):
        flash("Nome e nível (0, 1 ou 2) são obrigatórios.", "danger")
        return redirect(url_for("usuarios.index"))
    if Cargo.query.filter_by(nome=nome).first():
        flash("Cargo já existe.", "danger")
        return redirect(url_for("usuarios.index"))
    db.session.add(Cargo(nome=nome, nivel=int(nivel)))
    db.session.commit()
    flash(f"Cargo '{nome}' criado.", "success")
    return redirect(url_for("usuarios.index"))


_LOGO_ALLOWED = {"png", "jpg", "jpeg", "gif", "webp"}
_LOGO_MAX_BYTES = 2 * 1024 * 1024  # 2 MB


def _redirect_back(default_endpoint="painel.index"):
    destino = request.referrer
    if destino:
        return redirect(destino)
    return redirect(url_for(default_endpoint))


@bp.route("/clinica/logo", methods=["POST"])
@login_required
@nivel_minimo(0)
def atualizar_logo_clinica():
    if current_user.is_superadmin or not current_user.clinica_id:
        flash("Acesse esta função como admin de uma clínica.", "danger")
        return _redirect_back("painel.meu_perfil")

    clinica = Clinica.query.get_or_404(current_user.clinica_id)
    nome_impresso = request.form.get("nome_impresso", "").strip() or None
    clinica.nome_impresso = nome_impresso

    arquivo = request.files.get("logo")
    if arquivo and arquivo.filename:
        ext = arquivo.filename.rsplit(".", 1)[-1].lower()
        if ext not in _LOGO_ALLOWED:
            flash("Formato inválido. Use PNG, JPG, GIF ou WEBP.", "danger")
            return _redirect_back("painel.meu_perfil")
        arquivo.stream.seek(0, 2)
        tamanho = arquivo.stream.tell()
        arquivo.stream.seek(0)
        if tamanho > _LOGO_MAX_BYTES:
            flash("Imagem muito grande. Máximo permitido: 2 MB.", "danger")
            return _redirect_back("painel.meu_perfil")
        from flask import current_app
        logo_dir = os.path.join(current_app.static_folder, "logos")
        os.makedirs(logo_dir, exist_ok=True)
        # Remove logo anterior se existir
        if clinica.logo_path:
            caminho_antigo = os.path.join(current_app.static_folder, clinica.logo_path.lstrip("/"))
            if os.path.isfile(caminho_antigo):
                os.remove(caminho_antigo)
        nome_arquivo = f"clinica_{clinica.id}_{uuid.uuid4().hex[:8]}.{ext}"
        caminho = os.path.join(logo_dir, secure_filename(nome_arquivo))
        arquivo.save(caminho)
        clinica.logo_path = f"logos/{secure_filename(nome_arquivo)}"

    db.session.add(Log(usuario_id=current_user.id, acao="Atualizou logo/nome da clínica"))
    db.session.commit()
    flash("Configurações da clínica atualizadas.", "success")
    return _redirect_back("painel.meu_perfil")
