<template>
  <q-page class="q-pa-md">
    <div class="text-h5 q-mb-md">Signup Preview</div>
    <p class="text-grey-7">
      Quick preview of content members see during signup. Reflects the current
      configuration.
    </p>

    <div v-if="loading" class="q-pa-lg text-center">
      <q-spinner size="3em" />
    </div>

    <template v-else>
      <!-- Welcome email -->
      <div class="text-h6 q-mt-lg q-mb-sm">Welcome email</div>
      <q-card flat bordered>
        <iframe
          :srcdoc="welcomeEmailHtml"
          title="Welcome email preview"
          style="width: 100%; height: 700px; border: 0"
        />
      </q-card>

      <!-- Terms & conditions cards -->
      <div class="text-h6 q-mt-lg q-mb-sm">Terms &amp; conditions cards</div>
      <p v-if="!termsAcceptanceCards.length" class="text-grey-7">
        No terms &amp; conditions cards are configured.
      </p>
      <div v-else class="row">
        <terms-acceptance-card
          v-for="(card, i) in termsAcceptanceCards"
          :key="i"
          :icon="card.icon"
          :title="card.title"
          :body-html="card.body_html"
          :checkbox-text="card.checkbox_text"
          :model-value="false"
          class="col-12 col-md-6"
        />
      </div>
    </template>
  </q-page>
</template>

<script lang="ts">
import { defineComponent } from 'vue';
import { api } from 'boot/axios';
import TermsAcceptanceCard from '@components/Billing/TermsAcceptanceCard.vue';

export default defineComponent({
  name: 'SignupPreview',
  components: { TermsAcceptanceCard },
  data() {
    return {
      loading: true,
      welcomeEmailHtml: '',
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      termsAcceptanceCards: [] as any[],
    };
  },
  mounted() {
    api
      .get('/api/admin/signup-preview/')
      .then((result) => {
        this.welcomeEmailHtml = result.data.welcomeEmailHtml;
        this.termsAcceptanceCards = result.data.termsAcceptanceCards;
      })
      .finally(() => {
        this.loading = false;
      });
  },
});
</script>
