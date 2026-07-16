const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const fmt = n => n == null ? '—' : Math.round(n).toLocaleString('fr-FR') + ' K';
const pct = n => n == null ? '—' : Number(n).toFixed(1) + ' %';
const parseMoney = value => {
  const clean = String(value ?? '').replace(/[\s\u00A0\u202F]/g, '').replace(/[^0-9.-]/g, '');
  if (!clean || clean === '-' || clean === '.') return null;
  const n = Number(clean); return Number.isFinite(n) ? n : null;
};
const moneyInputValue = value => value == null || value === '' ? '' : Math.round(Number(value)).toLocaleString('fr-FR');
function formatMoneyField(input) {
  const n = parseMoney(input.value);
  input.value = n == null ? '' : moneyInputValue(n);
}
function bindMoneyField(input, onChange) {
  input.type = 'text'; input.inputMode = 'numeric';
  input.addEventListener('focus', () => { const n=parseMoney(input.value); input.value=n==null?'':String(Math.round(n)); input.select(); });
  input.addEventListener('blur', () => { formatMoneyField(input); onChange?.(true); });
  input.addEventListener('input', () => onChange?.(false));
  formatMoneyField(input);
}
const esc = s => String(s ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const pageNames = {dashboard:'Dashboard',crafts:'Crafts',prices:'Prix HDV',shopping:'Liste de courses',workshop:'Atelier',opportunities:'Opportunités & Conseiller',priorities:'Prix prioritaires',scanner:'Scan HDV',history:'Historique',backup:'Sauvegarde'};
let craftIngredientFilter = 0;
let craftIngredientName = '';
let autoRefreshTimer = null;
let autoRefreshEnabled = true;
let autoRefreshSeconds = 30;
let autoSyncEnabled = true;

async function api(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error((await response.text()) || `Erreur ${response.status}`);
  return response.json();
}

function switchPage(target) {
  const page = typeof target === 'string' ? target : target.dataset.page;
  $$('.tab,.page').forEach(x => x.classList.remove('active'));
  $(`.tab[data-page="${page}"]`)?.classList.add('active');
  $('#' + page)?.classList.add('active');
  $('#pageTitle').textContent = pageNames[page] || 'Dofus Craft Manager';
  window.scrollTo({top:0,behavior:'smooth'});
  setTimeout(() => refreshVisiblePage(false), 20);
}
$$('.tab').forEach(b => b.onclick = () => switchPage(b));
$$('.go-page').forEach(b => b.onclick = () => switchPage(b.dataset.target));
$('#quickPrices').onclick = () => switchPage('prices');
$('#quickCrafts').onclick = () => openCraftRanking('profit');
function openCraftRanking(sort='profit') {
  craftIngredientFilter = 0; craftIngredientName = '';
  switchPage('crafts');
  $('#craftSearch').value = '';
  $('#craftCategory').value = '';
  $('#minLevel').value = 0;
  $('#maxLevel').value = 200;
  $('#craftSort').value = sort;
  $('#onlyComplete').checked = true;
  $('#onlyProfitable').checked = true;
  $$('[data-craft-view]').forEach(x => x.classList.toggle('active', x.dataset.craftView === 'profitable'));
  loadCrafts();
}

async function loadStatus() {
  const s = await api('/api/status');
  $('#sItems').textContent = Number(s.items || 0).toLocaleString('fr-FR');
  $('#sRecipes').textContent = Number(s.recipes || 0).toLocaleString('fr-FR');
  $('#sPrices').textContent = Number(s.prices || 0).toLocaleString('fr-FR');
  $('#priceCount').textContent = Number(s.prices || 0).toLocaleString('fr-FR');
  $('#syncStatus').textContent = s.message || 'Prêt';
  $('#syncProgress').style.width = `${s.status === 'running' ? Math.max(2, Number(s.percent || 0)) : 100}%`;
  $('#syncDot').style.background = s.status === 'running' ? 'var(--warn)' : 'var(--good)';
  $('#syncDot').style.boxShadow = `0 0 12px ${s.status === 'running' ? 'var(--warn)' : 'var(--good)'}`;
  $('#lastSync').textContent = s.last_sync ? `Dernière synchro : ${s.last_sync.replace('T',' ')}` : 'Aucune synchronisation';
  if (s.status === 'running') setTimeout(loadStatus, 1500);
  return s;
}

$('#sync').onclick = async () => {
  try { await api('/api/sync', {method:'POST'}); loadStatus(); }
  catch (e) { alert('Synchronisation impossible : ' + e.message); }
};

function craftRows(items) {
  const head = '<div class="row header"><span title="Nom de l’objet crafté">Objet</span><span title="Niveau de l’objet">Niveau</span><span title="Prix HDV saisi avant taxe">Vente brute</span><span title="Prix reçu après déduction de la taxe HDV">Vente nette</span><span title="Coût si tous les ingrédients sont fabriqués directement">Coût fabrication</span><span title="Coût le plus faible entre achat et fabrication imbriquée">Coût optimal</span><span title="Vente nette moins coût optimal">Bénéfice net</span><span title="Bénéfice net divisé par le coût optimal">ROI net</span></div>';
  if (!items.length) return head + '<div class="empty">Aucun résultat avec ces filtres.</div>';
  return head + items.map(x => `
    <div class="row craft-row" data-id="${x.id}" data-name="${esc(x.name)}">
      <span><b>${esc(x.name)}</b><br><small>${esc(x.subtype || x.category || '')} · ${esc(x.mode || 'prix incomplet')}</small></span>
      <span>${x.level ?? '—'}</span><span>${fmt(x.sale)}</span><span>${fmt(x.net_sale)}</span><span>${fmt(x.craft)}</span><span>${fmt(x.best)}</span>
      <span class="${x.profit > 0 ? 'good' : x.profit < 0 ? 'bad' : ''}">${fmt(x.profit)}</span><span>${pct(x.roi)}</span>
    </div>`).join('');
}

async function loadCrafts(target='#craftList', limit=500) {
  const params = new URLSearchParams({
    q: $('#craftSearch')?.value || '', category: $('#craftCategory')?.value || '',
    min_level: $('#minLevel')?.value || 0, max_level: $('#maxLevel')?.value || 200,
    sort: $('#craftSort')?.value || 'profit', complete: $('#onlyComplete')?.checked ? '1' : '0',
    profitable: $('#onlyProfitable')?.checked ? '1' : '0', ingredient_id: craftIngredientFilter || 0, limit
  });
  const data = await api('/api/crafts?' + params.toString());
  const banner = craftIngredientFilter ? `<div class="craft-context-banner"><span>Crafts utilisant <b>${esc(craftIngredientName)}</b></span><button id="clearIngredientFilter" class="secondary">Afficher tous les crafts</button></div>` : '';
  $(target).innerHTML = banner + craftRows(data);
  $('#clearIngredientFilter')?.addEventListener('click', () => { craftIngredientFilter=0; craftIngredientName=''; loadCrafts(); });
  $(target).querySelectorAll('.craft-row').forEach(row => row.onclick = () => openRecipe(row.dataset.id, row.dataset.name));
}

$('#craftGo').onclick = () => loadCrafts();
$('#craftSearch').onkeydown = e => { if (e.key === 'Enter') loadCrafts(); };
let craftTimer;
$('#craftSearch').oninput = () => { clearTimeout(craftTimer); craftTimer = setTimeout(() => loadCrafts(), 240); };
['craftCategory','minLevel','maxLevel','craftSort','onlyComplete','onlyProfitable'].forEach(id => $('#'+id).onchange = () => loadCrafts());
$$('[data-craft-view]').forEach(btn => btn.onclick = () => {
  $$('[data-craft-view]').forEach(x=>x.classList.remove('active'));
  btn.classList.add('active');
  const view=btn.dataset.craftView;
  $('#onlyComplete').checked = view !== 'all';
  $('#onlyProfitable').checked = view === 'profitable';
  $('#craftSort').value = view === 'missing' ? 'name' : 'profit';
  if (view === 'missing') { $('#onlyComplete').checked=false; $('#onlyProfitable').checked=false; }
  loadCrafts();
});

function treeHtml(node) {
  const total = node.best == null ? null : node.best * node.quantity;
  const children = (node.children || []).map(treeHtml).join('');
  return `<details open><summary><b>${esc(node.name)}</b> ×${node.quantity}<span>${fmt(total)}</span><small>${esc(node.mode || 'prix manquant')}</small></summary>${children ? `<div class="tree-children">${children}</div>` : ''}</details>`;
}

let currentRecipe = null;
async function openRecipe(id, name) {
  try {
    currentRecipe = {id:+id,name};
    const [recipe, tree] = await Promise.all([api('/api/recipe?id=' + id), api('/api/tree?id=' + id)]);
    $('#recipeTitle').textContent = name;
    const c = recipe.cost;
    $('#recipeSummary').innerHTML = `<div class="summary-grid"><div><small>Prix de vente</small><b>${fmt(recipe.sale)}</b></div><div><small>Taxe (${Number(recipe.tax_rate*100).toFixed(1)} %)</small><b class="bad">-${fmt(recipe.tax)}</b></div><div><small>Vente nette</small><b>${fmt(recipe.net_sale)}</b></div><div><small>Coût retenu</small><b>${fmt(c.best)}</b></div><div><small>Bénéfice net</small><b class="${recipe.profit>0?'good':recipe.profit<0?'bad':''}">${fmt(recipe.profit)}</b></div><div><small>ROI net</small><b>${pct(recipe.roi)}</b></div><div><small>Choix</small><b>${esc(c.mode || 'incomplet')}</b></div></div>`;
    const missing = recipe.ingredients.filter(x => x.buy == null);
    const ingredientRows = recipe.ingredients.map(x => {
      const ingredientName = x.name || '#' + x.ingredient_id;
      const bestLot = unitPrice(x.p1, x.p10, x.p100);
      const directCost = x.best == null ? null : x.best * x.quantity;
      const plan = x.purchase_plan || {};
      return `<div class="recipe-price-row" data-item-id="${x.ingredient_id}" data-item-name="${esc(ingredientName)}">
        <div class="recipe-item-cell"><b>${esc(ingredientName)}</b><small>Quantité nécessaire : ×${x.quantity} · ${esc(x.mode || 'incomplet')}</small></div>
        <input class="rp1 money-field" type="text" inputmode="numeric" placeholder="Prix x1" value="${moneyInputValue(x.p1)}" aria-label="Prix x1 de ${esc(ingredientName)}">
        <input class="rp10 money-field" type="text" inputmode="numeric" placeholder="Prix x10" value="${moneyInputValue(x.p10)}" aria-label="Prix x10 de ${esc(ingredientName)}">
        <input class="rp100 money-field" type="text" inputmode="numeric" placeholder="Prix x100" value="${moneyInputValue(x.p100)}" aria-label="Prix x100 de ${esc(ingredientName)}">
        <span class="recipe-best-lot"><b>${bestLot ? fmt(bestLot.value) : '—'}</b><small>${bestLot ? 'via '+bestLot.label : 'prix manquant'}</small></span>
        <span class="recipe-line-cost"><b>${fmt(directCost)}</b><small>coût retenu</small></span>
        <button class="open-price-item secondary">Prix HDV →</button>
        <details class="recipe-buy-details"><summary>Détail du plan d’achat</summary><div>${esc(plan.label || 'Aucun plan calculable')} · ${fmt(plan.cost)}</div></details>
      </div>`;
    }).join('');
    $('#recipeBody').innerHTML = recipe.ingredients.length ? `<div class="recipe-price-table">
      <div class="recipe-price-row header"><span>Ingrédient / quantité</span><span>Prix x1</span><span>Prix x10</span><span>Prix x100</span><span>Meilleur PU</span><span>Coût</span><span>Navigation</span></div>${ingredientRows}</div>` : '<div class="empty">Aucune recette trouvée.</div>';
    if (missing.length) {
      $('#recipeBody').insertAdjacentHTML('afterbegin', `<div class="missing-price-banner"><div><b>${missing.length} prix HDV manquant${missing.length > 1 ? 's' : ''}</b><small>Tu peux tous les saisir directement dans le tableau ci-dessous.</small></div><button id="openFirstMissing" class="secondary">Ouvrir le premier dans Prix HDV</button></div>`);
      $('#openFirstMissing').onclick = () => openItemInPrices(missing[0].name || String(missing[0].ingredient_id));
    }
    bindRecipePriceTable();
    $('#treeBody').innerHTML = treeHtml(tree);
    $('#recipeModal').classList.remove('hidden');
  } catch(e) { alert('Impossible de charger ce craft : ' + e.message); }
}
function openItemInPrices(name) {
  $('#recipeModal').classList.add('hidden');
  switchPage('prices');
  $('#priceSearch').value = name;
  $('#priceView').value = 'all';
  loadPrices(name).then(() => {
    const first = $('#priceList .price-grid[data-id] .price-input');
    first?.focus();
    $('#priceList')?.scrollIntoView({behavior:'smooth',block:'start'});
  });
}

function bindQuickPriceEditors() {
  $$('#recipeBody .quick-price').forEach(box => {
    box.querySelectorAll('.money-field').forEach(input => bindMoneyField(input));
    const save = box.querySelector('.save-quick-price');
    const open = box.querySelector('.open-price-item');
    open.onclick = () => openItemInPrices(box.dataset.itemName);
    save.onclick = async () => {
      const read = cls => parseMoney(box.querySelector(cls).value);
      const state = box.querySelector('.quick-price-state');
      save.disabled = true; state.textContent = 'Sauvegarde…'; box.querySelectorAll('.money-field').forEach(formatMoneyField);
      try {
        const result = await api('/api/prices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item_id:+box.dataset.itemId,p1:read('.qp1'),p10:read('.qp10'),p100:read('.qp100')})});
        if (!result.ok) throw new Error('Le serveur n’a pas confirmé la sauvegarde');
        state.textContent = '✓ Prix enregistré, recalcul en cours';
        await Promise.all([loadStatus(), loadDashboard(), loadCrafts()]);
        const recipe = currentRecipe;
        if (recipe) await openRecipe(recipe.id, recipe.name);
      } catch(e) {
        state.textContent = 'Erreur : ' + e.message;
      } finally { save.disabled = false; }
    };
  });
}

async function saveRecipePriceRow(row) {
  const read = cls => parseMoney(row.querySelector(cls).value);
  const result = await api('/api/prices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item_id:+row.dataset.itemId,p1:read('.rp1'),p10:read('.rp10'),p100:read('.rp100')})});
  if (!result.ok) throw new Error('Sauvegarde non confirmée');
}
function bindRecipePriceTable() {
  const rows = $$('#recipeBody .recipe-price-row[data-item-id]');
  rows.forEach(row => {
    row.querySelectorAll('.money-field').forEach(input => bindMoneyField(input));
    row.querySelector('.open-price-item').onclick = () => openItemInPrices(row.dataset.itemName);
  });
  const saveAll = $('#saveAllRecipePrices');
  const state = $('#recipeSaveState');
  saveAll.onclick = async () => {
    saveAll.disabled = true; state.textContent = `Sauvegarde de ${rows.length} ingrédient${rows.length>1?'s':''}…`; state.className='recipe-save-state';
    rows.forEach(row=>row.querySelectorAll('.money-field').forEach(formatMoneyField));
    try {
      for (const row of rows) await saveRecipePriceRow(row);
      state.textContent = '✓ Tous les prix sont enregistrés. Craft recalculé.'; state.className='recipe-save-state good';
      await Promise.all([loadStatus(),loadDashboard(),loadCrafts()]);
      const recipe = currentRecipe; if (recipe) await openRecipe(recipe.id, recipe.name);
    } catch(e) { state.textContent='Erreur : '+e.message; state.className='recipe-save-state bad'; }
    finally { saveAll.disabled=false; }
  };
}

$('#closeModal').onclick = () => $('#recipeModal').classList.add('hidden');
$('#recipeModal').onclick = e => { if (e.target.id === 'recipeModal') $('#recipeModal').classList.add('hidden'); };
document.addEventListener('keydown', e => { if(e.key === 'Escape') $('#recipeModal').classList.add('hidden'); });

const priceSaveTimers = new Map();
function unitPrice(p1,p10,p100) {
  const values = [p1 > 0 ? {value:p1,label:'x1'} : null,p10 > 0 ? {value:p10/10,label:'x10'} : null,p100 > 0 ? {value:p100/100,label:'x100'} : null].filter(Boolean);
  return values.length ? values.sort((a,b)=>a.value-b.value)[0] : null;
}
function priceRowHtml(x) {
  const best = unitPrice(x.p1,x.p10,x.p100);
  const icon = x.image ? `<img class="item-icon" src="${esc(x.image)}" loading="lazy" onerror="this.style.display='none'">` : '<div class="item-icon"></div>';
  const craftButton = x.is_craftable ? `<button class="view-item-craft" title="Voir la recette et la rentabilité">Voir le craft</button>` : '';
  const usesButton = Number(x.used_in_count||0) > 0 ? `<button class="view-used-crafts secondary" title="Voir les crafts qui utilisent cet objet">Utilisé dans ${Number(x.used_in_count).toLocaleString('fr-FR')}</button>` : '';
  return `<div class="price-grid" data-id="${x.id}" data-name="${esc(x.name)}" data-craftable="${x.is_craftable?1:0}"><button type="button" class="item-cell clickable-item item-name-link" title="${x.is_craftable?'Ouvrir le craft':'Voir les crafts utilisant cet objet'}" aria-label="Ouvrir ${esc(x.name)}">${icon}<span class="item-meta"><b>${esc(x.name)}</b><small>${esc(x.subtype || x.category || '')} · ID ${x.id}${x.updated_at ? ' · ' + esc(x.updated_at) : ''}</small></span></button><input class="price-input p1" type="text" inputmode="numeric" placeholder="—" value="${moneyInputValue(x.p1)}"><input class="price-input p10" type="text" inputmode="numeric" placeholder="—" value="${moneyInputValue(x.p10)}"><input class="price-input p100" type="text" inputmode="numeric" placeholder="—" value="${moneyInputValue(x.p100)}"><span class="unit-best">${best ? `<b>${fmt(best.value)}</b><small>via ${best.label}</small>` : '<b>—</b><small>prix manquant</small>'}</span><div class="price-actions">${craftButton}${usesButton}<button class="clear-price" title="Effacer les trois prix">Effacer</button></div></div>`;
}
async function savePriceRow(row, immediate=false) {
  const id = +row.dataset.id; clearTimeout(priceSaveTimers.get(id));
  const execute = async () => {
    const val = cls => parseMoney(row.querySelector(cls).value);
    row.classList.add('saving');
    try {
      await api('/api/prices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item_id:id,p1:val('.p1'),p10:val('.p10'),p100:val('.p100')})});
      const best = unitPrice(val('.p1'),val('.p10'),val('.p100'));
      row.querySelector('.unit-best').innerHTML = best ? `<b>${fmt(best.value)}</b><small>via ${best.label}</small>` : '<b>—</b><small>prix manquant</small>';
      row.classList.remove('saving'); row.classList.add('saved'); setTimeout(()=>row.classList.remove('saved'),800);
      $('#priceMessage').textContent = 'Prix sauvegardé · calculs actualisés'; setTimeout(()=>$('#priceMessage').textContent='',1600);
      await Promise.allSettled([loadStatus(),loadDashboard(),loadCrafts()]);
    } catch(e) { row.classList.remove('saving'); $('#priceMessage').textContent = 'Erreur : ' + e.message; }
  };
  if (immediate) execute(); else priceSaveTimers.set(id,setTimeout(execute,450));
}
async function loadPrices(query=null) {
  const q = query === null ? ($('#priceSearch')?.value || '') : query;
  const params = new URLSearchParams({q,view:$('#priceView')?.value || 'recent',category:$('#priceCategory')?.value || '',limit:'250'});
  const data = await api('/api/items?' + params.toString());
  $('#priceShown').textContent = data.length.toLocaleString('fr-FR');
  const head = '<div class="price-grid header"><span>Objet</span><span>Prix x1</span><span>Prix x10</span><span>Prix x100</span><span>Meilleur PU</span><span>Navigation</span></div>';
  $('#priceList').innerHTML = head + (data.length ? data.map(priceRowHtml).join('') : '<div class="empty">Aucun objet à afficher. Utilise la recherche ou change le filtre.</div>');
  $('#priceList').querySelectorAll('.price-grid[data-id]').forEach(row => {
    row.querySelectorAll('.price-input').forEach(input => bindMoneyField(input, immediate => savePriceRow(row, immediate)));
    row.querySelector('.clear-price').onclick = () => { row.querySelectorAll('.price-input').forEach(i=>i.value=''); savePriceRow(row,true); };
    const openOwnCraft = () => openRecipe(row.dataset.id, row.dataset.name);
    const openUses = () => openCraftsUsing(row.dataset.id, row.dataset.name);
    row.querySelector('.view-item-craft')?.addEventListener('click', e => { e.stopPropagation(); openOwnCraft(); });
    row.querySelector('.view-used-crafts')?.addEventListener('click', e => { e.stopPropagation(); openUses(); });
    row.querySelector('.item-name-link')?.addEventListener('click', e => {
      e.preventDefault();
      e.stopPropagation();
      if (Number(row.dataset.craftable)) openOwnCraft();
      else if (row.querySelector('.view-used-crafts')) openUses();
      else {
        $('#priceMessage').textContent = 'Cet objet n’a pas de recette et n’est utilisé dans aucun craft.';
        setTimeout(()=>$('#priceMessage').textContent='',2200);
      }
    });
  });
}
$('#priceGo').onclick = () => loadPrices();
$('#priceSearch').onkeydown = e => { if (e.key === 'Enter') loadPrices(); };
let priceTimer;
$('#priceSearch').oninput = () => { clearTimeout(priceTimer); priceTimer = setTimeout(() => loadPrices(), 220); };
$('#priceView').onchange = () => loadPrices();
$('#priceCategory').onchange = () => loadPrices();

function openCraftsUsing(itemId, itemName) {
  craftIngredientFilter = Number(itemId) || 0;
  craftIngredientName = itemName || `#${itemId}`;
  switchPage('crafts');
  $('#craftSearch').value = '';
  $('#onlyComplete').checked = false;
  $('#onlyProfitable').checked = false;
  $('#craftSort').value = 'profit';
  $$('.tab[data-page="crafts"]')?.[0];
  loadCrafts();
}

async function refreshVisiblePage(showMessage=true) {
  if (!autoRefreshEnabled) return;
  const active = document.activeElement;
  if (active && ['INPUT','TEXTAREA','SELECT'].includes(active.tagName)) return;
  if (!$('#recipeModal').classList.contains('hidden')) return;
  const page = $('.page.active')?.id;
  const jobs = [loadStatus()];
  if (page === 'dashboard') jobs.push(loadDashboard());
  else if (page === 'crafts') jobs.push(loadCrafts());
  else if (page === 'prices') jobs.push(loadPrices());
  else if (page === 'history' && typeof loadHistory === 'function') jobs.push(loadHistory());
  await Promise.allSettled(jobs);
  if (showMessage && page === 'prices') {
    $('#priceMessage').textContent = 'Actualisation automatique effectuée';
    setTimeout(()=>$('#priceMessage').textContent='',1200);
  }
}
function startAutoRefresh() {
  clearInterval(autoRefreshTimer);
  if (!autoRefreshEnabled) return;
  autoRefreshTimer = setInterval(() => refreshVisiblePage(false), Math.max(10, autoRefreshSeconds) * 1000);
}
async function maybeAutoSyncRecipes(status) {
  if (!autoSyncEnabled || !status || status.status === 'running') return;
  const last = status.last_sync ? new Date(status.last_sync) : null;
  const stale = !last || Number.isNaN(last.getTime()) || (Date.now() - last.getTime() > 24*60*60*1000);
  if (stale) {
    try { await api('/api/sync',{method:'POST'}); loadStatus(); } catch(e) { /* synchronisation déjà active ou hors ligne */ }
  }
}

async function loadCategories() {
  const rows = await api('/api/categories');
  const categories = [...new Set(rows.map(x => x.category).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'fr'));
  $('#craftCategory').innerHTML += categories.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join('');
}
async function loadDashboard() {
  const d = await api('/api/dashboard');
  $('#sProfitable').textContent = Number(d.profitable || 0).toLocaleString('fr-FR');
  $('#topCrafts').innerHTML = craftRows(d.top_profit || []);
  $('#topRoi').innerHTML = craftRows(d.top_roi || []);
  $$('#topCrafts .craft-row,#topRoi .craft-row').forEach(row => row.onclick = () => openRecipe(row.dataset.id, row.dataset.name));
}
function download(url) { const a=document.createElement('a'); a.href=url; document.body.appendChild(a); a.click(); a.remove(); }
$('#exportBtn').onclick = () => download('/api/export-prices');
$('#exportCsvBtn').onclick = () => download('/api/export-prices-csv');
$('#backupBtn').onclick = async () => { const r=await api('/api/backup'); $('#backupMessage').textContent='Sauvegarde créée : data/backups/' + r.file; };
async function loadSettings(){
  const s=await api('/api/settings');
  if ($('#taxEnabled')) $('#taxEnabled').checked=!!s.sale_tax_enabled;
  if ($('#taxRate')) $('#taxRate').value=(Number(s.sale_tax_rate||0.02)*100).toFixed(1);
  autoRefreshEnabled = s.auto_refresh_enabled !== false;
  autoRefreshSeconds = Number(s.auto_refresh_seconds||30);
  autoSyncEnabled = s.auto_sync_enabled !== false;
  if ($('#autoRefreshEnabled')) $('#autoRefreshEnabled').checked=autoRefreshEnabled;
  if ($('#autoRefreshSeconds')) $('#autoRefreshSeconds').value=autoRefreshSeconds;
  if ($('#autoSyncEnabled')) $('#autoSyncEnabled').checked=autoSyncEnabled;
  startAutoRefresh();
}

async function saveSettings(){
  const enabled=$('#taxEnabled').checked;
  const rate=Math.max(0,Number($('#taxRate').value||2))/100;
  await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sale_tax_enabled:enabled,sale_tax_rate:rate})});
  $('#settingsMessage').textContent='Paramètres enregistrés';
  await Promise.all([loadDashboard(),loadCrafts()]);
  setTimeout(()=>$('#settingsMessage').textContent='',1500);
}
$('#saveSettings')?.addEventListener('click',saveSettings);
async function saveAutoSettings(){
  autoRefreshEnabled=$('#autoRefreshEnabled').checked;
  autoRefreshSeconds=Math.max(10,Math.min(Number($('#autoRefreshSeconds').value||30),300));
  autoSyncEnabled=$('#autoSyncEnabled').checked;
  await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({auto_refresh_enabled:autoRefreshEnabled,auto_refresh_seconds:autoRefreshSeconds,auto_sync_enabled:autoSyncEnabled})});
  startAutoRefresh();
  $('#autoSettingsMessage').textContent='Actualisation automatique enregistrée';
  setTimeout(()=>$('#autoSettingsMessage').textContent='',1700);
}
$('#saveAutoSettings')?.addEventListener('click',saveAutoSettings);

$('#importFile').onchange = async e => { if(!e.target.files[0]) return; const rows=JSON.parse(await e.target.files[0].text()); const r=await api('/api/import-prices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(rows)}); alert(`${r.count} prix importés.`); await Promise.all([loadStatus(),loadPrices(),loadDashboard(),loadCrafts()]); };

(async function init() {
  try {
    const [status] = await Promise.all([loadStatus(),loadCategories(),loadPrices(''),loadSettings()]);
    await Promise.all([loadDashboard(),loadCrafts()]);
    await maybeAutoSyncRecipes(status);
  } catch(e) {
    $('#syncStatus').textContent = 'Erreur de chargement';
    alert('Erreur au démarrage : ' + e.message);
  }
})();


// ---- V3 : historique, diagnostic et liste de courses ----
const SHOP_KEY = 'dcm_shopping_v3';
let shopping = JSON.parse(localStorage.getItem(SHOP_KEY) || '[]');
function saveShopping(){ localStorage.setItem(SHOP_KEY, JSON.stringify(shopping)); renderShopping(); }
function flattenPurchases(node, out={}){
  if (!node) return out;
  if (!node.children || !node.children.length || node.mode === 'acheter') {
    out[node.id] = out[node.id] || {id:node.id,name:node.name,quantity:0,unit:node.best};
    out[node.id].quantity += Number(node.quantity||1);
    return out;
  }
  node.children.forEach(c=>flattenPurchases(c,out));
  return out;
}
async function renderShopping(){
  const selected=$('#shoppingSelected'), result=$('#shoppingResult');
  if(!selected||!result) return;
  if(!shopping.length){selected.innerHTML='<div class="empty">Aucun craft sélectionné.</div>';result.innerHTML='<div class="empty">La liste de ressources apparaîtra ici.</div>';return;}
  selected.innerHTML=shopping.map((x,i)=>`<div class="shopping-line"><span><b>${esc(x.name)}</b><small>ID ${x.id}</small></span><b>×${x.quantity}</b><button data-remove="${i}" class="clear-price">Retirer</button></div>`).join('');
  selected.querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{shopping.splice(+b.dataset.remove,1);saveShopping();});
  const totals={};
  for(const x of shopping){const tree=await api(`/api/tree?id=${x.id}&quantity=${x.quantity}`);flattenPurchases(tree,totals);}
  const rows=Object.values(totals).sort((a,b)=>a.name.localeCompare(b.name,'fr'));
  result.innerHTML=rows.map(x=>`<div class="shopping-line"><span><b>${esc(x.name)}</b><small>${x.unit==null?'prix manquant':fmt(x.unit)+' /u'}</small></span><b>×${x.quantity}</b><span>${fmt(x.unit==null?null:x.unit*x.quantity)}</span></div>`).join('') || '<div class="empty">Aucune ressource terminale.</div>';
}
$('#addModalShopping').onclick=()=>{if(!currentRecipe)return;const q=Math.max(1,+$('#modalQty').value||1);shopping.push({...currentRecipe,quantity:q});saveShopping();$('#recipeModal').classList.add('hidden');};
$('#clearShopping').onclick=()=>{shopping=[];saveShopping();};
$('#copyShopping').onclick=async()=>{const lines=[...$('#shoppingResult').querySelectorAll('.shopping-line')].map(x=>x.innerText.replace(/\n/g,' · ')).join('\n');await navigator.clipboard.writeText(lines);};
let shoppingMatches=[];
async function searchShopping(){const q=$('#shoppingSearch').value.trim();if(!q){$('#shoppingMatches').innerHTML='';return;}shoppingMatches=await api('/api/crafts?'+new URLSearchParams({q,limit:'20',sort:'name'}));$('#shoppingMatches').innerHTML=craftRows(shoppingMatches);$('#shoppingMatches').querySelectorAll('.craft-row').forEach(r=>r.onclick=()=>{shopping.push({id:+r.dataset.id,name:r.dataset.name,quantity:Math.max(1,+$('#shoppingQty').value||1)});saveShopping();});}
let shopTimer; $('#shoppingSearch').oninput=()=>{clearTimeout(shopTimer);shopTimer=setTimeout(searchShopping,180)}; $('#shoppingAdd').onclick=()=>shoppingMatches[0]&&($('#shoppingMatches .craft-row')?.click());

async function loadHistory(){const rows=await api('/api/history?limit=250');const q=($('#historySearch')?.value||'').toLowerCase();const data=rows.filter(x=>!q||x.name.toLowerCase().includes(q));const head='<div class="row header history-row"><span>Objet</span><span>x1</span><span>x10</span><span>x100</span><span>Date</span></div>';$('#historyList').innerHTML=head+(data.length?data.map(x=>`<div class="row history-row"><span><b>${esc(x.name)}</b><small>ID ${x.item_id}</small></span><span>${fmt(x.p1)}</span><span>${fmt(x.p10)}</span><span>${fmt(x.p100)}</span><span>${esc(x.recorded_at)}</span></div>`).join(''):'<div class="empty">Aucun historique.</div>');}
$('#refreshHistory').onclick=loadHistory; $('#historySearch').oninput=loadHistory;
async function runDiagnostics(){const d=await api('/api/diagnostics');$('#diagnosticsBody').innerHTML=`<article><b class="${d.ok?'good':'bad'}">${d.ok?'Données cohérentes':'Anomalies détectées'}</b><span>État global</span></article><article><b>${d.priced_items}</b><span>objets tarifés</span></article><article><b>${d.hidden_items}</b><span>objets techniques masqués</span></article><article><b class="${d.recipes_without_output?'bad':'good'}">${d.recipes_without_output}</b><span>recettes sans objet</span></article><article><b class="${d.ingredients_without_item?'bad':'good'}">${d.ingredients_without_item}</b><span>ingrédients inconnus</span></article><article><b>${d.crafts_without_any_price}</b><span>crafts sans prix de vente</span></article>`;}
$('#runDiagnostics').onclick=runDiagnostics;
renderShopping(); loadHistory(); runDiagnostics();

$$('[data-open-ranking]').forEach(btn => btn.onclick = () => openCraftRanking(btn.dataset.openRanking || 'profit'));


// ---- V5 : Opportunités, priorités et scan HDV assisté ----
let opportunityData=null, opportunityView='budget_best';
function opportunityRows(items){
  const head='<div class="row header opportunity-row"><span>Objet</span><span>Coût optimal</span><span>Bénéfice net/u</span><span>ROI net</span><span>Quantité budget</span><span>Bénéfice budget</span><span>Confiance</span></div>';
  if(!items?.length) return head+'<div class="empty">Aucune opportunité calculable avec les prix actuels.</div>';
  return head+items.map(x=>`<div class="row opportunity-row craft-row" data-id="${x.id}" data-name="${esc(x.name)}"><span><b>${esc(x.name)}</b><small>${esc(x.subtype||x.category||'')}</small></span><span>${fmt(x.best)}</span><span class="good">${fmt(x.profit)}</span><span>${pct(x.roi)}</span><span>${Number(x.budget_qty||0).toLocaleString('fr-FR')}</span><span class="good">${fmt(x.budget_profit)}</span><span>${Math.round(x.confidence||0)} %</span></div>`).join('');
}
async function loadOpportunities(){
  const budget=parseMoney($('#oppBudget')?.value)||5000000;
  opportunityData=await api('/api/opportunities?budget='+encodeURIComponent(budget));
  $('#oppCount').textContent=Number(opportunityData.count||0).toLocaleString('fr-FR')+' opportunités';
  $('#advisorText').innerHTML=(opportunityData.advice||[]).map(x=>`<article>✦ ${esc(String(x).replace(/,/g,' '))}</article>`).join('')||'<div class="empty">Renseigne davantage de prix pour obtenir des recommandations.</div>';
  renderOpportunityView();
}
function renderOpportunityView(){
  const data=opportunityData?.[opportunityView]||[]; $('#opportunityList').innerHTML=opportunityRows(data);
  $$('#opportunityList .craft-row').forEach(r=>r.onclick=()=>openRecipe(r.dataset.id,r.dataset.name));
}
$('#oppRefresh')?.addEventListener('click',()=>{formatMoneyField($('#oppBudget'));loadOpportunities();});
bindMoneyField($('#oppBudget'));
$$('[data-opp-view]').forEach(b=>b.onclick=()=>{$$('[data-opp-view]').forEach(x=>x.classList.remove('active'));b.classList.add('active');opportunityView=b.dataset.oppView;renderOpportunityView();});

async function loadPriorities(){
  const data=await api('/api/priorities?limit=100');
  $('#prioritySummary').innerHTML=`<span>● ${Number(data.priced||0).toLocaleString('fr-FR')} prix déjà renseignés</span><span>● Tri par crafts immédiatement débloqués</span>`;
  const head='<div class="row header priority-row"><span>Objet à relever</span><span>Crafts débloqués immédiatement</span><span>Crafts potentiellement concernés</span><span>Utilisé directement dans</span><span>Action</span></div>';
  $('#priorityList').innerHTML=head+(data.items?.length?data.items.map(x=>`<div class="row priority-row"><span><b>${esc(x.name)}</b><small>${esc(x.subtype||x.category||'')}</small></span><span class="good">${Number(x.unlocks||0).toLocaleString('fr-FR')}</span><span>${Number(x.potential||0).toLocaleString('fr-FR')}</span><span>${Number(x.used_in||0).toLocaleString('fr-FR')}</span><span><button class="priority-price" data-name="${esc(x.name)}">Renseigner le prix</button></span></div>`).join(''):'<div class="empty">Aucun prix prioritaire : tous les crafts sont déjà calculables.</div>');
  $$('.priority-price').forEach(b=>b.onclick=()=>openItemInPrices(b.dataset.name));
}
$('#priorityRefresh')?.addEventListener('click',loadPriorities);

let scanMatches=[];
function setScanImage(file){if(!file)return;const reader=new FileReader();reader.onload=()=>{$('#scanPreview').src=reader.result;$('#scanPreview').classList.remove('hidden');};reader.readAsDataURL(file);}
$('#scanDrop')?.addEventListener('click',()=>$('#scanFile').click());
$('#scanFile')?.addEventListener('change',e=>setScanImage(e.target.files[0]));
$('#scanDrop')?.addEventListener('dragover',e=>{e.preventDefault();e.currentTarget.classList.add('drag');});
$('#scanDrop')?.addEventListener('dragleave',e=>e.currentTarget.classList.remove('drag'));
$('#scanDrop')?.addEventListener('drop',e=>{e.preventDefault();e.currentTarget.classList.remove('drag');setScanImage(e.dataTransfer.files[0]);});
document.addEventListener('paste',e=>{if($('.page.active')?.id!=='scanner')return;const f=[...e.clipboardData.files].find(x=>x.type.startsWith('image/'));if(f)setScanImage(f);});
let scanTimer;
$('#scanItemSearch')?.addEventListener('input',()=>{clearTimeout(scanTimer);scanTimer=setTimeout(async()=>{const q=$('#scanItemSearch').value.trim();scanMatches=q?await api('/api/item-search?q='+encodeURIComponent(q)):[];$('#scanMatches').innerHTML=scanMatches.map(x=>`<button class="scan-match" data-id="${x.id}" data-name="${esc(x.name)}">${esc(x.name)}<small>${esc(x.subtype||x.category||'')}</small></button>`).join('');$$('.scan-match').forEach(b=>b.onclick=()=>{$('#scanItemId').value=b.dataset.id;$('#scanItemSearch').value=b.dataset.name;$('#scanMatches').innerHTML='';});},180);});
['scanP1','scanP10','scanP100'].forEach(id=>bindMoneyField($('#'+id)));
$('#scanSave')?.addEventListener('click',async()=>{const id=Number($('#scanItemId').value);if(!id){$('#scanMessage').textContent='Sélectionne un objet dans les résultats.';return;}const payload={item_id:id,p1:parseMoney($('#scanP1').value),p10:parseMoney($('#scanP10').value),p100:parseMoney($('#scanP100').value)};await api('/api/prices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});$('#scanMessage').textContent='✓ Prix enregistrés et calculs actualisés';await Promise.allSettled([loadStatus(),loadDashboard(),loadCrafts(),loadPriorities(),loadOpportunities()]);});

const oldRefreshVisiblePage=refreshVisiblePage;
refreshVisiblePage=async function(showMessage=true){await oldRefreshVisiblePage(showMessage);const page=$('.page.active')?.id;if(page==='workshop')await loadWorkshopOnce();else if(page==='opportunities')await loadOpportunities();else if(page==='priorities')await loadPriorities();};



// ---- V5.5 : Atelier léger, sélection explicite et chargement à la demande ----
let workshopLoaded=false;
let workshopSelection=JSON.parse(localStorage.getItem('dcm_workshop_selection')||'[]');
let selectedWorkshopCraft=null, selectedInventoryItem=null;
const saveWorkshopSelection=()=>{localStorage.setItem('dcm_workshop_selection',JSON.stringify(workshopSelection));renderWorkshopSelection();};
function renderWorkshopSelection(){
  const el=$('#workshopSelection'); if(!el)return;
  el.innerHTML=workshopSelection.length?workshopSelection.map((x,i)=>`<div class="workshop-line"><span><b>${esc(x.name)}</b><small>Objectif de production</small></span><input type="number" min="1" value="${x.quantity}" data-workshop-qty="${i}"><button class="secondary" data-workshop-remove="${i}">Retirer</button></div>`).join(''):'<div class="empty">Aucun craft ajouté.</div>';
  $$('[data-workshop-qty]').forEach(input=>input.onchange=()=>{workshopSelection[+input.dataset.workshopQty].quantity=Math.max(1,+input.value||1);saveWorkshopSelection();});
  $$('[data-workshop-remove]').forEach(btn=>btn.onclick=()=>{workshopSelection.splice(+btn.dataset.workshopRemove,1);saveWorkshopSelection();});
}
function showSelected(kind,item){
  const box=$('#'+(kind==='craft'?'workshopCraftSelected':'inventorySelected'));
  const button=$('#'+(kind==='craft'?'workshopAddCraft':'inventoryAdd'));
  if(!item){box.classList.add('hidden');box.innerHTML='';button.disabled=true;return;}
  box.innerHTML=`<b>${esc(item.name)}</b><small>${esc(item.subtype||item.category||'Objet sélectionné')}</small>`;
  box.classList.remove('hidden'); button.disabled=false;
}
async function searchWorkshopCrafts(){
  const q=$('#workshopCraftSearch').value.trim(); selectedWorkshopCraft=null;showSelected('craft',null);
  if(!q){$('#workshopCraftMatches').innerHTML='';return;}
  const rows=await api('/api/crafts?'+new URLSearchParams({q,limit:'12',sort:'name'}));
  $('#workshopCraftMatches').innerHTML=rows.map(x=>`<button class="workshop-match" data-id="${x.id}" data-name="${esc(x.name)}"><b>${esc(x.name)}</b><small>${esc(x.subtype||x.category||'')}</small></button>`).join('');
  $$('#workshopCraftMatches .workshop-match').forEach((b,i)=>b.onclick=()=>{selectedWorkshopCraft=rows[i];$$('#workshopCraftMatches .workshop-match').forEach(x=>x.classList.remove('selected'));b.classList.add('selected');showSelected('craft',selectedWorkshopCraft);});
}
let wsCraftTimer;$('#workshopCraftSearch')?.addEventListener('input',()=>{clearTimeout(wsCraftTimer);wsCraftTimer=setTimeout(searchWorkshopCrafts,220)});
$('#workshopAddCraft')?.addEventListener('click',()=>{if(!selectedWorkshopCraft)return;const qty=Math.max(1,+$('#workshopCraftQty').value||1);const found=workshopSelection.find(x=>x.item_id===+selectedWorkshopCraft.id);if(found)found.quantity+=qty;else workshopSelection.push({item_id:+selectedWorkshopCraft.id,name:selectedWorkshopCraft.name,quantity:qty});saveWorkshopSelection();selectedWorkshopCraft=null;showSelected('craft',null);$('#workshopCraftSearch').value='';$('#workshopCraftMatches').innerHTML='';});
$('#workshopClear')?.addEventListener('click',()=>{workshopSelection=[];saveWorkshopSelection();renderWorkshopPlan(null);});
async function loadInventory(){
  const rows=await api('/api/inventory?limit=500');
  $('#inventoryList').innerHTML=rows.length?rows.map(x=>`<div class="workshop-line inventory-line" data-id="${x.id}"><span><b>${esc(x.name)}</b><small>${esc(x.subtype||x.category||'')}</small></span><input class="inventory-line-qty" type="number" min="0" value="${x.quantity}"><button class="secondary inventory-save">Mettre à jour</button></div>`).join(''):'<div class="empty">Inventaire vide.</div>';
  $$('#inventoryList .inventory-line').forEach(row=>row.querySelector('.inventory-save').onclick=async()=>{await api('/api/inventory',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item_id:+row.dataset.id,quantity:Math.max(0,+row.querySelector('.inventory-line-qty').value||0)})});await loadInventory();});
}
async function searchInventoryItems(){
  const q=$('#inventorySearch').value.trim();selectedInventoryItem=null;showSelected('inventory',null);
  if(!q){$('#inventoryMatches').innerHTML='';return;}
  const rows=await api('/api/item-search?q='+encodeURIComponent(q)+'&limit=12');
  $('#inventoryMatches').innerHTML=rows.map(x=>`<button class="workshop-match" data-id="${x.id}" data-name="${esc(x.name)}"><b>${esc(x.name)}</b><small>${esc(x.subtype||x.category||'')}</small></button>`).join('');
  $$('#inventoryMatches .workshop-match').forEach((b,i)=>b.onclick=()=>{selectedInventoryItem=rows[i];$$('#inventoryMatches .workshop-match').forEach(x=>x.classList.remove('selected'));b.classList.add('selected');showSelected('inventory',selectedInventoryItem);});
}
let invTimer;$('#inventorySearch')?.addEventListener('input',()=>{clearTimeout(invTimer);invTimer=setTimeout(searchInventoryItems,220)});
$('#inventoryAdd')?.addEventListener('click',async()=>{if(!selectedInventoryItem)return;await api('/api/inventory',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item_id:+selectedInventoryItem.id,quantity:Math.max(0,+$('#inventoryQty').value||0)})});selectedInventoryItem=null;showSelected('inventory',null);$('#inventorySearch').value='';$('#inventoryMatches').innerHTML='';await loadInventory();});
$('#workshopInventoryRefresh')?.addEventListener('click',loadInventory);
function renderPlanLines(rows,type){if(!rows?.length)return '<div class="empty">Aucun élément.</div>';return rows.map(x=>`<div class="plan-line"><b>${esc(x.name)}</b><span>×${Number(x.quantity||x.units||0).toLocaleString('fr-FR')}</span><span>${type==='purchase'?(x.label+' · '+fmt(x.cost)):''}</span></div>`).join('');}
function renderWorkshopPlan(data){
  if(!data){['workshopPurchases','workshopCraftSteps','workshopStockUsed','workshopSummary'].forEach(id=>$('#'+id).innerHTML='<div class="empty">Lance un calcul.</div>');return;}
  $('#workshopPurchases').innerHTML=renderPlanLines(data.purchases,'purchase');$('#workshopCraftSteps').innerHTML=renderPlanLines(data.crafts,'craft');$('#workshopStockUsed').innerHTML=renderPlanLines(data.stock_used,'stock');
  const missing=renderPlanLines(data.missing,'missing');$('#workshopSummary').innerHTML=`<div class="metric-grid"><div><small>Coût total</small><b>${fmt(data.total_cost)}</b></div><div><small>État</small><b class="${data.complete?'good':'bad'}">${data.complete?'Plan complet':'Prix manquants'}</b></div><div><small>Achats</small><b>${data.purchases.length}</b></div><div><small>Sous-crafts</small><b>${data.crafts.length}</b></div></div>${data.missing.length?'<h3>Prix manquants</h3>'+missing:''}`;
  $('#workshopState').textContent=data.complete?'✓ Plan calculé':'Plan calculé avec des prix manquants';
}
$('#workshopCalculate')?.addEventListener('click',async()=>{if(!workshopSelection.length){$('#workshopState').textContent='Ajoute au moins un craft.';return;}$('#workshopState').textContent='Calcul en cours…';const data=await api('/api/workshop-plan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({selections:workshopSelection})});renderWorkshopPlan(data);});
$('#workshopCopy')?.addEventListener('click',async()=>{await navigator.clipboard.writeText($('#workshopPurchases').innerText);$('#workshopState').textContent='Liste copiée.';});
async function loadWorkshopOnce(){if(workshopLoaded)return;workshopLoaded=true;renderWorkshopSelection();renderWorkshopPlan(null);await loadInventory();}
