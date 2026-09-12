<template>
  <div v-if="features?.enableCaptcha" ref="container" class="q-my-sm" />
</template>

<script lang="ts">
import { mapGetters } from 'vuex';
import { defineComponent } from 'vue';

// Cloudflare Turnstile is the only provider referenced in the frontend, and
// only in this file — swapping providers means editing here + the backend
// verify helper, nothing else.
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

// Load the script once for the whole app; every widget instance awaits the
// same promise so the ones that mount before it loads just queue.
let turnstileReady: Promise<void> | null = null;
function loadTurnstile(): Promise<void> {
  if (turnstileReady) return turnstileReady;
  turnstileReady = new Promise((resolve, reject) => {
    if (window.turnstile) {
      resolve();
      return;
    }
    const script = document.createElement('script');
    script.src = TURNSTILE_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => {
      // Drop the cached rejection so a later mount can retry the load instead
      // of being stuck "unavailable" for the rest of the SPA session.
      turnstileReady = null;
      reject(new Error('Turnstile script failed to load'));
    };
    document.head.appendChild(script);
  });
  return turnstileReady;
}

export default defineComponent({
  name: 'CaptchaWidget',
  props: {
    // Binds the minted token to the form (register / login / password_reset);
    // the backend re-checks it.
    action: { type: String, default: undefined },
    modelValue: { type: String, default: '' },
  },
  emits: ['update:modelValue', 'captcha-unavailable'],
  data() {
    return {
      widgetId: null as string | null,
    };
  },
  computed: {
    // Self-contained so hosts don't have to map `keys`.
    ...mapGetters('config', ['keys', 'features']),
  },
  mounted() {
    if (this.features?.enableCaptcha) this.renderWidget();
  },
  beforeUnmount() {
    this.removeWidget();
  },
  methods: {
    async renderWidget() {
      const siteKey = this.keys?.captchaSiteKey;
      if (!siteKey) {
        this.$emit('captcha-unavailable');
        return;
      }
      try {
        await loadTurnstile();
      } catch {
        this.$emit('captcha-unavailable');
        return;
      }
      const container = this.$refs.container as HTMLElement | undefined;
      if (!window.turnstile || !container) {
        this.$emit('captcha-unavailable');
        return;
      }
      this.widgetId = window.turnstile.render(container, {
        sitekey: siteKey,
        action: this.action,
        callback: (token: string) => this.$emit('update:modelValue', token),
        // Clear the token so a >300s-old one is never submitted.
        'expired-callback': () => this.$emit('update:modelValue', ''),
        // A blocked/slow script, bad key, or non-allowed origin (native
        // builds) all surface here — tell the host instead of leaving a
        // permanently-disabled submit button.
        'error-callback': () => {
          this.$emit('update:modelValue', '');
          this.$emit('captcha-unavailable');
        },
      });
    },
    // Called by the host after a spent-token error so the retry carries a
    // fresh token (Turnstile tokens are single-use).
    reset() {
      if (window.turnstile && this.widgetId !== null) {
        window.turnstile.reset(this.widgetId);
        this.$emit('update:modelValue', '');
      }
    },
    removeWidget() {
      if (window.turnstile && this.widgetId !== null) {
        window.turnstile.remove(this.widgetId);
        this.widgetId = null;
      }
    },
  },
});
</script>
