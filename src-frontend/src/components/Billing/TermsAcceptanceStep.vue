<template>
  <div>
    <div class="text-h6 q-py-md">{{ $t('signup.acceptTerms') }}</div>
    <div class="row">
      <terms-acceptance-card
        v-for="(card, i) in cards"
        :key="i"
        :icon="card.icon"
        :title="card.title"
        :body-html="card.body_html"
        :checkbox-text="card.checkbox_text"
        v-model="accepted[i]"
        class="col-12 col-md-6"
      />
    </div>

    <div class="row justify-start q-mt-md">
      <q-space />
      <q-btn
        :disable="!allAccepted || submitting"
        :loading="submitting"
        @click="submit"
        color="primary"
        :label="$t('button.continue')"
      />
    </div>
  </div>
</template>

<script lang="ts">
import { defineComponent, PropType } from 'vue';
import { api } from 'boot/axios';
import TermsAcceptanceCard from '@components/Billing/TermsAcceptanceCard.vue';

// The terms & conditions step, shared by both signup steppers. It normally
// runs before payment (SelectTier); SignupRequiredSteps hosts it too, as the
// only way for a member who somehow reached the post-payment steps without
// accepting to unblock themselves.
export default defineComponent({
  name: 'TermsAcceptanceStep',
  components: { TermsAcceptanceCard },
  props: {
    // Cards as configured in TERMS_ACCEPTANCE_CARDS. Both parents already
    // read these to build their step list, so they pass them down.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    cards: { type: Array as PropType<any[]>, required: true },
  },
  emits: ['accepted'],
  data() {
    return {
      accepted: new Array(this.cards.length).fill(false) as boolean[],
      submitting: false,
    };
  },
  computed: {
    allAccepted(): boolean {
      return this.accepted.every(Boolean);
    },
  },
  methods: {
    async submit() {
      this.submitting = true;
      try {
        // No body: the server stamps terms_accepted_at and is the source of
        // truth for what was accepted.
        await api.post('/api/billing/accept-terms/');
        this.$emit('accepted');
      } catch {
        this.$q.dialog({
          title: this.$t('error.error'),
          message: this.$t('signup.termsAcceptError'),
        });
      } finally {
        this.submitting = false;
      }
    },
  },
});
</script>
