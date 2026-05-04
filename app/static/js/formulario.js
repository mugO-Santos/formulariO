// Modal LGPD
const btnAbrirLgpd = document.getElementById('btn-abrir-lgpd');
const btnFecharLgpd = document.getElementById('btn-fechar-lgpd');
const modalLgpd = document.getElementById('modal-lgpd');
if (btnAbrirLgpd) {
  btnAbrirLgpd.addEventListener('click', () => modalLgpd.classList.remove('hidden'));
}
if (btnFecharLgpd) {
  btnFecharLgpd.addEventListener('click', () => modalLgpd.classList.add('hidden'));
}
if (modalLgpd) {
  modalLgpd.addEventListener('click', (e) => {
    if (e.target === modalLgpd) modalLgpd.classList.add('hidden');
  });
}

// Busca CEP via ViaCEP
const btnCep = document.getElementById('btn-busca-cep');
if (btnCep) {
  btnCep.addEventListener('click', async () => {
    const cep = document.getElementById('cep').value.replace(/\D/g, '');
    if (cep.length !== 8) { alert('CEP inválido.'); return; }
    try {
      const res = await fetch(`https://viacep.com.br/ws/${cep}/json/`);
      const data = await res.json();
      if (data.erro) { alert('CEP não encontrado.'); return; }
      const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
      set('endereco', data.logradouro);
      set('bairro', data.bairro);
      set('cidade', data.localidade);
    } catch { alert('Erro ao buscar CEP.'); }
  });
}

// Máscara CPF
const cpfInput = document.getElementById('cpf');
if (cpfInput) {
  cpfInput.addEventListener('input', () => {
    let v = cpfInput.value.replace(/\D/g, '').slice(0, 11);
    v = v.replace(/(\d{3})(\d)/, '$1.$2')
         .replace(/(\d{3})(\d)/, '$1.$2')
         .replace(/(\d{3})(\d{1,2})$/, '$1-$2');
    cpfInput.value = v;
  });
}

// Máscara Telefone
const telInput = document.getElementById('telefone');
if (telInput) {
  telInput.addEventListener('input', () => {
    let v = telInput.value.replace(/\D/g, '').slice(0, 11);
    if (v.length <= 10) v = v.replace(/(\d{2})(\d{4})(\d{0,4})/, '($1) $2-$3');
    else                v = v.replace(/(\d{2})(\d{5})(\d{0,4})/, '($1) $2-$3');
    telInput.value = v;
  });
}

// Máscara CEP
const cepInput = document.getElementById('cep');
if (cepInput) {
  cepInput.addEventListener('input', () => {
    let v = cepInput.value.replace(/\D/g, '').slice(0, 8);
    v = v.replace(/(\d{5})(\d)/, '$1-$2');
    cepInput.value = v;
  });
}

// Toggle visibilidade de senha
const btnVerSenha = document.getElementById('btn-ver-senha');
if (btnVerSenha) {
  btnVerSenha.addEventListener('click', () => {
    const inp = document.getElementById('senha');
    inp.type = inp.type === 'password' ? 'text' : 'password';
  });
}
