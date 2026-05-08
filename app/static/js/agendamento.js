function preencherCamposAgendamento(selectId, nomeId, telefoneId, cpfId) {
  const select = document.getElementById(selectId);
  const nome = document.getElementById(nomeId);
  const telefone = document.getElementById(telefoneId);
  const cpf = document.getElementById(cpfId);
  if (!select || !nome || !telefone || !cpf) return;

  select.addEventListener("change", () => {
    const opt = select.options[select.selectedIndex];
    if (!opt || !opt.value) return;
    if (!nome.value.trim()) nome.value = opt.dataset.nome || "";
    if (!telefone.value.trim()) telefone.value = opt.dataset.telefone || "";
    if (!cpf.value.trim()) cpf.value = opt.dataset.cpf || "";
  });
}

preencherCamposAgendamento("paciente_id_agenda", "nome_paciente_agenda", "telefone_paciente_agenda", "cpf_paciente_agenda");
preencherCamposAgendamento("paciente_id_agenda_page", "nome_paciente_agenda_page", "telefone_paciente_agenda_page", "cpf_paciente_agenda_page");
preencherCamposAgendamento("paciente_id_agenda_edit", "nome_paciente_agenda_edit", "telefone_paciente_agenda_edit", "cpf_paciente_agenda_edit");
