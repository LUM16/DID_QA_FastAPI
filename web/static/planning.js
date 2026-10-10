(() => {
  'use strict';
  const root = document.querySelector('#planning');
  const states = {};
  let active = 'chat';
  const make = (tag, text, cls) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  const pct = n => `${(Number(n || 0) * 100).toFixed(1)}%`;
  function table(rows) {
    const wrap = make('div', undefined, 'planning-table');
    if (!rows.length) { wrap.textContent = 'No evidence-qualified candidates available.'; return wrap; }
    const grid = make('table'), head = make('thead'), tr = make('tr');
    const keys = Object.keys(rows[0]);
    keys.forEach(k => tr.append(make('th', k)));
    head.append(tr); grid.append(head);
    const body = make('tbody');
    rows.forEach(row => {
      const line = make('tr');
      keys.forEach(k => line.append(make('td', row[k] == null ? '—' : String(row[k]))));
      body.append(line);
    });
    grid.append(body); wrap.append(grid); return wrap;
  }
  function detail(title, content) {
    const node = make('details'); node.append(make('summary', title), content); return node;
  }
  async function response(fetchResponse) {
    const data = await fetchResponse.json();
    if (!fetchResponse.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data));
    return data;
  }
  function note(parent, text) { parent.append(make('p', text, 'planning-note')); }
  function snapshotNote(parent, snap) {
    if (snap) {
      const version = snap.version?.includes('v4') ? 'v4 TA/group hierarchy' : snap.version?.includes('v1') ? 'v1 person allocation' : 'published';
      note(parent, `Snapshot: ${snap.generated_at || 'published'} · ${version} · ${snap.history_row_count || 0} historical rows`);
    }
  }
  function cacheNote(parent, result) {
    if (result.cache) note(parent, `Shared TLF similarity cache: ${result.cache.hits} hits · ${result.cache.misses} new comparisons.`);
  }
  function recommendations(host, result) {
    host.append(make('h2', `${result.candidate_team_count} eligible teams · Top ${result.recommendations.length}`));
    note(host, `TA Lead: ${result.ta_lead_name}. Ranked across all current groups; scores are scope-match scores, not model probabilities.`);
    snapshotNote(host, result.history_snapshot);
    if (!result.recommendations.length) note(host, 'No team recommendations were produced from the available history.');
    result.recommendations.forEach(row => {
      const card = make('section', undefined, 'planning-card');
      card.append(make('h3', `#${row.rank} — ${row.du_team} · ${Number(row.score).toFixed(1)}/100`));
      note(card, row.recommendation_level);
      const bar = make('div', undefined, 'planning-score'), fill = make('span');
      fill.style.width = `${Math.min(100, Math.max(0, Number(row.score)))}%`; bar.append(fill); card.append(bar);
      card.append(table([{
        'Group Leads': (row.group_leads || []).join(', '),
        'TLF coverage': pct(row.tlf_semantic_coverage),
        'Similar DID ≥70%': row.similar_did_count_ge_70,
        'Similar DID ≥85%': row.similar_did_count_ge_85,
        'Completed DIDs': row.completed_did_count,
        'Semantic candidates': row.semantic_candidate_did_count,
        'Active DIDs': row.active_did_count
      }]));
      card.append(detail('TLF coverage evidence across completed DIDs', table((row.tlf_coverage_evidence || []).map(x => ({
        'Target TLF': x.target_tlf, Covered: x.matched ? 'Yes' : 'No',
        'Evidence DID': x.evidence_did, Completed: x.completion_date
      })))));
      card.append(detail('Most similar completed DIDs', table((row.similar_dids || []).map(x => ({
        DID: x.did, Completed: x.completion_date,
        'Scope similarity': pct(x.combined_similarity), 'TLF coverage': pct(x.tlf_semantic_coverage)
      })))));
      host.append(card);
    });
    cacheNote(host, result);
  }
  function candidate(role, kind, person) {
    return {
      Role: role, Recommendation: kind, Person: person ? person.person : 'Lead review required',
      Score: person?.adjusted_score, 'Base score': person?.base_score,
      'Balancing penalty': person?.balancing_penalty, 'Prior primaries': person?.prior_primary_allocations,
      'Active DIDs': person?.active_did_count, 'Evidence DID': person?.evidence_did
    };
  }
  function allocations(host, result, state) {
    host.append(make('h2', `${result.allocations.length} TLF allocations · ${result.team_lead_name}`));
    snapshotNote(host, result.snapshot);
    note(host, `Each prior primary reduces the next score by ${result.primary_balancing.penalty_per_prior_primary} points. Generation and QC are distinct within allocation groups except explicitly flagged fallback.`);
    const download = make('button', 'Download allocation Excel', 'primary');
    download.onclick = async () => {
      download.disabled = true;
      try {
        const res = await fetch('api/planning/allocate/excel', {
          method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({result})
        });
        if (!res.ok) { await response(res); return; }
        const url = URL.createObjectURL(await res.blob());
        const link = make('a'); link.href = url; link.download = 'tlf_person_allocation.xlsx';
        link.hidden = true; document.body.append(link); link.click();
        setTimeout(() => { link.remove(); URL.revokeObjectURL(url); }, 1000);
      } catch (e) { state.status.textContent = `Excel export failed: ${e.message}`; state.status.classList.add('planning-error'); }
      finally { download.disabled = false; }
    };
    host.append(download);
    const groups = new Map();
    result.allocations.forEach(a => {
      if (!groups.has(a.group)) groups.set(a.group, {gen: new Set(), qc: new Set()});
      const g = groups.get(a.group);
      if (a.generation.primary) g.gen.add(a.generation.primary.person);
      if (a.qc.primary) g.qc.add(a.qc.primary.person);
    });
    host.append(table([...groups].map(([group, owners]) => ({
      Group: group, 'Generation primaries': [...owners.gen].join(', '), 'QC primaries': [...owners.qc].join(', ')
    }))));
    result.allocations.forEach(a => {
      const card = make('section', undefined, 'planning-card');
      card.append(make('h3', `${a.tlf.name} · ${a.group}`));
      note(card, `Type: ${a.tlf.type || '—'} · Source: ${a.tlf.source || '—'}`);
      const rows = [];
      for (const [key, label] of [['generation', 'Generation'], ['qc', 'QC']]) {
        rows.push(candidate(label, 'Primary', a[key].primary));
        a[key].backups.forEach((p, i) => rows.push(candidate(label, `Backup ${i + 1}`, p)));
      }
      card.append(table(rows));
      if (a.lead_review_required) card.append(make('p', a.fallback_reason || 'Lead review required', 'planning-warning'));
      if (!a.generation.primary || !a.qc.primary) card.append(make('p', 'One or more roles have no eligible primary; lead review is required.', 'planning-warning'));
      if (a.generation.backups.length < 2 || a.qc.backups.length < 2) note(card, 'Fewer than two evidence-qualified backups are available; lead review is needed.');
      host.append(card);
    });
    cacheNote(host, result);
  }
  function build(mode) {
    const state = {loaded: false, revision: 0, controller: null};
    const panel = make('div'), card = make('section', undefined, 'planning-card');
    card.append(make('h2', mode === 'recommend' ? 'Recommend Team' : 'Allocate TLF People'));
    note(card, mode === 'recommend'
      ? 'Select a snapshot-backed TA Lead. Rank teams across all groups using TLF-only coverage 37%, similar completed DIDs 18%, recent experience 10%, and workload 35%. No group filter.'
      : 'Select an exact Team Lead from the complete snapshot list; no LLM name matching. Historical role evidence, grouped distinct Generation/QC, backups, workload and run-local balancing are retained.');
    const example = make('a', 'Download example workbook'); example.href = 'api/planning/example'; card.append(example);
    const form = make('form', undefined, 'planning-form');
    const leadLabel = mode === 'recommend' ? 'TA Lead' : 'Team Lead';
    const label = make('label', `${leadLabel} — search and select a complete name`);
    const search = make('input'); search.type = 'search'; search.placeholder = `Search ${leadLabel} names…`; search.setAttribute('aria-label', `Search ${leadLabel}`);
    const select = make('select'); select.size = 5; select.required = true; select.setAttribute('aria-label', leadLabel);
    label.append(search, select); form.append(label);
    const primaryLabel = make('label', mode === 'recommend' ? 'TLF workbook (.xlsx) or TLF CSV' : 'Workbook with TLF + Data sheets, or TLF CSV');
    const primary = make('input'); primary.type = 'file'; primary.accept = '.xlsx,.csv'; primary.required = true; primaryLabel.append(primary); form.append(primaryLabel);
    const dataLabel = make('label', 'Data CSV (required for CSV allocation; optional for recommendation)');
    const data = make('input'); data.type = 'file'; data.accept = '.csv'; dataLabel.append(data); form.append(dataLabel);
    const actions = make('div', undefined, 'planning-actions'), submit = make('button', mode === 'recommend' ? 'Recommend Team' : 'Allocate TLF People', 'primary');
    submit.type = 'submit'; submit.disabled = true;
    const reset = make('button', 'Reset'); reset.type = 'button';
    actions.append(submit, reset); form.append(actions);
    const status = make('p', '', 'planning-status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const results = make('div');
    card.append(form, status); panel.append(card, results);
    Object.assign(state, {panel, select, search, submit, status, results, names: []});
    function invalidate() {
      state.revision++; state.controller?.abort(); state.controller = null;
      results.replaceChildren(); status.textContent = ''; status.classList.remove('planning-error');
      submit.disabled = !state.loaded;
    }
    function filter() {
      const previous = select.value;
      select.replaceChildren();
      state.names.filter(n => n.toLocaleLowerCase().includes(search.value.toLocaleLowerCase())).forEach(n => {
        const option = make('option', n); option.value = n; select.append(option);
      });
      select.value = previous;
      if (!select.value) select.selectedIndex = -1;
      invalidate();
    }
    state.filter = filter;
    search.oninput = filter;
    select.onchange = invalidate;
    primary.onchange = () => { if (!primary.files[0]?.name.toLowerCase().endsWith('.csv')) data.value = ''; invalidate(); };
    data.onchange = invalidate;
    reset.onclick = () => { form.reset(); search.value = ''; select.selectedIndex = -1; filter(); };
    form.onsubmit = async event => {
      event.preventDefault(); invalidate();
      if (!state.names.includes(select.value)) { status.textContent = 'Select a complete name from the snapshot list.'; return; }
      const file = primary.files[0], dataFile = data.files[0];
      if (!file) { status.textContent = 'Select an input file.'; return; }
      if (mode === 'allocate' && file.name.toLowerCase().endsWith('.csv') && !dataFile) {
        status.textContent = 'CSV allocation requires both TLF CSV and Data CSV.'; return;
      }
      const version = state.revision, controller = new AbortController(); state.controller = controller;
      const body = new FormData(); body.set(mode === 'recommend' ? 'ta_lead_name' : 'team_lead_name', select.value);
      body.set('primary_file', file); if (dataFile) body.set('data_csv_file', dataFile);
      submit.disabled = true;
      const started = Date.now();
      const progress = () => { if (state.revision === version) status.textContent = `Comparing published snapshot evidence… ${Math.floor((Date.now() - started) / 1000)}s. No LLM or live Neo4j refresh.`; };
      progress(); const timer = setInterval(progress, 1000);
      try {
        const job = await response(await fetch(`api/planning/jobs/${mode}`, {method: 'POST', body, signal: controller.signal}));
        let result;
        while (state.revision === version) {
          const current = await response(await fetch(`api/planning/jobs/${job.job_id}`, {signal: controller.signal}));
          if (current.status === 'error') throw new Error(current.error);
          if (current.status === 'complete') { result = current.result; break; }
          await new Promise(resolve => setTimeout(resolve, 1000));
        }
        if (state.revision !== version) return;
        results.replaceChildren();
        if (mode === 'recommend') recommendations(results, result); else allocations(results, result, state);
        status.textContent = `Completed in ${((Date.now() - started) / 1000).toFixed(1)}s.`;
      } catch (e) {
        if (e.name !== 'AbortError' && state.revision === version) {
          status.textContent = e.message; status.classList.add('planning-error');
        }
      } finally {
        clearInterval(timer);
        if (state.revision === version) { submit.disabled = !state.loaded; state.controller = null; }
      }
    };
    return state;
  }
  async function load(state, mode) {
    if (state.loaded || state.loading) return;
    state.loading = true; state.status.textContent = 'Loading published snapshot choices…';
    try {
      const payload = await response(await fetch(`api/planning/${mode}/options`));
      state.names = payload[mode === 'recommend' ? 'ta_leads' : 'team_leads'];
      if (!state.names.length) throw new Error('The snapshot has no eligible lead choices.');
      state.loaded = true; state.filter();
      state.status.textContent = `Loaded ${state.names.length} exact snapshot names.`;
    } catch (e) { state.status.textContent = `${e.message} Switch back to this tab to retry.`; state.status.classList.add('planning-error'); }
    finally { state.loading = false; }
  }
  document.querySelectorAll('[data-workflow]').forEach(button => {
    button.onclick = () => {
      active = button.dataset.workflow;
      document.querySelectorAll('[data-workflow]').forEach(b => {
        b.classList.toggle('primary', b === button); b.setAttribute('aria-pressed', String(b === button));
      });
      document.querySelector('#chat').hidden = active !== 'chat';
      document.querySelector('.composer').hidden = active !== 'chat';
      root.hidden = active === 'chat';
      if (active !== 'chat') {
        states[active] ||= build(active);
        root.replaceChildren(states[active].panel); load(states[active], active);
      }
    };
  });
})();
