from flask import Blueprint, render_template
from flask_login import login_required
from app.models import Log
from app.decorators import nivel_minimo

bp = Blueprint("logs", __name__, url_prefix="/painel/logs")


@bp.route("/")
@login_required
@nivel_minimo(1)
def index():
    logs = Log.query.order_by(Log.criado_em.desc()).limit(500).all()
    return render_template("painel/logs.html", logs=logs)
