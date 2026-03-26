/**
 * quiz.js — Math Quiz Platform, vanilla JS quiz engine.
 *
 * State machine:
 *   loading → (error | submitted | quiz)
 *   quiz → submitted
 *
 * Server sync:
 *   - /api/questions  on load
 *   - /session-status every 30 s (timer re-sync)
 *   - /save-progress  every 30 s + on every answer select
 *   - /submit         on button click or timer expiry
 *
 * Anti-cheat:
 *   - AntiCheat.init() called after questions render (loaded from anti_cheat.js)
 */


'use strict';

// ── Auth helpers ────────────────────────────────────────────────────────────

function getToken() { return localStorage.getItem('mq_token') || ''; }
function getTeamId() { return localStorage.getItem('mq_team_id') || ''; }

function authHeaders() {
  return {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${getToken()}`,
  };
}

/** Redirect to login if we have no token. */
function guardAuth() {
  if (!getToken()) { window.location.href = '/login'; }
}

// ── DOM refs ────────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);

const Dom = {
  loading:     $('loadingScreen'),
  error:       $('errorScreen'),
  errorMsg:    $('errorMsg'),
  score:       $('scoreScreen'),
  scoreNum:    $('scoreNum'),
  scoreDenom:  $('scoreDenom'),
  scoreTime:   $('scoreFinishTime'),
  header:      $('quizHeader'),
  teamLabel:   $('teamLabel'),
  layout:      $('quizLayout'),
  qGrid:       $('qGrid'),
  qMeta:       $('qMeta'),
  qText:       $('qText'),
  optList:     $('optionsList'),
  prevBtn:     $('prevBtn'),
  nextBtn:     $('nextBtn'),
  submitBtn:   $('submitBtn'),
  saveInd:     $('saveIndicator'),
  timerText:   $('timerText'),
  timerDisp:   $('timerDisplay'),
};

// ── Application state ───────────────────────────────────────────────────────

let state = {
  questions:         [],   // [{question_number, question_id, question_text, options:[{label,text}]}]
  total:             30,
  currentIndex:      0,    // 0-based
  answersMap:        {},   // {question_id_str: selected_label}
  remainingSeconds:  1800,
  submitInProgress:  false,
  submitted:         false,
};

// Interval handles
let _timerIntervalId  = null;   // client-side countdown tick (every 1 s)
let _syncIntervalId   = null;   // server re-sync (every 30 s)
let _autoSaveId       = null;   // periodic auto-save (every 30 s)

// ── Screens ─────────────────────────────────────────────────────────────────

function showScreen(name) {
  Dom.loading.style.display = 'none';
  Dom.error.style.display   = 'none';
  Dom.score.classList.remove('visible');
  Dom.layout.style.display  = 'none';
  Dom.header.style.display  = 'none';

  if (name === 'loading') {
    Dom.loading.style.display = 'flex';
  } else if (name === 'error') {
    Dom.error.style.display = 'flex';
  } else if (name === 'score') {
    Dom.header.style.display = 'flex';
    Dom.score.classList.add('visible');
  } else if (name === 'quiz') {
    Dom.header.style.display = 'flex';
    Dom.layout.style.display = 'grid';
  }
}

// ── Timer ────────────────────────────────────────────────────────────────────

function formatTime(seconds) {
  const m = Math.floor(seconds / 60).toString().padStart(2, '0');
  const s = (seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

function updateTimerDisplay() {
  Dom.timerText.textContent = formatTime(state.remainingSeconds);
  Dom.timerDisp.classList.remove('warn', 'urgent');
  if (state.remainingSeconds <= 60)       Dom.timerDisp.classList.add('urgent');
  else if (state.remainingSeconds <= 300) Dom.timerDisp.classList.add('warn');
}

function startClientTimer() {
  clearInterval(_timerIntervalId);
  _timerIntervalId = setInterval(() => {
    if (state.submitted) { clearInterval(_timerIntervalId); return; }
    if (state.remainingSeconds > 0) {
      state.remainingSeconds--;
      updateTimerDisplay();
    }
    if (state.remainingSeconds <= 0) {
      clearInterval(_timerIntervalId);
      handleTimerExpired();
    }
  }, 1000);
}

async function syncTimerFromServer() {
  if (state.submitted) return;
  try {
    const res  = await fetch('/session-status', { headers: authHeaders() });
    const data = await res.json();
    if (data.status === 'submitted') {
      handleAlreadySubmitted(data);
      return;
    }
    if (typeof data.remaining_seconds === 'number') {
      state.remainingSeconds = data.remaining_seconds;
      updateTimerDisplay();
    }
  } catch (_) { /* non-fatal — keep using client countdown */ }
}

function startServerSync() {
  clearInterval(_syncIntervalId);
  _syncIntervalId = setInterval(syncTimerFromServer, 30_000);
}

// ── Auto-save ────────────────────────────────────────────────────────────────

function setSaveIndicator(status, msg) {
  Dom.saveInd.className = `save-indicator ${status}`;
  Dom.saveInd.textContent = msg;
}

async function saveProgress() {
  if (state.submitted) return;
  setSaveIndicator('saving', 'Saving…');
  try {
    const res = await fetch('/save-progress', {
      method:  'POST',
      headers: authHeaders(),
      body:    JSON.stringify({ answers: state.answersMap }),
    });
    if (res.ok) {
      setSaveIndicator('saved', `Saved at ${new Date().toLocaleTimeString()}`);
    } else {
      setSaveIndicator('error', 'Save failed — will retry');
    }
  } catch (_) {
    setSaveIndicator('error', 'Network error — will retry');
  }
}

function startAutoSave() {
  clearInterval(_autoSaveId);
  _autoSaveId = setInterval(saveProgress, 30_000);
}

// ── Sidebar grid ─────────────────────────────────────────────────────────────

function renderGrid() {
  Dom.qGrid.innerHTML = '';
  state.questions.forEach((q, idx) => {
    const dot = document.createElement('button');
    dot.className = 'q-dot';
    dot.setAttribute('role', 'listitem');
    dot.setAttribute('aria-label', `Question ${idx + 1}`);
    dot.textContent = idx + 1;
    dot.dataset.idx = idx;

    const qIdStr = String(q.question_id);
    if (state.answersMap[qIdStr]) dot.classList.add('answered');
    if (idx === state.currentIndex)  dot.classList.add('current');

    dot.addEventListener('click', () => navigateTo(idx));
    Dom.qGrid.appendChild(dot);
  });
}

function updateGrid() {
  const dots = Dom.qGrid.querySelectorAll('.q-dot');
  dots.forEach((dot, idx) => {
    const q      = state.questions[idx];
    const qIdStr = String(q.question_id);
    dot.classList.toggle('answered', !!state.answersMap[qIdStr]);
    dot.classList.toggle('current',  idx === state.currentIndex);
  });
}

// ── Question rendering ───────────────────────────────────────────────────────

function renderQuestion(idx) {
  const q      = state.questions[idx];
  const qIdStr = String(q.question_id);
  const saved  = state.answersMap[qIdStr] || null;
  const isLast = idx === state.questions.length - 1;
  const isFirst= idx === 0;

  Dom.qMeta.textContent  = `Question ${q.question_number} of ${state.total}`;
  Dom.qText.textContent  = q.question_text;

  Dom.optList.innerHTML = '';
  q.options.forEach(opt => {
    const li  = document.createElement('li');
    const btn = document.createElement('button');
    btn.className  = 'option-btn';
    btn.disabled   = state.submitted;
    btn.setAttribute('role', 'option');
    btn.setAttribute('aria-selected', saved === opt.label ? 'true' : 'false');

    const labelSpan = document.createElement('span');
    labelSpan.className   = 'option-label';
    labelSpan.textContent = opt.label;

    const textSpan = document.createElement('span');
    textSpan.textContent = opt.text;

    btn.appendChild(labelSpan);
    btn.appendChild(textSpan);

    if (saved === opt.label) btn.classList.add('selected');

    btn.addEventListener('click', () => onOptionSelected(q, opt.label));
    li.appendChild(btn);
    Dom.optList.appendChild(li);
  });

  // Navigation buttons
  Dom.prevBtn.disabled = isFirst;
  Dom.nextBtn.style.display   = isLast ? 'none'  : 'inline-flex';
  Dom.submitBtn.style.display = isLast ? 'inline-flex' : 'none';
  Dom.nextBtn.disabled  = false;
}

function navigateTo(idx) {
  if (idx < 0 || idx >= state.questions.length) return;
  state.currentIndex = idx;
  renderQuestion(idx);
  updateGrid();
}

// ── Answer selection ─────────────────────────────────────────────────────────

async function onOptionSelected(q, label) {
  if (state.submitted) return;
  const qIdStr = String(q.question_id);
  state.answersMap[qIdStr] = label;

  // Re-render options to update selection highlight
  renderQuestion(state.currentIndex);
  updateGrid();

  // Save to server immediately
  await saveProgress();
}

// ── Submission ────────────────────────────────────────────────────────────────

function disableAllInputs() {
  document.querySelectorAll('.option-btn, .nav-btn, .submit-btn').forEach(el => {
    el.disabled = true;
  });
}

function handleAlreadySubmitted(data) {
  state.submitted = true;
  clearInterval(_timerIntervalId);
  clearInterval(_syncIntervalId);
  clearInterval(_autoSaveId);
  showScore(data.score ?? 0, 30, data.finish_time ?? null);
}

async function handleTimerExpired() {
  if (state.submitInProgress || state.submitted) return;
  setSaveIndicator('saving', 'Time is up — submitting…');
  disableAllInputs();
  await submitQuiz();
}

async function submitQuiz() {
  if (state.submitInProgress || state.submitted) return;
  state.submitInProgress = true;
  Dom.submitBtn.disabled = true;

  clearInterval(_timerIntervalId);
  clearInterval(_syncIntervalId);
  clearInterval(_autoSaveId);

  try {
    const res  = await fetch('/submit', { method: 'POST', headers: authHeaders() });
    const data = await res.json();

    if (res.ok) {
      state.submitted = true;
      showScore(data.score, data.total ?? 30, data.finish_time);
    } else {
      setSaveIndicator('error', 'Submission failed. Please try again.');
      Dom.submitBtn.disabled = false;
    }
  } catch (_) {
    setSaveIndicator('error', 'Network error. Please retry submission.');
    Dom.submitBtn.disabled = false;
  } finally {
    state.submitInProgress = false;
  }
}

function showScore(score, total, finishTime) {
  state.submitted = true;

  // Tear down anti-cheat (no need for fullscreen lock on score screen)
  if (window.AntiCheat) window.AntiCheat.destroy();

  Dom.scoreNum.textContent   = score;
  Dom.scoreDenom.textContent = `/${total}`;

  if (finishTime) {
    const d = new Date(finishTime);
    Dom.scoreTime.textContent = `Finished at ${d.toLocaleTimeString()} on ${d.toLocaleDateString()}`;
  } else {
    Dom.scoreTime.textContent = '';
  }

  showScreen('score');
}

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  guardAuth();
  showScreen('loading');

  Dom.teamLabel.textContent = `Team: ${getTeamId()}`;

  let data;
  try {
    const res = await fetch('/api/questions', { headers: authHeaders() });
    data = await res.json();

    if (!res.ok) {
      // Token expired → send back to login
      if (res.status === 401) {
        localStorage.clear();
        window.location.href = '/login';
        return;
      }
      throw new Error(data.message || `HTTP ${res.status}`);
    }
  } catch (err) {
    Dom.errorMsg.textContent = `Failed to load questions: ${err.message}`;
    showScreen('error');
    return;
  }

  // Already submitted?
  if (data.status === 'submitted') {
    showScore(data.score ?? 0, 30, data.finish_time ?? null);
    return;
  }

  // Populate state
  state.questions        = data.questions || [];
  state.total            = data.total || state.questions.length;
  state.remainingSeconds = data.remaining_seconds ?? 1800;
  state.answersMap       = data.saved_answers || {};

  if (!state.questions.length) {
    Dom.errorMsg.textContent = 'No questions available. Please contact an invigilator.';
    showScreen('error');
    return;
  }

  // Render
  showScreen('quiz');
  renderGrid();
  renderQuestion(0);
  updateTimerDisplay();

  // Start timers and periodic tasks
  startClientTimer();
  startServerSync();
  startAutoSave();

  // Initialise anti-cheat (loaded from anti_cheat.js before this script)
  if (window.AntiCheat) {
    window.AntiCheat.init(() => ({
      currentIndex: state.currentIndex,
      submitted:    state.submitted,
    }));
  }
}

// ── Event listeners ──────────────────────────────────────────────────────────

Dom.prevBtn.addEventListener('click', () => navigateTo(state.currentIndex - 1));
Dom.nextBtn.addEventListener('click', () => navigateTo(state.currentIndex + 1));
Dom.submitBtn.addEventListener('click', async () => {
  const answered = Object.keys(state.answersMap).length;
  const total    = state.questions.length;
  if (answered < total) {
    const ok = confirm(
      `You have answered ${answered} of ${total} questions. Submit anyway?`
    );
    if (!ok) return;
  }
  await submitQuiz();
});

// ── Boot ─────────────────────────────────────────────────────────────────────

window.addEventListener('DOMContentLoaded', init);
