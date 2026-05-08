from sqlalchemy import and_, false, or_

from .extensions import db
from .models import Agendamento, Encaminhamento, Log, Medico, Paciente, Usuario


def clinica_escopo_id(usuario):
    if usuario is None or usuario.is_superadmin:
        return None
    return usuario.clinica_id


def usuario_sem_escopo(usuario):
    return usuario is not None and not usuario.is_superadmin and usuario.clinica_id is None


def filtro_paciente_clinica(clinica_id):
    return or_(
        filtro_paciente_origem_clinica(clinica_id),
        filtro_paciente_encaminhado_para_clinica(clinica_id),
    )


def filtro_paciente_origem_clinica(clinica_id):
    return or_(
        Paciente.clinica_id == clinica_id,
        and_(
            Paciente.clinica_id.is_(None),
            Paciente.medico.has(Medico.clinica_id == clinica_id),
        ),
    )


def filtro_paciente_encaminhado_para_clinica(clinica_id):
    return Paciente.encaminhamentos.any(
        and_(
            Encaminhamento.clinica_destino_id == clinica_id,
            Encaminhamento.status.in_(["enviado", "recebido", "em_andamento"]),
        )
    )


def scoped_pacientes(query, usuario):
    if usuario_sem_escopo(usuario):
        return query.filter(false())
    clinica_id = clinica_escopo_id(usuario)
    if clinica_id is None:
        return query
    return query.filter(filtro_paciente_clinica(clinica_id))


def scoped_medicos(query, usuario):
    if usuario_sem_escopo(usuario):
        return query.filter(false())
    clinica_id = clinica_escopo_id(usuario)
    if clinica_id is None:
        return query
    return query.filter(Medico.clinica_id == clinica_id)


def scoped_usuarios(query, usuario):
    if usuario_sem_escopo(usuario):
        return query.filter(false())
    clinica_id = clinica_escopo_id(usuario)
    if clinica_id is None:
        return query
    return query.filter(Usuario.clinica_id == clinica_id)


def scoped_logs(query, usuario):
    if usuario_sem_escopo(usuario):
        return query.filter(false())
    clinica_id = clinica_escopo_id(usuario)
    if clinica_id is None:
        return query
    return (
        query.outerjoin(Log.usuario)
        .outerjoin(Log.paciente)
        .filter(
            or_(
                Usuario.clinica_id == clinica_id,
                filtro_paciente_clinica(clinica_id),
            )
        )
    )


def scoped_agendamentos(query, usuario):
    if usuario_sem_escopo(usuario):
        return query.filter(false())
    clinica_id = clinica_escopo_id(usuario)
    if clinica_id is None:
        return query
    return query.filter(Agendamento.clinica_id == clinica_id)


def pode_acessar_medico(usuario, medico):
    if usuario_sem_escopo(usuario):
        return False
    clinica_id = clinica_escopo_id(usuario)
    return clinica_id is None or medico.clinica_id == clinica_id


def pode_acessar_usuario(usuario, alvo):
    if usuario_sem_escopo(usuario):
        return False
    clinica_id = clinica_escopo_id(usuario)
    return clinica_id is None or alvo.clinica_id == clinica_id


def pode_acessar_paciente(usuario, paciente):
    if usuario_sem_escopo(usuario):
        return False
    clinica_id = clinica_escopo_id(usuario)
    if clinica_id is None:
        return True
    return (
        paciente_da_clinica_origem(clinica_id, paciente)
        or paciente_foi_encaminhado_para(clinica_id, paciente)
    )


def paciente_da_clinica_origem(clinica_id, paciente):
    paciente_clinica_id = paciente.clinica_origem_id
    return paciente_clinica_id == clinica_id


def paciente_foi_encaminhado_para(clinica_id, paciente):
    return any(
        enc.clinica_destino_id == clinica_id
        and enc.status in ("enviado", "recebido", "em_andamento")
        for enc in paciente.encaminhamentos
    )


def pode_gerenciar_paciente(usuario, paciente):
    if usuario_sem_escopo(usuario):
        return False
    clinica_id = clinica_escopo_id(usuario)
    if clinica_id is None:
        return True
    return paciente_da_clinica_origem(clinica_id, paciente)


def sincronizar_clinica_pacientes_do_medico(medico):
    db.session.query(Paciente).filter(Paciente.medico_id == medico.id).update(
        {Paciente.clinica_id: medico.clinica_id},
        synchronize_session=False,
    )