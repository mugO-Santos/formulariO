from datetime import datetime, timezone
from flask_login import UserMixin
from app.extensions import db


class Clinica(db.Model):
    __tablename__ = "clinicas"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), unique=True, nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    eh_hospital = db.Column(db.Boolean, default=False, nullable=False)
    medico_responsavel_id = db.Column(db.Integer, db.ForeignKey("medicos.id"), nullable=True)
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    usuarios = db.relationship("Usuario", back_populates="clinica")
    medicos = db.relationship("Medico", back_populates="clinica", foreign_keys="Medico.clinica_id")
    pacientes = db.relationship("Paciente", back_populates="clinica")
    encaminhamentos_recebidos = db.relationship("Encaminhamento", back_populates="clinica_destino")
    medico_responsavel = db.relationship("Medico", foreign_keys=[medico_responsavel_id], post_update=True)

    def __repr__(self):
        return f"<Clinica {self.nome}>"


class Cargo(db.Model):
    __tablename__ = "cargos"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), unique=True, nullable=False)
    nivel = db.Column(db.Integer, nullable=False)  # 0, 1 ou 2

    usuarios = db.relationship("Usuario", back_populates="cargo")

    def __repr__(self):
        return f"<Cargo {self.nome} nivel={self.nivel}>"


class Usuario(UserMixin, db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(80), unique=True, nullable=False)
    senha_hash = db.Column(db.String(256), nullable=False)
    cargo_id = db.Column(db.Integer, db.ForeignKey("cargos.id"), nullable=False)
    clinica_id = db.Column(db.Integer, db.ForeignKey("clinicas.id"), nullable=True)
    is_superadmin = db.Column(db.Boolean, default=False, nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    cargo = db.relationship("Cargo", back_populates="usuarios")
    clinica = db.relationship("Clinica", back_populates="usuarios")
    logs = db.relationship("Log", back_populates="usuario")
    notificacoes = db.relationship("Notificacao", back_populates="usuario")
    encaminhamentos_enviados = db.relationship("Encaminhamento", back_populates="enviado_por")

    @property
    def nivel(self):
        return self.cargo.nivel

    @property
    def acesso_global(self):
        return self.is_superadmin

    @property
    def admin_clinica(self):
        return self.nivel == 0

    def __repr__(self):
        return f"<Usuario {self.nome}>"


class Medico(db.Model):
    __tablename__ = "medicos"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    crm = db.Column(db.String(30), unique=True, nullable=False)
    clinica_id = db.Column(db.Integer, db.ForeignKey("clinicas.id"), nullable=True)
    ativo = db.Column(db.Boolean, default=True, nullable=False)

    clinica = db.relationship("Clinica", back_populates="medicos", foreign_keys=[clinica_id])
    pacientes = db.relationship("Paciente", back_populates="medico")

    def __repr__(self):
        return f"<Medico {self.nome} CRM={self.crm}>"


class Paciente(db.Model):
    __tablename__ = "pacientes"

    id = db.Column(db.Integer, primary_key=True)

    # Dados pessoais
    nome = db.Column(db.String(120), nullable=False)
    nome_mae = db.Column(db.String(120), nullable=False)
    cpf = db.Column(db.String(14), unique=True, nullable=False)
    rg = db.Column(db.String(20), nullable=True)
    data_nascimento = db.Column(db.Date, nullable=False)
    estado_civil = db.Column(db.String(20), nullable=False)
    profissao = db.Column(db.String(80), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    telefone = db.Column(db.String(20), nullable=False)

    # Endereço
    cep = db.Column(db.String(9), nullable=True)
    endereco = db.Column(db.String(150), nullable=True)
    numero = db.Column(db.String(10), nullable=True)
    bairro = db.Column(db.String(80), nullable=True)
    cidade = db.Column(db.String(80), nullable=True)

    # Pagamento
    forma_pagamento = db.Column(db.String(30), nullable=True)

    # Vínculo médico
    medico_id = db.Column(db.Integer, db.ForeignKey("medicos.id"), nullable=True)
    clinica_id = db.Column(db.Integer, db.ForeignKey("clinicas.id"), nullable=True)
    nome_medico_digitado = db.Column(db.String(120), nullable=True)  # texto original do formulário

    # Observações internas
    observacoes = db.Column(db.Text, nullable=True)

    # LGPD
    aceite_lgpd = db.Column(db.Boolean, default=False, nullable=False)
    aceite_lgpd_em = db.Column(db.DateTime, nullable=True)

    # Controle
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    excluido_em = db.Column(db.DateTime, nullable=True)  # soft delete
    concluido_em = db.Column(db.DateTime, nullable=True)  # marcado como concluído

    medico = db.relationship("Medico", back_populates="pacientes")
    clinica = db.relationship("Clinica", back_populates="pacientes")
    logs = db.relationship("Log", back_populates="paciente")
    encaminhamentos = db.relationship("Encaminhamento", back_populates="paciente", cascade="all, delete-orphan")

    @property
    def excluido(self):
        return self.excluido_em is not None

    @property
    def concluido(self):
        return self.concluido_em is not None

    @property
    def clinica_origem_id(self):
        if self.clinica_id is not None:
            return self.clinica_id
        if self.medico is not None:
            return self.medico.clinica_id
        return None

    def __repr__(self):
        return f"<Paciente {self.nome}>"


class Log(db.Model):
    __tablename__ = "logs"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey("pacientes.id"), nullable=True)
    acao = db.Column(db.String(200), nullable=False)
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    usuario = db.relationship("Usuario", back_populates="logs")
    paciente = db.relationship("Paciente", back_populates="logs")

    def __repr__(self):
        return f"<Log {self.acao} em {self.criado_em}>"


class Encaminhamento(db.Model):
    __tablename__ = "encaminhamentos"

    id = db.Column(db.Integer, primary_key=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey("pacientes.id"), nullable=False)
    clinica_destino_id = db.Column(db.Integer, db.ForeignKey("clinicas.id"), nullable=False)
    enviado_por_usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    status = db.Column(db.String(30), default="enviado", nullable=False)
    observacao = db.Column(db.Text, nullable=True)
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    atualizado_em = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    paciente = db.relationship("Paciente", back_populates="encaminhamentos")
    clinica_destino = db.relationship("Clinica", back_populates="encaminhamentos_recebidos")
    enviado_por = db.relationship("Usuario", back_populates="encaminhamentos_enviados")

    __table_args__ = (
        db.UniqueConstraint("paciente_id", "clinica_destino_id", name="uq_encaminhamento_paciente_destino"),
    )

    def __repr__(self):
        return f"<Encaminhamento paciente={self.paciente_id} destino={self.clinica_destino_id}>"


class Notificacao(db.Model):
    __tablename__ = "notificacoes"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    mensagem = db.Column(db.Text, nullable=False)
    lida = db.Column(db.Boolean, default=False, nullable=False)
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    usuario = db.relationship("Usuario", back_populates="notificacoes")

    def __repr__(self):
        return f"<Notificacao para usuario_id={self.usuario_id}>"
