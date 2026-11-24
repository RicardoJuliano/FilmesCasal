'use strict';
/* Filmes a Dois — frontend puro. Rotas conforme CONTRATO.md */

const KEY = 'filmes-a-dois';
const $app = document.getElementById('app');
const $nav = document.getElementById('nav');
const $top = document.getElementById('topbar');
const $toast = document.getElementById('toast');

const S = {
  session: null,   // {code, member_id, token, name}
  couple: null,    // {code, me, members}
  options: null,
  tab: 'recs',
  poll: null,
  seq: 0,          // invalida renders assíncronos antigos
};

/* ---------- utilidades ---------- */
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'text') el.textContent = v;
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(kid));
  }
  return el;
}

function loadSession() {
  try {
    const s = JSON.parse(localStorage.getItem(KEY));
    if (s && s.code && s.token && s.member_id) return s;
  } catch (e) { /* sem storage */ }
  return null;
}
function saveSession(s) {
  S.session = s;
  try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) { /* ignora */ }
}
function clearSession() {
  S.session = null; S.couple = null;
  try { localStorage.removeItem(KEY); } catch (e) { /* ignora */ }
}

let toastTimer;
function toast(msg) {
  $toast.textContent = msg;
  $toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $toast.classList.remove('show'), 2600);
}

class ApiError extends Error {
  constructor(msg, status) { super(msg); this.status = status; }
}

async function api(method, path, body) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (S.session) { headers['X-Code'] = S.session.code; headers['X-Token'] = S.session.token; }
  let res;
  try {
    res = await fetch(path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch (e) {
    throw new ApiError('Sem conexão com o servidor. Verifique sua internet e tente de novo.', 0);
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* corpo vazio ou inválido */ }
  if (!res.ok) {
    const msg = (data && data.error) || 'Algo deu errado. Tente novamente em instantes.';
    throw new ApiError(msg, res.status);
  }
  return data || {};
}

/* trata erro de tela: sessão inválida volta ao início */
function handleError(e, box) {
  if (e instanceof ApiError && (e.status === 401 || e.status === 404) && S.session) {
    clearSession();
    stopPoll();
    renderWelcome('Sua sessão expirou. Entre novamente com o código do casal.');
    return;
  }
  const msg = e && e.message ? e.message : 'Algo deu errado.';
  if (box) { box.textContent = msg; box.hidden = false; } else toast(msg);
}

function stopPoll() { if (S.poll) { clearInterval(S.poll); S.poll = null; } }

function setView(node, { nav = true } = {}) {
  S.seq++;
  stopPoll();
  $app.replaceChildren(h('div', { class: 'screen' }, node));
  $app.classList.toggle('nonav', !nav);
  $top.hidden = false;
  $nav.hidden = !nav;
  window.scrollTo(0, 0);
  $app.focus({ preventScroll: true });
  if (nav) renderNav();
}

function loading(text) {
  return h('div', { class: 'center' }, h('div', { class: 'spinner', role: 'progressbar', 'aria-label': 'Carregando' }), h('p', { class: 'muted', text: text || 'Carregando…' }));
}

function errorBox() { return h('div', { class: 'error', role: 'alert', hidden: true }); }

function inviteUrl(code) { return location.origin + '/?convite=' + encodeURIComponent(code); }

function stars(value, onPick, small) {
  const wrap = h('div', { class: 'stars' + (small ? ' sm' : ''), role: 'group', 'aria-label': 'Nota de 1 a 5 estrelas' });
  for (let i = 1; i <= 5; i++) {
    wrap.append(h('button', {
      type: 'button', class: 'star' + (i <= value ? ' on' : ''),
      'aria-label': i + (i === 1 ? ' estrela' : ' estrelas'), 'aria-pressed': String(i === value),
      onclick: () => onPick(i),
    }, '★'));
  }
  return wrap;
}

function logoImg(src) {
  const img = h('img', { src, alt: '' });
  img.addEventListener('error', () => img.remove());
  return img;
}

function poster(m) {
  if (m.poster_url) {
    const img = h('img', { class: 'poster', src: m.poster_url, alt: 'Capa de ' + m.title, decoding: 'async' });
    img.addEventListener('error', () => img.replaceWith(h('div', { class: 'poster ph', role: 'img', 'aria-label': 'Sem capa' }, '🎬')));
    return img;
  }
  return h('div', { class: 'poster ph', role: 'img', 'aria-label': 'Sem capa' }, '🎬');
}

function providers(list) {
  if (!list || !list.length) return null;
  return h('div', { class: 'prov', 'aria-label': 'Onde assistir' },
    list.map(p => p.logo_url
      ? h('img', { src: p.logo_url, alt: p.name, title: p.name, loading: 'lazy' })
      : h('span', { class: 'pn', text: p.name })));
}

function metaLine(m) {
  const parts = [];
  if (m.year) parts.push(m.year);
  if (m.runtime) parts.push(m.runtime + ' min');
  if (m.genres && m.genres.length) parts.push(m.genres.slice(0, 3).join(', '));
  return parts.join(' · ');
}

/* ---------- navegação ---------- */
const NAV = [
  ['recs', '🍿', 'Recomendações'],
  ['lista', '📋', 'Lista'],
  ['avaliar', '⭐', 'Avaliar'],
  ['perfil', '👤', 'Perfil'],
];
function renderNav() {
  $nav.replaceChildren(...NAV.map(([id, ic, label]) => h('button', {
    type: 'button', 'aria-current': S.tab === id ? 'page' : false,
    onclick: () => go(id),
  }, h('span', { class: 'ic', 'aria-hidden': 'true', text: ic }), h('span', { text: label }))));
}
function go(tab) {
  S.tab = tab;
  ({ recs: renderRecs, lista: renderLista, avaliar: renderAvaliar, perfil: renderPerfil })[tab]();
}

/* ---------- 1. boas-vindas ---------- */
function renderWelcome(notice) {
  const params = new URLSearchParams(location.search);
  const invite = (params.get('convite') || '').trim().toUpperCase();
  const err = errorBox();
  if (notice) { err.textContent = notice; err.hidden = false; }

  const nameInput = h('input', { type: 'text', id: 'nome', maxlength: '40', autocomplete: 'given-name', placeholder: 'Ex.: Ana' });
  const codeInput = h('input', { type: 'text', id: 'codigo', maxlength: '6', autocapitalize: 'characters', autocomplete: 'off', placeholder: 'K7P2QX', value: invite });
  const buttons = [];

  async function submit(kind) {
    err.hidden = true;
    const name = nameInput.value.trim();
    if (!name) { err.textContent = 'Diga seu nome para continuar.'; err.hidden = false; nameInput.focus(); return; }
    let body = { name };
    if (kind === 'join') {
      const code = codeInput.value.trim().toUpperCase();
      if (!code) { err.textContent = 'Digite o código do casal.'; err.hidden = false; codeInput.focus(); return; }
      body = { code, name };
    }
    buttons.forEach(b => b.disabled = true);
    try {
      const r = await api('POST', kind === 'join' ? '/api/couple/join' : '/api/couple', body);
      saveSession({ code: r.code, member_id: r.member_id, token: r.token, name });
      if (invite) history.replaceState(null, '', location.pathname);
      if (kind === 'create') renderInvite(); else boot();
    } catch (e) {
      buttons.forEach(b => b.disabled = false);
      handleError(e, err);
    }
  }

  const createBtn = h('button', { type: 'button', class: 'btn primary block', onclick: () => submit('create') }, 'Criar nosso casal');
  const joinBtn = h('button', { type: 'button', class: 'btn primary block', onclick: () => submit('join') }, 'Entrar no casal');
  buttons.push(createBtn, joinBtn);

  const nameField = h('div', null, h('label', { for: 'nome', text: 'Seu nome' }), nameInput);
  const joinField = h('div', null, h('label', { for: 'codigo', text: 'Código do casal' }), codeInput);

  const content = invite
    ? [h('p', { class: 'muted', text: 'Você foi convidado(a)! Diga seu nome e entre para receber as mesmas recomendações.' }),
       h('div', { class: 'panel stack' }, nameField, joinField, joinBtn),
       h('div', { class: 'divider', text: 'ou' }),
       h('p', { class: 'muted', style: 'text-align:center' }, 'Prefere começar um casal novo? ',
         h('a', { href: location.pathname, style: 'color:var(--gold)' }, 'Criar casal'))]
    : [h('div', { class: 'panel stack' }, nameField, createBtn),
       h('div', { class: 'divider', text: 'ou entre com um código' }),
       h('div', { class: 'panel stack' }, joinField, joinBtn)];

  setView(h('div', null,
    h('div', { class: 'hero' },
      h('div', { class: 'big', 'aria-hidden': 'true', text: '🎬' }),
      h('h1', { text: 'Filmes a Dois' }),
      h('p', { class: 'muted', text: 'Vocês respondem, a gente escolhe o filme da noite. As mesmas recomendações para o casal.' })),
    err, ...content), { nav: false });
  $top.hidden = true;
}

/* ---------- link de convite ---------- */
function renderInvite() {
  const code = S.session.code;
  const url = inviteUrl(code);
  const copy = async () => {
    try { await navigator.clipboard.writeText(url); toast('Link copiado!'); }
    catch (e) {
      const ta = h('textarea', { style: 'position:fixed;opacity:0' }, url);
      document.body.append(ta); ta.select();
      try { document.execCommand('copy'); toast('Link copiado!'); } catch (e2) { toast('Copie o link manualmente.'); }
      ta.remove();
    }
  };
  const share = async () => {
    try { await navigator.share({ title: 'Filmes a Dois', text: 'Vem escolher filmes comigo! Código: ' + code, url }); }
    catch (e) { /* cancelado */ }
  };
  setView(h('div', null,
    h('div', { class: 'hero' }, h('div', { class: 'big', 'aria-hidden': 'true', text: '💌' }),
      h('h2', { text: 'Casal criado!' }),
      h('p', { class: 'muted', text: 'Convide seu par: mande o link abaixo ou o código.' })),
    h('div', { class: 'panel stack' },
      h('div', { class: 'code', 'aria-label': 'Código do casal ' + code.split('').join(' '), text: code }),
      h('div', { class: 'linkbox', text: url }),
      h('div', { class: 'row' },
        h('button', { type: 'button', class: 'btn gold', style: 'flex:1', onclick: copy }, 'Copiar link'),
        navigator.share ? h('button', { type: 'button', class: 'btn', style: 'flex:1', onclick: share }, 'Compartilhar') : null)),
    h('div', { class: 'footer-actions' },
      h('button', { type: 'button', class: 'btn primary', onclick: boot }, 'Continuar'))), { nav: false });
}

/* ---------- 2. questionário ---------- */
const HUMORES = [['rir', '😂 Rir'], ['chorar', '😢 Chorar'], ['tensao', '😬 Tensão'], ['pensar', '🧠 Pensar'],
  ['aventura', '🧭 Aventura'], ['romance', '💕 Romance'], ['medo', '👻 Medo']];
const EPOCAS = [['classicos', 'Clássicos (antes de 1980)'], ['80_90', 'Anos 80 e 90'], ['2000_2010', '2000 a 2010'], ['recentes', 'Recentes (2011+)']];
const IDIOMAS = [['pt', 'Português'], ['en', 'Inglês'], ['es', 'Espanhol'], ['outros', 'Outros']];
const DURACOES = [[90, 'Até 1h30'], [120, 'Até 2h'], [150, 'Até 2h30'], [null, 'Tanto faz']];

function emptyQuiz() {
  return { generos_amo: [], generos_veto: [], humores: [], epocas: [], duracao_max: null, idiomas: [], streamings: [], nota_min: 6.0 };
}

async function renderQuiz() {
  setView(loading('Preparando o questionário…'), { nav: false });
  const seq = S.seq;
  let options, quiz;
  try {
    if (!S.options) S.options = await api('GET', '/api/options');
    options = S.options;
    const q = await api('GET', '/api/quiz');
    quiz = Object.assign(emptyQuiz(), q.quiz || {});
  } catch (e) { if (seq === S.seq) handleError(e); return; }
  if (seq !== S.seq) return;

  const toggle = (arr, v) => { const i = arr.indexOf(v); if (i >= 0) arr.splice(i, 1); else arr.push(v); };
  const chips = (items, selected, { max, cls, onChange } = {}) => {
    const box = h('div', { class: 'chips' });
    const paint = () => box.querySelectorAll('button').forEach(b => {
      const on = selected.includes(b._v);
      b.setAttribute('aria-pressed', String(on));
      b.disabled = !!(max && !on && selected.length >= max) || !!(b._block && b._block());
    });
    items.forEach(([v, label, logo]) => {
      const b = h('button', { type: 'button', class: 'chip ' + (cls || ''), onclick: () => { toggle(selected, v); paint(); if (onChange) onChange(); } },
        logo ? logoImg(logo) : null, label);
      b._v = v;
      if (cls === 'veto') b._block = () => quiz.generos_amo.includes(v);
      box.append(b);
    });
    paint();
    box._paint = paint;
    return box;
  };

  const genreItems = options.genres.map(g => [g.id, g.name]);
  let vetoBox;
  const amoBox = chips(genreItems, quiz.generos_amo, { max: 5, onChange: () => {
    quiz.generos_veto = quiz.generos_veto.filter(v => !quiz.generos_amo.includes(v));
    if (vetoBox) vetoBox._paint();
  } });
  vetoBox = chips(genreItems, quiz.generos_veto, { cls: 'veto' });

  const durBox = h('div', { class: 'chips', role: 'radiogroup', 'aria-label': 'Duração máxima' });
  const paintDur = () => durBox.querySelectorAll('button').forEach(b => b.setAttribute('aria-checked', String(b._v === quiz.duracao_max)));
  DURACOES.forEach(([v, label]) => {
    const b = h('button', { type: 'button', role: 'radio', class: 'chip', onclick: () => { quiz.duracao_max = v; paintDur(); paintChipsAria(durBox); } }, label);
    b._v = v; durBox.append(b);
  });
  function paintChipsAria(box) { box.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', b.getAttribute('aria-checked'))); }
  paintDur(); paintChipsAria(durBox);

  const notaOut = h('output', { class: 'code', style: 'letter-spacing:0;font-size:2rem', text: quiz.nota_min.toFixed(1) });
  const notaIn = h('input', { type: 'range', min: '5', max: '8', step: '0.5', value: String(quiz.nota_min), 'aria-label': 'Nota mínima',
    oninput: () => { quiz.nota_min = parseFloat(notaIn.value); notaOut.textContent = quiz.nota_min.toFixed(1); } });

  const provItems = options.providers.map(p => [p.id, p.name, p.logo_url]);

  const steps = [
    { t: 'Quais gêneros você ama?', d: 'Escolha até 5.', node: () => amoBox },
    { t: 'O que você não aguenta?', d: 'Esses gêneros ficam de fora das recomendações do casal.', node: () => vetoBox },
    { t: 'O que você quer sentir?', d: 'Escolha quantos quiser.', node: () => chips(HUMORES, quiz.humores) },
    { t: 'De que época?', d: 'Vazio = qualquer época.', node: () => chips(EPOCAS, quiz.epocas) },
    { t: 'Quanto tempo de filme?', d: 'Duração máxima.', node: () => durBox },
    { t: 'Em que idioma?', d: 'Vazio = qualquer idioma.', node: () => chips(IDIOMAS, quiz.idiomas) },
    { t: 'Quais streamings você assina?', d: 'Vazio = qualquer um.', node: () => chips(provItems, quiz.streamings) },
    { t: 'Qual a nota mínima?', d: 'Nota do TMDB, de 5 a 8.', node: () => h('div', { class: 'panel' }, notaOut, notaIn,
      h('p', { class: 'muted', style: 'text-align:center;margin:0', text: 'Quanto maior, mais exigente.' })) },
  ];

  let i = 0;
  const err = errorBox();
  function draw() {
    const st = steps[i];
    const last = i === steps.length - 1;
    const next = h('button', { type: 'button', class: 'btn primary', onclick: last ? finish : () => { i++; draw(); } }, last ? 'Concluir' : 'Próxima');
    const view = h('div', null,
      h('div', { class: 'stepinfo', text: `Etapa ${i + 1} de ${steps.length}` }),
      h('div', { class: 'progress', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': String(steps.length), 'aria-valuenow': String(i + 1) },
        h('div', { style: `width:${((i + 1) / steps.length) * 100}%` })),
      h('h2', { text: st.t }), h('p', { class: 'muted', text: st.d }),
      st.node(), err,
      h('div', { class: 'footer-actions' },
        i > 0 ? h('button', { type: 'button', class: 'btn ghost', onclick: () => { i--; draw(); } }, 'Voltar') : null, next));
    err.hidden = true;
    S.seq++;
    $app.replaceChildren(h('div', { class: 'screen' }, view));
    window.scrollTo(0, 0);
    $app.focus({ preventScroll: true });
  }
  async function finish(ev) {
    ev.target.disabled = true; err.hidden = true;
    try {
      await api('PUT', '/api/quiz', quiz);
      boot();
    } catch (e) { ev.target.disabled = false; handleError(e, err); }
  }
  draw();
}

/* ---------- 3. notas iniciais (seed) ---------- */
const MIN_RATINGS = 5;

async function renderSeed() {
  setView(loading('Buscando filmes para vocês avaliarem…'), { nav: false });
  const seq = S.seq;
  let movies;
  try { movies = (await api('GET', '/api/seed')).movies || []; }
  catch (e) { if (seq === S.seq) handleError(e); return; }
  if (seq !== S.seq) return;

  const me = S.couple.members.find(m => m.id === S.couple.me);
  const base = me ? me.ratings_count : 0;
  const local = {}; // tmdb_id -> 1..5 ou 0
  const counter = h('strong');
  const cont = h('button', { type: 'button', class: 'btn primary', onclick: () => boot() }, 'Ver recomendações');
  const hint = h('p', { class: 'muted' });
  const err = errorBox();

  const total = () => base + Object.values(local).filter(v => v > 0).length;
  function update() {
    const n = total();
    counter.textContent = Math.min(n, MIN_RATINGS) + ' de ' + MIN_RATINGS;
    cont.disabled = n < MIN_RATINGS;
    hint.textContent = n < MIN_RATINGS ? 'Avalie pelo menos ' + (MIN_RATINGS - n) + ' filme(s) para continuar.' : 'Pronto! Quanto mais notas, melhores as recomendações.';
  }

  async function rate(m, value, tile, starsHolder, noBtn) {
    err.hidden = true;
    const prev = local[m.tmdb_id] || 0;
    local[m.tmdb_id] = value;
    paintTile();
    update();
    try { await api('POST', '/api/rating', { tmdb_id: m.tmdb_id, rating: value }); }
    catch (e) { local[m.tmdb_id] = prev; paintTile(); update(); handleError(e, err); }
    function paintTile() {
      const v = local[m.tmdb_id] || 0;
      tile.classList.toggle('rated', v > 0);
      starsHolder.replaceChildren(stars(v, n => rate(m, n, tile, starsHolder, noBtn), true));
      noBtn.setAttribute('aria-pressed', String(m.tmdb_id in local && v === 0));
    }
  }

  const grid = h('div', { class: 'grid' });
  movies.forEach(m => {
    const holder = h('div');
    const tile = h('article', { class: 'tile' });
    const noBtn = h('button', { type: 'button', class: 'seen-no', 'aria-pressed': 'false', onclick: () => rate(m, 0, tile, holder, noBtn) }, 'Não vi');
    holder.append(stars(0, n => rate(m, n, tile, holder, noBtn), true));
    tile.append(poster(m), h('div', { class: 'info' },
      h('div', { class: 't', text: m.title }), h('div', { class: 'meta', text: m.year || '' }), holder, noBtn));
    grid.append(tile);
  });

  setView(h('div', null,
    h('h2', { text: 'Quais desses você já viu?' }),
    h('p', { class: 'muted' }, 'Dê de 1 a 5 estrelas ou marque "Não vi". Notas feitas: ', counter),
    hint, err, grid,
    h('div', { class: 'footer-actions', style: 'position:sticky;bottom:0;padding:.75rem 0;background:linear-gradient(transparent,var(--bg) 40%)' }, cont)), { nav: false });
  update();
}

/* ---------- 4/5. recomendações ---------- */
async function renderRecs(refresh) {
  S.tab = 'recs';
  setView(loading(refresh ? 'Atualizando recomendações…' : 'Procurando o filme perfeito…'));
  const seq = S.seq;
  let r;
  try { r = await api('GET', '/api/recommendations?refresh=' + (refresh ? 1 : 0)); }
  catch (e) { if (seq === S.seq) handleError(e); return; }
  if (seq !== S.seq) return;

  if (!r.ready) {
    const names = (r.waiting_for || []).join(' e ') || 'seu par';
    setView(h('div', { class: 'center' },
      h('div', { class: 'big pulse', 'aria-hidden': 'true', text: '⏳' }),
      h('h2', { text: 'Esperando ' + names }),
      h('p', { class: 'muted', text: 'Assim que responder o questionário, as recomendações aparecem aqui. Vou checar a cada 10 segundos.' }),
      h('p', { class: 'muted' }, 'Código do casal: ', h('strong', { text: S.session.code })),
      h('div', { class: 'row', style: 'justify-content:center' },
        h('button', { type: 'button', class: 'btn gold', onclick: () => navigator.clipboard && navigator.clipboard.writeText(inviteUrl(S.session.code)).then(() => toast('Link copiado!'), () => toast('Não consegui copiar.')) }, 'Copiar link de convite'),
        navigator.share ? h('button', { type: 'button', class: 'btn', onclick: () => navigator.share({ title: 'Filmes a Dois', url: inviteUrl(S.session.code) }).catch(() => {}) }, 'Compartilhar') : null)));
    const mySeq = S.seq;
    S.poll = setInterval(async () => {
      try {
        const x = await api('GET', '/api/recommendations?refresh=0');
        if (x.ready && mySeq === S.seq) renderRecs();
      } catch (e) { if (e.status === 401 || e.status === 404) handleError(e); }
    }, 10000);
    return;
  }

  const list = h('div', { class: 'cards' });
  const header = h('div', { class: 'row', style: 'justify-content:space-between;margin-bottom:1rem' },
    h('h2', { style: 'margin:0', text: 'Para vocês dois' }),
    h('button', { type: 'button', class: 'btn small', onclick: () => renderRecs(true) }, '↻ Atualizar'));
  const empty = h('div', { class: 'center', hidden: true },
    h('div', { class: 'big', 'aria-hidden': 'true', text: '🍿' }),
    h('p', { class: 'muted', text: 'Sem mais sugestões por agora. Avalie mais filmes e atualize!' }));
  const checkEmpty = () => { empty.hidden = list.children.length > 0; };

  (r.movies || []).forEach(m => list.append(recCard(m, checkEmpty, () => renderRecs())));
  setView(h('div', null, header, list, empty));
  checkEmpty();
}

function recCard(m, onGone, reload) {
  const card = h('article', { class: 'mcard' });
  const act = async (path, body, msg, after) => {
    card.querySelectorAll('button').forEach(b => b.disabled = true);
    try {
      await api('POST', path, body);
      toast(msg);
      card.classList.add('out');
      setTimeout(() => { card.remove(); onGone(); if (after) after(); }, 250);
    } catch (e) { card.querySelectorAll('button').forEach(b => b.disabled = false); handleError(e); }
  };
  const seen = Array.isArray(m.seen_by) ? m.seen_by : [];
  const myId = S.session && S.session.member_id;
  const mine = seen.find(x => x.member_id === myId);
  const rate = async n => {
    card.querySelectorAll('button').forEach(b => b.disabled = true);
    try {
      await api('POST', '/api/rating', { tmdb_id: m.tmdb_id, rating: n });
      toast('Anotado! O filme continua aqui até os dois verem.');
      reload();
    } catch (e) { card.querySelectorAll('button').forEach(b => b.disabled = false); handleError(e); }
  };
  const actions = h('div', { class: 'actions' });
  const showButtons = () => actions.replaceChildren(
    h('button', { type: 'button', class: 'btn primary', onclick: () => act('/api/watchlist', { tmdb_id: m.tmdb_id, action: 'add' }, 'Adicionado à lista!') }, '＋ Quero ver'),
    h('button', { type: 'button', class: 'btn gold', onclick: showRate }, mine ? '✎ Mudar nota' : '✔ Já vi'),
    h('button', { type: 'button', class: 'btn ghost', onclick: () => act('/api/dismiss', { tmdb_id: m.tmdb_id }, 'Ok, não mostro mais.') }, '✕ Não curti'));
  const showRate = () => {
    const picker = stars(mine ? mine.rating : 0, rate);
    actions.replaceChildren(h('div', { class: 'ratepick', role: 'group', 'aria-label': 'Que nota você dá para ' + m.title + '?' },
      h('span', { class: 'meta', text: 'Que nota você dá?' }), picker,
      h('button', { type: 'button', class: 'btn ghost small', onclick: showButtons }, 'Cancelar')));
    const first = picker.querySelector('button'); if (first) first.focus();
  };
  showButtons();
  const cls = m.match >= 75 ? '' : m.match >= 50 ? ' mid' : ' low';
  card.append(
    poster(m),
    h('div', { class: 'body' },
      h('div', { class: 'title', text: m.title }),
      h('div', { class: 'meta', text: metaLine(m) }),
      h('span', { class: 'match' + cls, 'aria-label': m.match + '% de match' }, '♥ ' + m.match + '% match'),
      seen.length ? h('div', { class: 'seenby' }, seen.map(x => h('span', { class: 'seen-badge',
        text: (x.member_id === myId ? 'Você já viu' : x.name + ' já viu') + (x.rating ? ' ★' + x.rating : '') }))) : null,
      m.reasons && m.reasons.length ? h('ul', { class: 'reasons' }, m.reasons.map(t => h('li', { text: t }))) : null,
      providers(m.providers)),
    actions);
  return card;
}

/* ---------- 6. lista do casal ---------- */
let listaTab = 'quero_ver';

async function renderLista() {
  S.tab = 'lista';
  setView(loading('Abrindo a lista…'));
  const seq = S.seq;
  let items;
  try {
    items = (await api('GET', '/api/watchlist')).items || [];
    S.couple = await api('GET', '/api/couple');
  } catch (e) { if (seq === S.seq) handleError(e); return; }
  if (seq !== S.seq) return;

  const names = {};
  S.couple.members.forEach(m => { names[m.id] = m.name; });
  const me = S.couple.me;
  const body = h('div', { class: 'cards' });
  const tabs = h('div', { class: 'tabs', role: 'tablist' });

  async function call(path, payload, msg) {
    try { await api('POST', path, payload); if (msg) toast(msg); renderLista(); }
    catch (e) { handleError(e); }
  }

  function paint() {
    const want = items.filter(i => i.status !== 'assistido');
    const seen = items.filter(i => i.status === 'assistido');
    tabs.replaceChildren(
      h('button', { type: 'button', role: 'tab', 'aria-selected': String(listaTab === 'quero_ver'), onclick: () => { listaTab = 'quero_ver'; paint(); } }, `Quero ver (${want.length})`),
      h('button', { type: 'button', role: 'tab', 'aria-selected': String(listaTab === 'assistido'), onclick: () => { listaTab = 'assistido'; paint(); } }, `Assistidos (${seen.length})`));
    const shown = listaTab === 'quero_ver' ? want : seen;
    if (!shown.length) {
      body.replaceChildren(h('div', { class: 'center' }, h('div', { class: 'big', 'aria-hidden': 'true', text: listaTab === 'quero_ver' ? '📋' : '🎞️' }),
        h('p', { class: 'muted', text: listaTab === 'quero_ver' ? 'Nada na lista ainda. Marque "Quero ver" nas recomendações.' : 'Nenhum filme assistido ainda.' })));
      return;
    }
    body.replaceChildren(...shown.map(m => {
      const card = h('article', { class: 'mcard' });
      const info = h('div', { class: 'body' },
        h('div', { class: 'title', text: m.title }),
        h('div', { class: 'meta', text: metaLine(m) }),
        providers(m.providers));
      const actions = h('div', { class: 'actions' });
      if (m.status !== 'assistido') {
        actions.append(
          h('button', { type: 'button', class: 'btn primary', onclick: () => call('/api/watchlist', { tmdb_id: m.tmdb_id, action: 'watched' }, 'Marcado como assistido! Dê sua nota.') }, '✔ Já assistimos'),
          h('button', { type: 'button', class: 'btn ghost danger', onclick: () => call('/api/watchlist', { tmdb_id: m.tmdb_id, action: 'remove' }, 'Removido da lista.') }, 'Remover'));
      } else {
        const r = m.ratings || {};
        const mine = r[me] || 0;
        info.append(h('div', { class: 'ratings' },
          S.couple.members.map(mem => h('div', null, (mem.id === me ? 'Você' : mem.name) + ': ',
            r[mem.id] ? h('b', { text: '★'.repeat(r[mem.id]) + ' ' + r[mem.id] + '/5' }) : h('span', { class: 'muted', text: 'ainda sem nota' })))));
        info.append(h('div', null, h('div', { class: 'meta', text: mine ? 'Sua nota:' : 'Dê sua nota:' }),
          stars(mine, n => call('/api/rating', { tmdb_id: m.tmdb_id, rating: n }, 'Nota salva!'), true)));
        actions.append(h('button', { type: 'button', class: 'btn ghost danger small', onclick: () => call('/api/watchlist', { tmdb_id: m.tmdb_id, action: 'remove' }, 'Removido da lista.') }, 'Remover da lista'));
      }
      card.append(poster(m), info, actions);
      return card;
    }));
  }
  setView(h('div', null, h('h2', { text: 'Nossa lista' }), tabs, body));
  paint();
}

/* ---------- 7. avaliar (buscar filme já visto) ---------- */
function renderAvaliar() {
  S.tab = 'avaliar';
  const err = errorBox();
  const results = h('div', { class: 'cards' });
  const input = h('input', { type: 'search', id: 'busca', placeholder: 'Ex.: Matrix', 'aria-label': 'Buscar filme', autocomplete: 'off' });
  const ratedLocal = {};

  async function search() {
    const q = input.value.trim();
    err.hidden = true;
    if (q.length < 2) { err.textContent = 'Digite pelo menos 2 letras.'; err.hidden = false; return; }
    results.replaceChildren(loading('Buscando…'));
    const seq = S.seq;
    try {
      const movies = (await api('GET', '/api/search?q=' + encodeURIComponent(q))).movies || [];
      if (seq !== S.seq) return;
      if (!movies.length) { results.replaceChildren(h('div', { class: 'center muted', text: 'Nenhum filme encontrado.' })); return; }
      results.replaceChildren(...movies.map(m => searchCard(m)));
    } catch (e) { results.replaceChildren(); handleError(e, err); }
  }

  function searchCard(m) {
    const holder = h('div');
    const paint = () => holder.replaceChildren(
      stars(ratedLocal[m.tmdb_id] || 0, n => rate(n), true),
      h('button', { type: 'button', class: 'seen-no', onclick: () => rate(0) }, 'Não vi'));
    async function rate(n) {
      try {
        await api('POST', '/api/rating', { tmdb_id: m.tmdb_id, rating: n });
        ratedLocal[m.tmdb_id] = n; paint();
        toast(n ? 'Nota salva!' : 'Nota removida.');
      } catch (e) { handleError(e); }
    }
    paint();
    return h('article', { class: 'mcard' }, poster(m),
      h('div', { class: 'body' }, h('div', { class: 'title', text: m.title }), h('div', { class: 'meta', text: metaLine(m) }),
        m.overview ? h('p', { class: 'synopsis', text: m.overview }) : null, holder));
  }

  setView(h('div', null,
    h('h2', { text: 'Avaliar um filme' }),
    h('p', { class: 'muted', text: 'Busque um filme que você já viu e dê sua nota. Isso afina as recomendações.' }),
    h('form', { class: 'row', style: 'flex-wrap:nowrap', onsubmit: ev => { ev.preventDefault(); search(); } },
      input, h('button', { type: 'submit', class: 'btn primary' }, 'Buscar')),
    err, h('div', { style: 'margin-top:1rem' }, results)));
}

/* ---------- perfil ---------- */
async function renderPerfil() {
  S.tab = 'perfil';
  setView(loading());
  const seq = S.seq;
  try { S.couple = await api('GET', '/api/couple'); }
  catch (e) { if (seq === S.seq) handleError(e); return; }
  if (seq !== S.seq) return;
  const url = inviteUrl(S.session.code);
  const members = S.couple.members;
  setView(h('div', null,
    h('h2', { text: 'Perfil' }),
    h('div', { class: 'panel stack' },
      h('div', null, h('div', { class: 'meta', text: 'Casal' }), h('div', { class: 'code', style: 'padding:.25rem 0', text: S.session.code })),
      h('ul', { style: 'margin:0;padding-left:1.1rem' }, members.map(m => h('li', null,
        (m.id === S.couple.me ? m.name + ' (você)' : m.name) + ' — ',
        h('span', { class: 'muted', text: (m.quiz_done ? 'questionário feito' : 'questionário pendente') + ', ' + m.ratings_count + ' notas' })))),
      members.length < 2 ? h('div', { class: 'linkbox', text: url }) : null,
      members.length < 2 ? h('button', { type: 'button', class: 'btn gold', onclick: () =>
        (navigator.share ? navigator.share({ title: 'Filmes a Dois', url }).catch(() => {}) : navigator.clipboard.writeText(url).then(() => toast('Link copiado!'), () => toast('Não consegui copiar.'))) },
        navigator.share ? 'Compartilhar convite' : 'Copiar link de convite') : null),
    h('div', { class: 'stack', style: 'margin-top:1.25rem' },
      h('button', { type: 'button', class: 'btn block', onclick: renderQuiz }, 'Refazer questionário'),
      h('button', { type: 'button', class: 'btn block ghost danger', onclick: () => {
        if (confirm('Sair deste aparelho? Você poderá voltar com o código do casal, mas precisará entrar de novo como novo membro se o casal já estiver cheio.')) {
          clearSession(); stopPoll(); history.replaceState(null, '', location.pathname); renderWelcome();
        } } }, 'Sair'))));
}

/* ---------- inicialização ---------- */
async function boot() {
  if (!S.session) { renderWelcome(); return; }
  setView(loading(), { nav: false });
  const seq = S.seq;
  try {
    S.couple = await api('GET', '/api/couple');
  } catch (e) { if (seq === S.seq) handleError(e); return; }
  if (seq !== S.seq) return;
  const me = S.couple.members.find(m => m.id === S.couple.me);
  if (!me) { clearSession(); renderWelcome('Não encontrei você neste casal. Entre novamente.'); return; }
  if (!me.quiz_done) return renderQuiz();
  if (me.ratings_count < MIN_RATINGS) return renderSeed();
  go(S.tab || 'recs');
}

S.session = loadSession();
if (S.session) {
  // convite com sessão ativa: mantém a sessão atual
  boot();
} else {
  renderWelcome();
}
