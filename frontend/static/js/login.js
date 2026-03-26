/**
 * login.js — Vanilla JS login handler for Math Quiz platform.
 *
 * On form submit:
 *   1. POST /login with {team_id, pin}
 *   2. Store token, team_id, set_assigned in localStorage
 *   3. Redirect to /quiz on success
 *   4. Show clear error messages for known error codes
 */

'use strict';

// ── DOM references ────────────────────────────────────────────────────────
const form          = document.getElementById('loginForm');
const teamIdInput   = document.getElementById('teamId');
const pinInput      = document.getElementById('pin');
const loginBtn      = document.getElementById('loginBtn');
const togglePinBtn  = document.getElementById('togglePin');
const bannerError   = document.getElementById('bannerError');
const bannerWarning = document.getElementById('bannerWarning');

// ── Error code → human-readable messages ─────────────────────────────────
const ERROR_MESSAGES = {
  invalid_credentials: 'Incorrect Team ID or PIN. Please try again.',
  already_submitted:   'Your team has already submitted the quiz.',
  network_violation:   'Access denied. Please connect to the venue Wi-Fi and try again.',
  token_expired:       'Your session has expired. Please log in again.',
  bad_request:         'Team ID and PIN are required.',
  server_error:        'A server error occurred. Please try again shortly.',
};

// ── Helpers ───────────────────────────────────────────────────────────────

/**
 * Display a banner message.
 * @param {'error'|'warning'} type
 * @param {string} message
 */
function showBanner(type, message) {
  hideBanners();
  const el = type === 'error' ? bannerError : bannerWarning;
  el.textContent = message;
  el.classList.add('visible');
}

function hideBanners() {
  bannerError.classList.remove('visible');
  bannerWarning.classList.remove('visible');
  bannerError.textContent   = '';
  bannerWarning.textContent = '';
}

/** Toggle loading state on the submit button. */
function setLoading(loading) {
  loginBtn.disabled = loading;
  loginBtn.classList.toggle('loading', loading);
  teamIdInput.disabled = loading;
  pinInput.disabled    = loading;
}

/** Normalise a team_id — uppercase, trim whitespace. */
function normaliseTeamId(raw) {
  return raw.trim().toUpperCase();
}

/** Persist auth data to localStorage. */
function saveAuth({ token, team_id, set_assigned, remaining_seconds, saved_answers }) {
  localStorage.setItem('mq_token',             token);
  localStorage.setItem('mq_team_id',           team_id);
  localStorage.setItem('mq_set_assigned',      set_assigned);
  localStorage.setItem('mq_remaining_seconds', String(remaining_seconds));
  // saved_answers may be an object — serialise it
  localStorage.setItem('mq_saved_answers',     JSON.stringify(saved_answers || {}));
}

// ── PIN show / hide toggle ────────────────────────────────────────────────
togglePinBtn.addEventListener('click', () => {
  const isHidden = pinInput.type === 'password';
  pinInput.type         = isHidden ? 'text' : 'password';
  togglePinBtn.textContent = isHidden ? '🙈' : '👁';
  togglePinBtn.setAttribute('aria-label', isHidden ? 'Hide PIN' : 'Show PIN');
});

// ── Form submission ───────────────────────────────────────────────────────
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  hideBanners();

  const team_id = normaliseTeamId(teamIdInput.value);
  const pin     = pinInput.value;

  // Basic client-side validation
  if (!team_id) {
    teamIdInput.focus();
    showBanner('error', 'Please enter your Team ID.');
    return;
  }
  if (!pin) {
    pinInput.focus();
    showBanner('error', 'Please enter your PIN.');
    return;
  }

  setLoading(true);

  try {
    const response = await fetch('/login', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ team_id, pin }),
    });

    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error('server_error');
    }

    if (response.ok) {
      // ── Success ──────────────────────────────────────────────────────
      saveAuth(data);
      // Redirect to quiz page
      window.location.href = '/quiz';
      return; // keep spinner on while navigating
    }

    // ── Known error codes ─────────────────────────────────────────────
    const code    = data.error || 'server_error';
    const message = ERROR_MESSAGES[code] || data.message || ERROR_MESSAGES.server_error;

    if (code === 'already_submitted') {
      showBanner('warning', message);
    } else {
      showBanner('error', message);
    }

  } catch (networkErr) {
    // Covers fetch() failures (offline, CORS issues, etc.)
    showBanner('error', 'Cannot reach the server. Check your network connection.');
  } finally {
    setLoading(false);
  }
});

// ── Auto-focus Team ID on load ────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  teamIdInput.focus();

  // If already logged in, redirect straight to quiz
  const existingToken = localStorage.getItem('mq_token');
  if (existingToken) {
    window.location.href = '/quiz';
  }
});
