<template>
  <div v-if="features?.enableCaptcha" class="q-my-sm">
    <!-- v-show, not v-if: render() needs this element to exist. -->
    <div v-show="!unavailable" ref="container" />

    <!-- Turnstile fails for reasons a member can clear (flaky network, a
         blocked script) and reasons they can't (a native build's origin isn't
         on the site key). The server requires a token either way, so there is
         no submitting past this — offer the retry and say what happened. -->
    <q-banner v-if="unavailable" dense class="bg-negative text-white">
      {{ $t('error.captchaUnavailable') }}
      <template #action>
        <q-btn flat dense :label="$t('button.retry')" @click="retry" />
      </template>
    </q-banner>
  </div>
</template>

<script lang="ts">
import { mapGetters } from 'vuex';
import { defineComponent } from 'vue';
import { loadTurnstile } from './turnstile';

export default defineComponent({
  name: 'CaptchaWidget',
  props: {
    // Binds the minted token to the form (register / login / password_reset);
    // the backend re-checks it.
    action: { type: String, default: undefined },
    modelValue: { type: String, default: '' },
  },
  emits: ['update:modelValue'],
  data() {
    return {
      widgetId: null as string | null,
      unavailable: false,
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
    // Otherwise the host keeps a token with no widget behind it, and the next
    // mount starts with Submit enabled on a token that may have expired.
    this.$emit('update:modelValue', '');
  },
  methods: {
    async renderWidget() {
      const siteKey = this.keys?.captchaSiteKey;
      if (!siteKey) {
        this.fail();
        return;
      }
      try {
        await loadTurnstile();
      } catch {
        this.fail();
        return;
      }
      const container = this.$refs.container as HTMLElement | undefined;
      if (!window.turnstile || !container) {
        this.fail();
        return;
      }
      this.widgetId = window.turnstile.render(container, {
        sitekey: siteKey,
        action: this.action,
        callback: (token: string) => this.$emit('update:modelValue', token),
        // Clear the token so a >300s-old one is never submitted.
        'expired-callback': () => this.$emit('update:modelValue', ''),
        // A blocked/slow script, bad key, or non-allowed origin (native
        // builds) all surface here.
        'error-callback': () => this.fail(),
      });
    },
    fail() {
      this.$emit('update:modelValue', '');
      this.unavailable = true;
    },
    retry() {
      // A failed script load clears the module-level cache, so this re-fetches
      // it; a widget that rendered but errored has to be torn down first.
      this.removeWidget();
      this.unavailable = false;
      this.renderWidget();
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
