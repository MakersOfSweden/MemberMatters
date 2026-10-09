<template>
  <div class="text-center">
    <p
      @click="confirmSkipSignup"
      style="text-decoration: underline; cursor: pointer"
    >
      {{ $t('tiers.skipSignup') }}
    </p>
  </div>
</template>

<script>
import { mapActions } from 'vuex';
import { defineComponent } from 'vue';

export default defineComponent({
  name: 'SkipSignupLink',
  methods: {
    ...mapActions('profile', ['getProfile']),
    confirmSkipSignup() {
      this.$q
        .dialog({
          title: this.$t('tiers.skipSignupWarningTitle'),
          message: this.$t('tiers.skipSignupWarningMessage'),
          html: true,
          ok: {
            label: this.$t('tiers.skipSignupWarningConfirm'),
            color: 'negative',
            flat: true,
          },
          cancel: {
            label: this.$t('button.cancel'),
            color: 'primary',
          },
          persistent: true,
        })
        .onOk(() => {
          this.skipSignup();
        });
    },
    skipSignup() {
      this.$axios
        .post('/api/billing/skip-signup/')
        .then(async (response) => {
          if (response.data.success) {
            await this.getProfile();
            this.$router.push({ name: 'dashboard' });
          } else {
            this.$q.dialog({
              title: this.$t('error.requestFailed'),
              message: this.$t('error.contactUs'),
            });
          }
        })
        .catch(() => {
          this.$q.dialog({
            title: this.$t('error.requestFailed'),
            message: this.$t('error.contactUs'),
          });
        });
    },
  },
});
</script>
