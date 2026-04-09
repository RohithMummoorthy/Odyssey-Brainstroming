/**
 * admin.js — Math Quiz Admin Dashboard
 *
 * Auth:    Admin JWT stored in sessionStorage as 'admin_token'
 * Polling: /admin/status every 3 s, /admin/leaderboard every 5 s
 */

'use strict';

// ── Token ─────────────────────────────────────────────────────────────────

function getToken()     { return sessionStorage.getItem('admin_token') || ''; }
function setToken(t)    { sessionStorage.setItem('admin_token', t); }
function clearToken()   { sessionStorage.removeItem('admin_token'); }

function authHeaders() {
  return {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${getToken()}`,
  };
}

// ── DOM helpers ───────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);

const Dom = {
  loginScreen:      $('loginScreen'),
  dashboard:        $('dashboard'),
  adminPwInput:     $('adminPwInput'),
  loginBtn:         $('loginBtn'),
  loginError:       $('loginError'),
  eventStatusBadge: $('eventStatusBadge'),
  startCountInput:  $('startCountInput'),
  startEventBtn:    $('startEventBtn'),
  activateTeamInput:$('activateTeamInput'),
  activateTeamBtn:  $('activateTeamBtn'),
  endEventBtn:      $('endEventBtn'),
  resetEventBtn:    $('resetEventBtn'),
  lockNetBtn:       $('lockNetBtn'),
  unlockNetBtn:     $('unlockNetBtn'),
  exportBtn:        $('exportBtn'),
  lockedIpDisplay:  $('lockedIpDisplay'),
  lastRefreshTs:    $('lastRefreshTs'),
  teamCount:        $('teamCount'),
  teamsBody:        $('teamsBody'),
  teamFilter:       $('teamFilter'),
  reloginBody:      $('reloginBody'),
  reloginCount:     $('reloginCount'),
  leaderboardBody:  $('leaderboardBody'),
  auditModal:       $('auditModal'),
  auditModalTitle:  $('auditModalTitle'),
  auditModalBody:   $('auditModalBody'),
  closeAuditModal:  $('closeAuditModal'),
  adminToast:       $('adminToast'),
};

// ── Toast ─────────────────────────────────────────────────────────────────

let _toastTimer = null;
function toast(msg, type = 'ok') {
  Dom.adminToast.textContent = msg;
  Dom.adminToast.className   = `show ${type}`;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => Dom.adminToast.classList.remove('show'), 3500);
}

// ── API helpers ───────────────────────────────────────────────────────────

async function api(method, path, body) {
  const opts = { method, headers: authHeaders() };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res  = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    clearToken();
    showLogin();
    return null;
  }
  return { ok: res.ok, status: res.status, data };
}

// ── State ─────────────────────────────────────────────────────────────────

let _allTeams       = [];
let _filterText     = '';
let _eventStatus    = 'waiting';
let _lockedIp       = '';
let _statusInterval = null;
let _lbInterval     = null;

function inferEventStatusFromTeams(rows) {
  const submitted = rows.filter(t => t.status === 'submitted').length;
  const active    = rows.filter(t => t.status === 'active').length;
  const waiting   = rows.filter(t => t.status === 'waiting').length;
  if (active > 0 || (submitted > 0 && waiting === 0 && active === 0)) {
    return active > 0 ? 'running' : 'ended';
  }
  return 'waiting';
}

// ── Login ─────────────────────────────────────────────────────────────────

function showLogin() {
  Dom.loginScreen.style.display = 'flex';
  Dom.dashboard.style.display   = 'none';
}

function showDashboard() {
  Dom.loginScreen.style.display = 'none';
  Dom.dashboard.style.display   = 'flex';
}

async function handleLogin() {
  const pw = Dom.adminPwInput.value.trim();
  if (!pw) return;

  Dom.loginBtn.disabled = true;
  const r = await api('POST', '/admin/login', { password: pw }).catch(() => null);
  Dom.loginBtn.disabled = false;

  if (!r || !r.ok) {
    Dom.loginError.style.display = 'block';
    return;
  }

  Dom.loginError.style.display = 'none';
  setToken(r.data.token);
  showDashboard();
  startPolling();
  refreshLeaderboard();
  fetchNetworkStatus();
}

Dom.adminPwInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') handleLogin();
});
Dom.loginBtn.addEventListener('click', handleLogin);

// ── Status polling ────────────────────────────────────────────────────────

async function refreshStatus() {
  const r = await api('GET', '/admin/status');
  if (!r || !r.ok) return;

  const payload = r.data;
  if (Array.isArray(payload)) {
    // Backward-compatibility for older backend response shape.
    _allTeams = payload;
    _eventStatus = inferEventStatusFromTeams(_allTeams);
  } else {
    _allTeams = payload?.teams || [];
    _eventStatus = payload?.event_status || inferEventStatusFromTeams(_allTeams);
  }

  renderTeams();
  renderRelogin();
  updateEventStatusUI();
  Dom.lastRefreshTs.textContent = `Last refresh: ${new Date().toLocaleTimeString()}`;
}

async function refreshLeaderboard() {
  const r = await api('GET', '/admin/leaderboard');
  if (!r || !r.ok) return;
  renderLeaderboard(r.data || []);
}

async function fetchNetworkStatus() {
  // We read the locked IP from the app_config via /admin/status data isn't
  // directly exposed, so ping lock-status by looking at lockedIp from the
  // network-lock/unlock responses stored in sessionStorage.
  const stored = sessionStorage.getItem('admin_locked_ip') || '';
  _lockedIp = stored;
  Dom.lockedIpDisplay.textContent = stored || 'unrestricted';
}

function startPolling() {
  clearInterval(_statusInterval);
  clearInterval(_lbInterval);
  refreshStatus();
  _statusInterval = setInterval(refreshStatus,      3_000);
  _lbInterval     = setInterval(refreshLeaderboard, 5_000);
}

// ── Event status UI ───────────────────────────────────────────────────────

function updateEventStatusUI() {
  if (!['waiting', 'running', 'ended'].includes(_eventStatus)) {
    _eventStatus = 'waiting';
  }

  const badge = Dom.eventStatusBadge;
  if (_eventStatus === 'running') {
    badge.className   = 'badge badge-success';
    badge.textContent = '● Running';
    Dom.startEventBtn.disabled = true;
    Dom.endEventBtn.disabled   = false;
    Dom.exportBtn.disabled     = true;
  } else if (_eventStatus === 'ended') {
    badge.className   = 'badge badge-danger';
    badge.textContent = '■ Ended';
    Dom.startEventBtn.disabled = true;
    Dom.endEventBtn.disabled   = true;
    Dom.exportBtn.disabled     = false;
  } else {
    badge.className   = 'badge badge-muted';
    badge.textContent = '○ Waiting';
    Dom.startEventBtn.disabled = false;
    Dom.endEventBtn.disabled   = true;
    Dom.exportBtn.disabled     = true;
  }
}

// ── Render teams table ────────────────────────────────────────────────────

function statusBadge(status) {
  const map = {
    submitted: 'badge-success',
    active:    'badge-warn',
    waiting:   'badge-muted',
  };
  return `<span class="badge ${map[status] || 'badge-muted'}">${status}</span>`;
}

function fmtTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${d.toLocaleTimeString()}`;
}

function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const total = Math.max(0, Number(seconds) || 0);
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${mins}:${String(secs).padStart(2, '0')}`;
}

function timerLabel(t) {
  if (!t.timer_started) {
    return '<span class="badge badge-muted">Not started</span>';
  }
  if (t.status === 'submitted') {
    return '<span class="badge badge-success">Completed</span>';
  }
  if (typeof t.remaining_seconds === 'number') {
    return `<span class="badge badge-warn">${fmtDuration(t.remaining_seconds)} left</span>`;
  }
  return '<span class="badge badge-muted">Started</span>';
}

function timeTakenLabel(t) {
  if (t.time_taken_minutes === null || t.time_taken_minutes === undefined) return '—';
  return `${t.time_taken_minutes} min`;
}

function startedAtLabel(t) {
  if (!t.server_start_time) return '—';
  return fmtTime(t.server_start_time);
}

function renderTeams() {
  const filter = _filterText.toLowerCase();
  const rows   = _allTeams.filter(t =>
    !filter ||
    t.team_id.toLowerCase().includes(filter) ||
    (t.team_name || '').toLowerCase().includes(filter)
  );

  Dom.teamCount.textContent = `(${rows.length}/${_allTeams.length})`;

  if (!rows.length) {
    Dom.teamsBody.innerHTML = `<tr><td colspan="13" class="empty">No teams match filter.</td></tr>`;
    return;
  }

  Dom.teamsBody.innerHTML = rows.map(t => {
    const rowClass = [
      t.screen_locked   ? 'row-locked'   : '',
      t.tab_switch_count > 3 ? 'row-tababuse' : '',
    ].filter(Boolean).join(' ');

    return `
    <tr class="${rowClass}" data-team="${t.team_id}">
      <td><code>${t.team_id}</code></td>
      <td>${t.team_name || '—'}</td>
      <td>${statusBadge(t.status)}</td>
      <td><strong>${t.score ?? 0}</strong><span class="ts">/30</span></td>
      <td>${t.questions_answered ?? 0}</td>
      <td style="color:${t.tab_switch_count > 3 ? 'var(--warn)' : 'inherit'}">${t.tab_switch_count ?? 0}</td>
      <td>${t.screen_locked   ? '<span class="badge badge-danger">Yes</span>'  : '<span class="badge badge-muted">No</span>'}</td>
      <td>${t.relogin_requested ? '<span class="badge badge-warn">Req</span>' : '—'}</td>
      <td>${timerLabel(t)}</td>
      <td class="ts">${startedAtLabel(t)}</td>
      <td class="ts">${timeTakenLabel(t)}</td>
      <td class="ts">${fmtTime(t.finish_time)}</td>
      <td>
        <div style="display:flex;gap:.3rem;flex-wrap:nowrap">
          ${t.screen_locked ? `<button class="btn btn-ghost btn-sm" onclick="doUnlockScreen('${t.team_id}',event)">Unlock</button>` : ''}
          ${t.relogin_requested ? `<button class="btn btn-warn btn-sm" onclick="doApproveRelogin('${t.team_id}',event)">Re-login</button>` : ''}
          ${t.status !== 'submitted' ? `<button class="btn btn-danger btn-sm" onclick="doForceSubmit('${t.team_id}',event)">Submit</button>` : ''}
        </div>
      </td>
    </tr>`;
  }).join('');

  // Row click → audit log
  Dom.teamsBody.querySelectorAll('tr[data-team]').forEach(row => {
    row.addEventListener('click', e => {
      if (e.target.tagName === 'BUTTON') return;
      openAuditModal(row.dataset.team);
    });
  });
}

Dom.teamFilter.addEventListener('input', () => {
  _filterText = Dom.teamFilter.value;
  renderTeams();
});

// ── Re-login requests ─────────────────────────────────────────────────────

function renderRelogin() {
  const pending = _allTeams.filter(t => t.relogin_requested);
  if (!pending.length) {
    Dom.reloginCount.style.display = 'none';
    Dom.reloginBody.innerHTML = `<div class="empty">No pending re-login requests.</div>`;
    return;
  }
  Dom.reloginCount.style.display = 'inline-flex';
  Dom.reloginCount.textContent   = pending.length;

  Dom.reloginBody.innerHTML = pending.map(t => `
    <div class="relogin-row">
      <span><code>${t.team_id}</code> ${t.team_name ? `(${t.team_name})` : ''}</span>
      <button class="btn btn-warn btn-sm" onclick="doApproveRelogin('${t.team_id}',event)">Approve</button>
    </div>`).join('');
}

// ── Leaderboard ───────────────────────────────────────────────────────────

function renderLeaderboard(rows) {
  if (!rows.length) {
    Dom.leaderboardBody.innerHTML = `<div class="empty">No submissions yet.</div>`;
    return;
  }
  const medals = ['🥇','🥈','🥉'];
  Dom.leaderboardBody.innerHTML = rows.slice(0, 10).map((r, i) => `
    <div class="lb-row">
      <span class="lb-rank">${medals[i] || r.rank}</span>
      <div>
        <div style="font-weight:600">${r.team_id}</div>
        <div style="color:var(--muted);font-size:.72rem">${r.team_name || ''}</div>
      </div>
      <span class="lb-score">${r.score}/30</span>
    </div>`).join('');
}

// ── Audit modal ───────────────────────────────────────────────────────────

async function openAuditModal(teamId) {
  Dom.auditModalTitle.textContent = `Audit Log — ${teamId}`;
  Dom.auditModalBody.innerHTML    = `<div class="empty">Loading…</div>`;
  Dom.auditModal.classList.add('open');

  const r = await api('GET', `/admin/audit-logs?team_id=${teamId}`);
  if (!r || !r.ok) {
    Dom.auditModalBody.innerHTML = `<div class="empty" style="color:var(--danger)">Failed to load.</div>`;
    return;
  }
  const logs = r.data || [];
  if (!logs.length) {
    Dom.auditModalBody.innerHTML = `<div class="empty">No events recorded.</div>`;
    return;
  }
  Dom.auditModalBody.innerHTML = logs.map(e => `
    <div class="audit-entry">
      <span class="audit-type">${e.event_type}</span>
      <span class="audit-ts">${e.timestamp ? new Date(e.timestamp).toLocaleString() : ''}</span><br/>
      <span class="audit-meta">${e.metadata ? JSON.stringify(e.metadata, null, 2) : ''}</span>
    </div>`).join('');
}

Dom.closeAuditModal.addEventListener('click', () => Dom.auditModal.classList.remove('open'));
Dom.auditModal.addEventListener('click', e => { if (e.target === Dom.auditModal) Dom.auditModal.classList.remove('open'); });

// ── Action handlers ───────────────────────────────────────────────────────

async function doUnlockScreen(teamId, e) {
  e.stopPropagation();
  const r = await api('POST', '/admin/unlock-screen', { team_id: teamId });
  if (r?.ok) toast(`Screen unlocked: ${teamId}`, 'ok');
  else        toast('Failed to unlock screen', 'err');
}

async function doApproveRelogin(teamId, e) {
  e.stopPropagation();
  const r = await api('POST', '/admin/approve-relogin', { team_id: teamId });
  if (r?.ok) toast(`Re-login approved: ${teamId}`, 'ok');
  else        toast('Failed to approve re-login', 'err');
}

async function doForceSubmit(teamId, e) {
  e.stopPropagation();
  if (!confirm(`Force-submit ${teamId}? This cannot be undone.`)) return;
  const r = await api('POST', '/admin/force-submit', { team_id: teamId });
  if (r?.ok) toast(`${teamId} submitted (score: ${r.data.score})`, 'ok');
  else        toast('Force-submit failed', 'err');
}

// Expose to inline onclick handlers
window.doUnlockScreen  = doUnlockScreen;
window.doApproveRelogin = doApproveRelogin;
window.doForceSubmit   = doForceSubmit;

// ── Top-bar buttons ────────────────────────────────────────────────────────

Dom.startEventBtn.addEventListener('click', async () => {
  const raw = (Dom.startCountInput?.value || '').trim();
  const teamCount = raw ? Number(raw) : null;
  if (raw && (!Number.isInteger(teamCount) || teamCount <= 0)) {
    toast('Enter a valid positive team count', 'err');
    return;
  }

  const msg = teamCount
    ? `Start the event for first ${teamCount} waiting teams?`
    : 'Start the event? All waiting teams will be activated.';
  if (!confirm(msg)) return;

  const body = teamCount ? { team_count: teamCount } : {};
  const r = await api('POST', '/admin/start-event', body);
  if (r?.ok) {
    toast(`Event started — ${r.data.team_count} teams active`, 'ok');
    refreshStatus();
  } else {
    toast('Failed to start event', 'err');
  }
});

Dom.activateTeamBtn.addEventListener('click', async () => {
  const teamId = (Dom.activateTeamInput?.value || '').trim().toUpperCase();
  if (!teamId) {
    toast('Enter Team ID to activate', 'err');
    return;
  }
  const r = await api('POST', '/admin/activate-team', { team_id: teamId });
  if (r?.ok) {
    toast(`Team activated: ${teamId}`, 'ok');
    Dom.activateTeamInput.value = '';
    refreshStatus();
  } else {
    toast(r?.data?.message || 'Failed to activate team', 'err');
  }
});

Dom.activateTeamInput?.addEventListener('keydown', e => {
  if (e.key === 'Enter') Dom.activateTeamBtn.click();
});

Dom.endEventBtn.addEventListener('click', async () => {
  if (!confirm('End the event? All active teams will be auto-submitted.')) return;
  const r = await api('POST', '/admin/end-event');
  if (r?.ok) {
    const queued = r.data.queued_submissions ?? r.data.auto_submitted ?? 0;
    toast(`Event ended — ${queued} submissions queued`, 'ok');
    refreshStatus();
  } else {
    toast('Failed to end event', 'err');
  }
});

Dom.resetEventBtn.addEventListener('click', async () => {
  if (!confirm('🚨 WARNING: Are you sure you want to RESET THE EVENT?\n\nThis will wipe ALL SCORES, set all teams to waiting, and delete their sessions. This cannot be undone!')) return;
  const r = await api('POST', '/admin/reset-event');
  if (r?.ok) {
    toast('Event reset successfully', 'ok');
    refreshStatus();
  } else {
    toast('Failed to reset event', 'err');
  }
});

Dom.lockNetBtn.addEventListener('click', async () => {
  const r = await api('POST', '/admin/lock-network');
  if (r?.ok) {
    _lockedIp = r.data.locked_to;
    Dom.lockedIpDisplay.textContent = _lockedIp;
    sessionStorage.setItem('admin_locked_ip', _lockedIp);
    toast(`Network locked to ${_lockedIp}`, 'ok');
  } else {
    toast('Failed to lock network', 'err');
  }
});

Dom.unlockNetBtn.addEventListener('click', async () => {
  const r = await api('POST', '/admin/unlock-network');
  if (r?.ok) {
    _lockedIp = '';
    Dom.lockedIpDisplay.textContent = 'unrestricted';
    sessionStorage.removeItem('admin_locked_ip');
    toast('Network unlocked', 'ok');
  } else {
    toast('Failed to unlock network', 'err');
  }
});

Dom.exportBtn.addEventListener('click', async () => {
  Dom.exportBtn.disabled = true;
  Dom.exportBtn.textContent = '↗ Exporting…';
  const r = await api('POST', '/admin/export-sheets');
  Dom.exportBtn.disabled = false;
  Dom.exportBtn.textContent = '↗ Export to Sheets';

  if (r?.ok) {
    toast(`Exported ${r.data.exported} teams to Sheets`, 'ok');
    window.open(r.data.sheet_url, '_blank');
  } else {
    toast(`Export failed: ${r?.data?.message || 'unknown error'}`, 'err');
  }
});

// ── Boot ──────────────────────────────────────────────────────────────────

window.addEventListener('DOMContentLoaded', () => {
  if (getToken()) {
    showDashboard();
    startPolling();
    refreshLeaderboard();
    fetchNetworkStatus();
  } else {
    showLogin();
  }
});
