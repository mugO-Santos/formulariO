from datetime import datetime, timezone
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from app.extensions import db
from app.models import Usuario, Log, Notificacao, Cargo

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("painel.index"))

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        senha = request.form.get("senha", "")

        usuario = Usuario.query.filter_by(nome=nome, ativo=True).first()

        if usuario and check_password_hash(usuario.senha_hash, senha):
            login_user(usuario)
            db.session.add(Log(usuario_id=usuario.id, acao="Login realizado"))
            db.session.commit()
            return redirect(url_for("painel.index"))

        flash("Nome ou senha incorretos.", "danger")

    return render_template("login.html")


@bp.route("/logout")
@login_required
def logout():
    db.session.add(Log(usuario_id=current_user.id, acao="Logout realizado"))
    db.session.commit()
    logout_user()
    return redirect(url_for("formulario.index"))


@bp.route("/esqueci-senha", methods=["POST"])
def esqueci_senha():
    nome = request.form.get("nome", "").strip()
    # Notifica todos os usuários de nível 0 e 1
    admins = (
        Usuario.query
        .join(Cargo)
        .filter(Cargo.nivel <= 1, Usuario.ativo == True)
        .all()
    )
    for a in admins:
        db.session.add(Notificacao(
            usuario_id=a.id,
            mensagem=f"Solicitação de redefinição de senha para o usuário: '{nome}'",
        ))
    db.session.commit()
    flash("Sua solicitação foi enviada ao administrador.", "info")
    return redirect(url_for("auth.login"))
