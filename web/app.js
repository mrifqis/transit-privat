const byId = id => document.getElementById(id);
const status = byId('status');
const workspace = byId('workspace');
const preview = byId('preview');
let deadline;
let displayedId;
let expiryTimers = [];

function clearExpiryTimers() {
  expiryTimers.forEach(timer => clearTimeout(timer));
  expiryTimers = [];
}

function clearPreview() {
  displayedId = null;
  preview.value = '';
  preview.hidden = true;
  byId('preview-label').hidden = true;
}

function locked() {
  clearExpiryTimers();
  clearTimeout(deadline);
  workspace.hidden = true;
  byId('login').hidden = false;
  byId('lock').hidden = true;
  byId('send').reset();
  byId('items').replaceChildren();
  clearPreview();
}

async function request(url, method = 'GET', body) {
  const response = await fetch(url, {
    method, body, headers: {'X-Transit-Request': '1'}
  });
  if (!response.ok) {
    if (response.status === 401 && url !== '/login') locked();
    throw Error({
      400: 'Periksa teks, file, dan masa simpan.',
      401: url === '/login' ? 'Kode salah, kedaluwarsa, atau sudah dipakai.' : 'Sesi terkunci.',
      404: 'Kiriman sudah kedaluwarsa atau dihapus.',
      413: 'Batas ukuran 256 KiB untuk teks dan 25 MiB untuk file.',
      429: 'Terlalu banyak percobaan. Coba lagi dalam beberapa menit.',
      507: 'Penyimpanan penuh. Hapus beberapa kiriman atau tunggu masa simpannya habis.'
    }[response.status] || 'Permintaan gagal.');
  }
  if (url !== '/logout') {
    clearTimeout(deadline);
    deadline = setTimeout(locked, 900000);
  }
  return response;
}

async function run(action) {
  status.textContent = '';
  try { await action(); }
  catch (error) { status.textContent = error.message; }
}

function button(label, action) {
  const element = document.createElement('button');
  element.textContent = label;
  element.onclick = () => run(action);
  return element;
}

async function load() {
  const response = await request('/items');
  const data = await response.json();
  byId('login').hidden = true;
  byId('lock').hidden = false;
  workspace.hidden = false;
  const list = byId('items');
  clearExpiryTimers();
  list.replaceChildren();
  if (!data.some(item => item.id === displayedId)) clearPreview();
  if (!data.length) list.textContent = 'Belum ada kiriman.';
  for (const item of data) {
    const url = '/items/' + item.id;
    const row = document.createElement('div');
    row.className = 'row';
    const detail = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = item.name;
    const expires = document.createElement('small');
    expires.textContent = 'Kedaluwarsa ' + new Date(item.expires * 1000).toLocaleString('id-ID');
    detail.append(title, document.createElement('br'), expires);
    const actions = document.createElement('div');
    actions.className = 'actions';
    if (item.kind === 'text') {
      actions.append(button('Buka', async () => {
        const text = await (await request(url)).text();
        displayedId = item.id;
        preview.value = text;
        preview.hidden = false;
        byId('preview-label').hidden = false;
        preview.focus();
      }), button('Salin', async () => {
        const text = await (await request(url)).text();
        try {
          await navigator.clipboard.writeText(text);
          status.textContent = 'Teks disalin.';
        } catch {
          displayedId = item.id;
          preview.value = text;
          preview.hidden = false;
          byId('preview-label').hidden = false;
          preview.select();
          status.textContent = 'Tekan Ctrl+C untuk menyalin teks yang dipilih.';
        }
      }));
    } else {
      const link = document.createElement('a');
      link.className = 'action';
      link.href = url;
      link.download = item.name;
      link.textContent = 'Unduh';
      actions.append(link);
    }
    actions.append(button('Hapus sekarang', async () => {
      await request(url, 'DELETE');
      await load();
    }));
    row.append(detail, actions);
    list.append(row);
    expiryTimers.push(setTimeout(() => {
      row.remove();
      if (displayedId === item.id) clearPreview();
      if (!list.childElementCount) list.textContent = 'Belum ada kiriman.';
    }, Math.max(0, item.expires * 1000 - Date.now())));
  }
}

byId('login').onsubmit = event => {
  event.preventDefault();
  const code = byId('otp').value;
  byId('otp').value = '';
  run(async () => {
    await request('/login', 'POST', code);
    await load();
  });
};
byId('lock').onclick = () => run(async () => {
  await request('/logout', 'POST');
  locked();
});
byId('send').onsubmit = event => {
  event.preventDefault();
  run(async () => {
    const text = byId('text').value;
    const file = byId('file').files[0];
    if (!text && !file) throw Error('Isi teks atau pilih file.');
    const save = byId('save');
    save.disabled = true;
    const minutes = byId('minutes').value;
    async function send(kind, name, body) {
      await request('/items?' + new URLSearchParams({kind, name, minutes}), 'POST', body);
    }
    try {
      if (text) {
        await send('text', byId('name').value, text);
        byId('text').value = '';
        byId('name').value = '';
      }
      if (file) {
        await send('file', file.name, file);
        byId('file').value = '';
      }
      status.textContent = 'Kiriman tersimpan.';
    } finally {
      save.disabled = false;
      if (!workspace.hidden) await load();
    }
  });
};
load().catch(error => {
  locked();
  if (error.message !== 'Sesi terkunci.') status.textContent = error.message;
});
