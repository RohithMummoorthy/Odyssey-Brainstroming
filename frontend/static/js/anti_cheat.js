/**
 * anti_cheat.js — Math Quiz Anti-Cheat Module
 *
 * Exports a single init(getState) function called from quiz.js after questions load.
 *
 * Features:
 *   1. Fullscreen lock with admin-unlock polling
 *   2. Tab/visibility switch detection + toast
 *   3. DOM snapshot every 90 s
 *   4. Blocked interactions (right-click, copy shortcuts, text select, drag)
 */

'use strict';

// ── Auth helpers (duplicated intentionally — no module bundler) ─────────────
function _getToken() { return localStorage.getItem('mq_token') || ''; }

function _authHeaders() {
  return {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${_getToken()}`,
  };
}

// ── Internal state ─────────────────────────────────────────────────────────
let _getQuizState = null;   // injected by init()
let _isLocked     = false;
let _switchCount  = 0;
let _isResetting  = false;
let _lastBlurTime = 0;
let _lockPollId   = null;
let _snapshotId   = null;

// ── DOM Elements ────────────────────────────────────────────────────────────

function _getOverlay() { return document.getElementById('acOverlay'); }
function _getToast()   { return document.getElementById('acToast'); }

// ─────────────────────────────────────────────────────────────────────────────
// 1. AUDIT LOG helper
// ─────────────────────────────────────────────────────────────────────────────

async function _logAudit(eventType, metadata = {}) {
  try {
    await fetch('/audit/log', {
      method:  'POST',
      headers: _authHeaders(),
      body:    JSON.stringify({ event_type: eventType, metadata }),
    });
  } catch (_) {
    // Non-fatal — best-effort audit
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 2. LOCK / UNLOCK screen
// ─────────────────────────────────────────────────────────────────────────────

function _lockScreen(reason) {
  if (_isLocked) return;
  _isLocked = true;

  const overlay = _getOverlay();
  if (overlay) {
    document.getElementById('acOverlayReason').textContent = reason || 'Unauthorized action detected.';
    overlay.classList.add('visible');
  }

  // Disable all quiz inputs
  document.querySelectorAll('.option-btn, .nav-btn, .submit-btn').forEach(el => {
    el.disabled = true;
  });

  // Start polling for admin unlock
  _startLockPoll();
}

function _unlockScreen() {
  _isLocked = false;

  const overlay = _getOverlay();
  if (overlay) overlay.classList.remove('visible');

  // Re-enable quiz inputs (only if quiz not submitted)
  const state = _getQuizState ? _getQuizState() : {};
  if (!state.submitted) {
    document.querySelectorAll('.option-btn, .nav-btn, .submit-btn').forEach(el => {
      el.disabled = false;
    });
  }

  _stopLockPoll();

  // Attempt to re-enter fullscreen
  _requestFullscreen();
}

// ─────────────────────────────────────────────────────────────────────────────
// 3. FULLSCREEN
// ─────────────────────────────────────────────────────────────────────────────

function _requestFullscreen() {
  const el = document.documentElement;
  if (el.requestFullscreen) {
    el.requestFullscreen().catch(() => { /* user may deny */ });
  } else if (el.webkitRequestFullscreen) {
    el.webkitRequestFullscreen();
  } else if (el.mozRequestFullScreen) {
    el.mozRequestFullScreen();
  }
}

async function _forceResetAndLogout() {
  if (_isResetting) return;
  _isResetting = true;
  _lockScreen('Resetting session due to security violation...');
  try {
    await fetch('/api/reset-progress', { method: 'POST', headers: _authHeaders() });
  } catch (e) {}
  localStorage.removeItem('mq_token');
  localStorage.removeItem('mq_team_id');
  window.location.href = '/login';
}

function _onFullscreenChange() {
  const isFullscreen = !!(
    document.fullscreenElement        ||
    document.webkitFullscreenElement  ||
    document.mozFullScreenElement
  );

  if (!isFullscreen && !_isLocked && !_isResetting) {
    const state   = _getQuizState ? _getQuizState() : {};
    const qNum    = state.currentIndex != null ? state.currentIndex + 1 : 0;

    _logAudit('fullscreen_exit', { question_number: qNum });
    _forceResetAndLogout();
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 4. ADMIN UNLOCK POLLING
// ─────────────────────────────────────────────────────────────────────────────

function _startLockPoll() {
  _stopLockPoll();
  _lockPollId = setInterval(async () => {
    try {
      const res  = await fetch('/api/lock-status', { headers: _authHeaders() });
      const data = await res.json();
      if (res.ok && data.locked === false) {
        _unlockScreen();
      }
    } catch (_) { /* non-fatal */ }
  }, 5_000);
}

function _stopLockPoll() {
  if (_lockPollId !== null) {
    clearInterval(_lockPollId);
    _lockPollId = null;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 5. TAB / VISIBILITY DETECTION
// ─────────────────────────────────────────────────────────────────────────────

function _onVisibilityChange(e) {
  if (_isResetting || _isLocked) return;
  
  if (e && e.type === 'visibilitychange' && !document.hidden) return;
  
  const now = Date.now();
  if (now - _lastBlurTime < 1000) return;
  _lastBlurTime = now;

  _switchCount++;
  const state = _getQuizState ? _getQuizState() : {};
  const qNum  = state.currentIndex != null ? state.currentIndex + 1 : 0;

  _logAudit('tab_switch', { question_number: qNum, count: _switchCount, event_type: e ? e.type : 'unknown' });

  if (_switchCount >= 3) {
    _lockScreen('You have been blocked for leaving the quiz interface multiple times (3). Contact Admin.');
  } else {
    _showToast(`Focus lost / Tab switch detected. Admin notified. (Count: ${_switchCount})`);
  }
}

function _showToast(message) {
  const toast = _getToast();
  if (!toast) return;

  toast.textContent = message;
  toast.classList.add('visible');

  clearTimeout(toast._hideTimer);
  toast._hideTimer = setTimeout(() => toast.classList.remove('visible'), 4_000);
}

// ─────────────────────────────────────────────────────────────────────────────
// 6. DOM SNAPSHOT
// ─────────────────────────────────────────────────────────────────────────────

function _captureSnapshot() {
  const state = _getQuizState ? _getQuizState() : {};
  const qNum  = state.currentIndex != null ? state.currentIndex + 1 : 0;

  try {
    // Clone DOM so we can manipulate without affecting the live page
    const clone = document.documentElement.cloneNode(true);

    // Remove <img> tags
    clone.querySelectorAll('img').forEach(el => el.remove());

    // Extract only answers-related elements
    const relevant = [];
    clone.querySelectorAll('.option-btn, .question-area, #questionCard').forEach(el => {
      relevant.push(el.outerHTML);
    });
    const compressed = relevant.join('\n');

    _logAudit('dom_snapshot', {
      question_number: qNum,
      snapshot:        compressed.slice(0, 8000),  // cap at 8 KB
    });
  } catch (_) { /* non-fatal */ }
}

// ─────────────────────────────────────────────────────────────────────────────
// 7. BLOCKED INTERACTIONS
// ─────────────────────────────────────────────────────────────────────────────

const _BLOCKED_KEYS = new Set(['c','v','u','s','a','p']);

function _blockInteractions() {
  // Right-click
  document.addEventListener('contextmenu', e => e.preventDefault(), true);

  // Ctrl shortcuts
  document.addEventListener('keydown', e => {
    if (e.ctrlKey && _BLOCKED_KEYS.has(e.key.toLowerCase())) {
      e.preventDefault();
    }
    // F12 developer tools
    if (e.key === 'F12') e.preventDefault();
    // Ctrl+Shift+I / Ctrl+Shift+J
    if (e.ctrlKey && e.shiftKey && ['I','J','C'].includes(e.key)) e.preventDefault();
  }, true);

  // Text selection
  document.addEventListener('selectstart', e => e.preventDefault(), true);

  // Drag
  document.addEventListener('dragstart', e => e.preventDefault(), true);
}

// ─────────────────────────────────────────────────────────────────────────────
// 8. START QUIZ button handler (fullscreen entry point)
// ─────────────────────────────────────────────────────────────────────────────

function _bindStartButton() {
  const btn = document.getElementById('startQuizBtn');
  if (!btn) return;

  btn.addEventListener('click', () => {
    _requestFullscreen();
    btn.closest('#startOverlay')?.remove();
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// 9. PUBLIC: init()
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Initialise all anti-cheat features.
 *
 * @param {() => object} getStateFn  — callback that returns current quiz state
 *                                     {currentIndex, submitted}
 */
function init(getStateFn) {
  _getQuizState = getStateFn;

  // Block interactions immediately
  _blockInteractions();

  // Fullscreen change listener
  document.addEventListener('fullscreenchange',       _onFullscreenChange);
  document.addEventListener('webkitfullscreenchange', _onFullscreenChange);
  document.addEventListener('mozfullscreenchange',    _onFullscreenChange);

  // Tab / visibility switch
  document.addEventListener('visibilitychange', _onVisibilityChange);
  window.addEventListener('blur', _onVisibilityChange);

  // DOM snapshot every 90 seconds
  _snapshotId = setInterval(_captureSnapshot, 90_000);

  // Bind "Start Quiz" button which triggers fullscreen entry
  _bindStartButton();
}

/**
 * Tear down all listeners and timers (call on quiz completion).
 */
function destroy() {
  document.removeEventListener('fullscreenchange',       _onFullscreenChange);
  document.removeEventListener('webkitfullscreenchange', _onFullscreenChange);
  document.removeEventListener('mozfullscreenchange',    _onFullscreenChange);
  document.removeEventListener('visibilitychange',       _onVisibilityChange);
  window.removeEventListener('blur', _onVisibilityChange);
  _stopLockPoll();
  if (_snapshotId) { clearInterval(_snapshotId); _snapshotId = null; }
}

// Expose to global scope (no bundler — loaded via <script> tag)
window.AntiCheat = { init, destroy };
