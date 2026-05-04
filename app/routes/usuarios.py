from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from app.extensions import db
from app.models import Usuario, Cargo
from app.decorators import nivel_minimo

bp = Blueprint("usuarios", __name__, url_prefix="/painel/usuarios")


@bp.route("/")
@login_required
@nivel_minimo(1)
def index():
    usuarios = Usuario.query.filter_by(ativo=True).order_by(Usuario.nome).all()
    cargos = Cargo.query.order_by(Cargo.nivel).all()
    return render_template("painel/usuarios.html", usuarios=usuarios, cargos=cargos)


@bp.route("/novo", methods=["POST"])
@login_required
@nivel_minimo(1)
def novo():
    nome = request.form.get("nome", "").strip()
    senha = request.form.get("senha", "")
    cargo_id = request.form.get("cargo_id")

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

    db.session.add(Usuario(
        nome=nome,
        senha_hash=generate_password_hash(senha),
        cargo_id=cargo.id,
    ))
    db.session.commit()
    flash(f"Usuário '{nome}' criado.", "success")
    return redirect(url_for("usuarios.index"))


@bp.route("/<int:uid>/excluir", methods=["POST"])
@login_required
@nivel_minimo(1)
def excluir(uid):
    usuario = Usuario.query.get_or_404(uid)
    if usuario.id == current_user.id:
        flash("Você não pode excluir a si mesmo.", "danger")
        return redirect(url_for("usuarios.index"))
    if usuario.nivel == 0 and current_user.nivel != 0:
        flash("Sem permissão para excluir usuários Admin.", "danger")
        return redirect(url_for("usuarios.index"))
    usuario.ativo = False
    db.session.commit()
    flash(f"Usuário '{usuario.nome}' desativado.", "warning")
    return redirect(url_for("usuarios.index"))


@bp.route("/novo-cargo", methods=["POST"])
@login_required
@nivel_minimo(1)
def novo_cargo():
    nome = request.form.get("nome", "").strip()
    nivel = request.form.get("nivel", "").strip()
    if not nome or nivel not in ("0", "1", "2"):
        flash("Nome e nível (0, 1 ou 2) são obrigatórios.", "danger")
        return redirect(url_for("usuarios.index"))
    if int(nivel) == 0 and current_user.nivel != 0:
        flash("Apenas Admin pode criar cargos de nível 0.", "danger")
        return redirect(url_for("usuarios.index"))
    if Cargo.query.filter_by(nome=nome).first():
        flash("Cargo já existe.", "danger")
        return redirect(url_for("usuarios.index"))
    db.session.add(Cargo(nome=nome, nivel=int(nivel)))
    db.session.commit()
    flash(f"Cargo '{nome}' criado.", "success")
    return redirect(url_for("usuarios.index"))
