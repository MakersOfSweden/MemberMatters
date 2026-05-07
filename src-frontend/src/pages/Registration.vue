<template>
  <q-page class="column flex items-center justify-center q-pt-xl">
    <template>
      <q-img
        contain
        :src="images.siteLogo"
        class="header-image-mobile q-my-lg"
      />
    </template>

    <q-card
      v-if="features.enableRegistration === false"
      class="q-pa-md registration-closed-card"
    >
      <q-banner class="bg-info text-white">
        {{
          features.registrationDisabledMessage ||
          $t('error.registrationClosed')
        }}
      </q-banner>
      <div class="row justify-end q-mt-md">
        <q-btn
          :label="$t('loginCard.login')"
          color="primary"
          :to="{ name: 'login' }"
        />
      </div>
    </q-card>

    <registration-card v-else />
  </q-page>
</template>

<script lang="ts">
import RegistrationCard from '@components/Account/RegistrationCard.vue';
import { mapGetters } from 'vuex';

export default {
  name: 'RegistrationPage',
  components: {
    RegistrationCard,
  },
  computed: {
    ...mapGetters('config', ['images', 'features']),
  },
};
</script>

<style scoped>
.header-image-mobile {
  max-height: 50px;
}
</style>
