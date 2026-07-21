<template>
  <q-page class="q-pa-md">
    <div class="text-h5 q-mb-md">Email</div>
    <p class="text-grey-7 q-mb-md">
      Send a test email to confirm your email configuration is working.
    </p>

    <!-- Config health check -->
    <div class="text-h6 q-mb-sm">Configuration</div>
    <q-banner
      v-if="!configLoading && hasUnsetConfig"
      class="bg-warning text-dark q-mb-md"
    >
      Some email settings aren't configured — sending may not work correctly.
    </q-banner>
    <q-card flat bordered class="q-mb-lg">
      <q-inner-loading :showing="configLoading">
        <q-spinner size="2em" />
      </q-inner-loading>
      <q-list separator>
        <q-item v-for="field in configFields" :key="field.key">
          <q-item-section avatar>
            <q-icon
              :name="field.isSet ? icons.success : icons.warning"
              :color="field.isSet ? 'positive' : 'negative'"
            />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ field.label }}</q-item-label>
            <q-item-label v-if="!field.isSet" caption class="text-negative">
              Not configured
            </q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-card>

    <!-- Send test email -->
    <div class="text-h6 q-mb-sm">Send a test email</div>
    <q-form @submit.prevent="sendTestEmail">
      <q-input
        v-model="recipient"
        type="email"
        outlined
        label="Recipient email"
        :rules="[(val) => !!val || 'Recipient email is required']"
        class="q-mb-md"
        style="max-width: 500px"
      />
      <q-btn
        type="submit"
        color="primary"
        :icon="icons.email"
        label="Send test email"
        :loading="submitting"
        :disable="!recipient"
      />
    </q-form>
  </q-page>
</template>

<script>
import icons from '@icons';
import { mapGetters } from 'vuex';

export default {
  name: 'EmailAdmin',
  data() {
    return {
      configFields: [],
      configLoading: false,
      recipient: '',
      submitting: false,
    };
  },
  computed: {
    ...mapGetters('profile', ['profile']),
    icons() {
      return icons;
    },
    hasUnsetConfig() {
      return this.configFields.some((field) => !field.isSet);
    },
  },
  mounted() {
    this.recipient = this.profile?.email || '';
    this.fetchConfigStatus();
  },
  methods: {
    fetchConfigStatus() {
      this.configLoading = true;
      this.$axios
        .get('/api/admin/email/config-status/')
        .then((response) => {
          this.configFields = response.data.fields;
        })
        .catch((e) => {
          console.log(e);
          this.$q.notify({
            type: 'negative',
            message: 'Failed to load email configuration status.',
          });
        })
        .finally(() => {
          this.configLoading = false;
        });
    },
    sendTestEmail() {
      if (!this.recipient) return;
      this.submitting = true;
      this.$axios
        .post('/api/admin/email/send-test/', { email: this.recipient })
        .then(() => {
          this.$q.notify({
            type: 'positive',
            message: 'Test email sent.',
          });
        })
        .catch((e) => {
          console.log(e);
          this.$q.notify({
            type: 'negative',
            message:
              e.response?.data?.message || 'Failed to send test email.',
          });
        })
        .finally(() => {
          this.submitting = false;
        });
    },
  },
};
</script>
