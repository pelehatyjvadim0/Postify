import {request, getSettings, getQueue} from './api.js';
import {escapeHtml as esc, sourceName, statusBadge} from './screens.js';

export const workState = {stage: 'review', view: 'list', query: '', week: 0, selected: null, editorOpen: false};
const stages = {all: 'Все', source: 'Материалы', review: 'На проверке', plan: 'В плане', published: 'Опубликовано', error: 'Проблемы', rejected: 'Отклонено'};

async function allItems(id, resource, signal) {
  const items = [];
  for (let offset = 0; ; offset += 100) {
    const page = await request(`/projects/${id}/${resource}?limit=100&offset=${offset}`, {signal});
    items.push(...page.items);
    if (page.items.length < 100) return items;
  }
}

export async function loadWorkspace(id, signal) {
  const [items, materials, publications, settings, queue] = await Promise.all([
    allItems(id, 'packages', signal), allItems(id, 'materials', signal),
    allItems(id, 'publications', signal), getSettings(id, signal), getQueue(id, signal),
  ]);
  return {items, materials, publications, settings, queue: queue.items};
}

export function shortTitle(value) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text) return 'Пост без текста';
  const sentence = text.split(/(?<=[.!?])\s/)[0];
  if (sentence.length <= 72) return sentence;
  return sentence.slice(0, 69).replace(/\s+\S*$/, '') + '…';
}

export function localDay(value, timezone) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en', {timeZone: timezone, year:'numeric', month:'2-digit', day:'2-digit'}).formatToParts(new Date(value)).map(p => [p.type,p.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function rows(data) {
  const superseded = new Set(data.items.filter(p => !['failed','processing'].includes(p.status)).map(p => p.previous_package_id));
  const used = new Set(data.items.map(p => p.candidate_id));
  const deliveries = new Map(data.publications.map(p => [p.package_id,p]));
  const queue = new Map(data.queue.map(p => [p.package_id,p]));
  const channels = new Map(data.settings.channels.map(c => [c.id,c.name]));
  const routes = new Map(data.settings.routes.map(r => [r.id,channels.get(r.channel_id)]));
  const posts = data.items.filter(p => !superseded.has(p.package_id)).map(p => {
    const delivery = deliveries.get(p.package_id), planned = queue.get(p.package_id);
    const status = delivery?.status || (p.status === 'approved' && planned?.status === 'overdue' ? 'overdue' : p.status);
    const stage = ['failed','retryable','uncertain','overdue'].includes(status) ? 'error' : status === 'published' ? 'published' : p.status === 'rejected' ? 'rejected' : p.status === 'approved' || status === 'sending' ? 'plan' : 'review';
    return {...p, key:`post-${p.package_id}`, action:'open-package', id:p.package_id, stage, displayStatus:status, title:shortTitle(p.post_text), channel:routes.get(p.route_id) || 'Канал не выбран', when:delivery?.confirmed_at || p.scheduled_at, delivery};
  });
  const materials = data.materials.filter(m => !used.has(m.candidate_id)).map(m => ({...m,key:`material-${m.candidate_id}`,action:'open-material',id:m.candidate_id,stage:m.generation_failure_code?'error':m.decision_status==='rejected'?'rejected':'source',displayStatus:m.generation_status||m.decision_status,title:shortTitle(m.title),channel:sourceName(m.source_name)}));
  return [...posts,...materials];
}

function row(item, timezone, calendar=false) {
  const date = item.when ? new Intl.DateTimeFormat('ru', calendar ? {timeZone:timezone,hour:'2-digit',minute:'2-digit'} : {timeZone:timezone,day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}).format(new Date(item.when)) : 'Без даты';
  const icons = {awaiting_review: ['◷', 'Ждёт проверки'], approved: ['◷', 'Запланирован'], planned: ['◷', 'Запланирован'], sending: ['◷', 'Отправляется'], published: ['✓', 'Опубликован'], failed: ['!', 'Ошибка'], rejected: ['×', 'Отклонён']};
  const [symbol, title] = icons[item.displayStatus] || ['•', 'Статус поста'];
  const state = calendar ? `<span class="work-status" title="${title}" aria-label="${title}">${symbol}</span>` : statusBadge(item.displayStatus);
  return `<button type="button" class="work-row ${workState.selected===item.key?'is-selected':''} ${calendar?'work-event':''}" data-action="${item.action}" data-id="${item.id}" data-work-key="${item.key}"><span class="work-copy"><strong>${esc(item.title)}</strong><small>${esc(item.channel)}</small></span>${state}<time>${esc(date)}</time></button>`;
}

export function renderWorkspace(data) {
  const all = rows(data), timezone = data.settings.project.timezone;
  const visible = all.filter(p => (workState.stage==='all'||p.stage===workState.stage) && `${p.title} ${p.post_text||''} ${p.channel}`.toLocaleLowerCase('ru').includes(workState.query.toLocaleLowerCase('ru')));
  const toolbar = `<div class="work-toolbar"><div class="work-views" aria-label="Вид постов">${[['list','Список'],['calendar','Календарь']].map(([key,title])=>`<button class="filter-chip ${workState.view===key?'is-active':''}" data-work-view="${key}" aria-pressed="${workState.view===key}">${title}</button>`).join('')}</div></div>`;
  const filters = `<div class="work-filters">${Object.entries(stages).map(([key,title])=>`<button class="filter-chip ${workState.stage===key?'is-active':''}" data-work-stage="${key}" aria-pressed="${workState.stage===key}">${title} <span>${key==='all'?all.length:all.filter(p=>p.stage===key).length}</span></button>`).join('')}</div>`;
  let content;
  if(workState.view==='list') {
    content = `<div class="work-list panel"><label class="work-search"><span class="visually-hidden">Поиск постов</span><input id="work-search" type="search" placeholder="Найти пост…" value="${esc(workState.query)}"></label><div class="work-table-head"><span>Пост / канал</span><span>Статус</span><span>Публикация</span></div>${visible.map(p=>row(p,timezone)).join('')||'<p class="work-empty">Здесь пока ничего нет</p>'}</div>`;
  } else {
    const start = new Date(localDay(new Date(),timezone)+'T12:00:00Z');
    start.setUTCDate(start.getUTCDate()-((start.getUTCDay()+6)%7)+workState.week*7);
    const days = Array.from({length:7},(_,i)=>{const d=new Date(start);d.setUTCDate(d.getUTCDate()+i);return d;});
    // A date alone is only a draft plan. The calendar shows posts that have
    // been approved for publication, are being delivered, or have a delivery result.
    const calendarItems = all.filter(p => p.when && ['plan', 'published', 'error'].includes(p.stage) && (workState.stage==='all'||p.stage===workState.stage));
    content = `<section class="panel work-calendar"><div class="work-calendar-head"><button class="icon-button" data-week="-1" aria-label="Предыдущая неделя">‹</button><strong>${new Intl.DateTimeFormat('ru',{month:'long',year:'numeric',timeZone:'UTC'}).format(days[3])}</strong><button class="button button--quiet" data-week="today">Сегодня</button><button class="icon-button" data-week="1" aria-label="Следующая неделя">›</button></div><div class="work-week">${days.map(day=>{const key=day.toISOString().slice(0,10),items=calendarItems.filter(p=>localDay(p.when,timezone)===key);return `<section class="work-day ${key===localDay(new Date(),timezone)?'is-today':''}"><h3>${new Intl.DateTimeFormat('ru',{weekday:'short',day:'numeric',timeZone:'UTC'}).format(day)}</h3>${items.sort((a,b)=>new Date(a.when)-new Date(b.when)).map(p=>row(p,timezone,true)).join('')||'<span class="work-free">Свободно</span>'}</section>`;}).join('')}</div></section>`;
  }
  const editor = workState.view === 'calendar' && workState.editorOpen ? '<section class="work-editor panel" id="work-editor" aria-label="Выбранный пост"><p class="work-empty">Загрузка поста…</p></section>' : '';
  return `<section class="screen work-screen" data-screen="review">${toolbar}${filters}<div class="work-layout ${workState.view==='calendar'?'work-layout-calendar':''} ${workState.editorOpen?'work-layout-editor-open':''}">${content}${editor}</div><a class="work-journal" href="#journal">История действий</a></section>`;
}
