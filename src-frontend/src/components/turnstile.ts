// Cloudflare Turnstile is the only provider referenced in the frontend, and
// only here and in CaptchaWidget.vue — swapping providers means editing those
// two + the backend verify helper, nothing else.
interface TurnstileRenderOptions {
  sitekey: string;
  action?: string;
  callback?: (token: string) => void;
  'expired-callback'?: () => void;
  'error-callback'?: () => void;
}
interface TurnstileApi {
  render: (el: HTMLElement | string, opts: TurnstileRenderOptions) => string;
  reset: (id?: string) => void;
  remove: (id?: string) => void;
}
declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

const TURNSTILE_SRC =
  'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';

// A connection that is silently dropped (a firewall, an offline kiosk) never
// fires onerror until the browser gives up, which can take minutes. Past this,
// the widget offers Retry instead of an empty box and a disabled button.
const LOAD_TIMEOUT_MS = 15000;

// Load the script once for the whole app; every widget instance awaits the
// same promise so the ones that mount before it loads just queue.
let turnstileReady: Promise<void> | null = null;
export function loadTurnstile(): Promise<void> {
  if (turnstileReady) return turnstileReady;
  turnstileReady = new Promise((resolve, reject) => {
    if (window.turnstile) {
      resolve();
      return;
    }
    const script = document.createElement('script');
    const timer = setTimeout(() => {
      // Detached so a load abandoned here can't settle later and clear the
      // cache a retry has since filled.
      script.onload = null;
      script.onerror = null;
      failed();
    }, LOAD_TIMEOUT_MS);
    const failed = () => {
      clearTimeout(timer);
      // Drop the cached rejection so a later mount can retry the load instead
      // of being stuck "unavailable" for the rest of the SPA session.
      turnstileReady = null;
      reject(new Error('Turnstile script failed to load'));
    };
    script.src = TURNSTILE_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => {
      clearTimeout(timer);
      resolve();
    };
    script.onerror = failed;
    document.head.appendChild(script);
  });
  return turnstileReady;
}
