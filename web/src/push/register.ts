// The worker is registered on every load, not only when the person asks for notifications: it
// has to exist before a push can arrive, and a registration that already exists is a no-op.
export function registerServiceWorker(): void {
  if (!('serviceWorker' in navigator) || !window.isSecureContext) return
  navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {
    // Without a worker the page works as before; the notifications page reports the state.
  })
}
