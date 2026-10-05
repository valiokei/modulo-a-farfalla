const desktop = import.meta.env.VITE_DESKTOP === 'true';
let lastReported = 0;

export function reportClientFailure() {
  if (!desktop || Date.now() - lastReported < 30_000) return;
  lastReported = Date.now();
  void fetch('/desktop/diagnostics/client-event', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({event: 'client_failed'})
  }).catch(() => {});
}

if (desktop) {
  window.addEventListener('error', reportClientFailure);
  window.addEventListener('unhandledrejection', reportClientFailure);
}
