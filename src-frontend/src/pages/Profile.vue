<template>
  <q-page class="column flex justify-start items-center">
    <div class="column flex content-start justify-center">
      <q-banner
        v-if="
          profile.memberStatus !== 'active' &&
          profile.memberStatus !== 'accountonly'
        "
        inline-actions
        rounded
        class="bg-orange text-white q-ma-md"
      >
        <template v-slot:avatar>
          <q-icon :name="icons.warning" />
        </template>
        {{ $t('access.inactive') }}
      </q-banner>

      <q-banner
        v-if="profile.memberStatus === 'Account Only'"
        inline-actions
        rounded
        class="bg-blue text-white q-ma-md"
      >
        <template v-slot:avatar>
          <q-icon :name="icons.info" />
        </template>
        {{ $t('paymentPlans.profileAccountOnlyWarning') }}
      </q-banner>
    </div>

    <profile-form class="q-mb-sm" />

    <q-btn
      color="primary"
      :label="$t('changePasswordCard.pageTitle')"
      class="profile-action-btn q-mb-sm"
      @click="changePassword = true"
    />

    <q-btn
      color="toolbar"
      :icon="icons.digitalId"
      :label="$t('digitalId.title')"
      class="profile-action-btn"
      @click="digitalId = true"
    />

    <p class="text-body2 text-grey-8 q-mt-xl">
      {{ $t('form.memberNumber') }}:<span class="q-ml-sm text-weight-bold">{{
        profile.id
      }}</span>
    </p>

    <q-dialog v-model="digitalId">
      <digital-id-card />
    </q-dialog>

    <q-dialog v-model="changePassword">
      <change-password-card />
    </q-dialog>
  </q-page>
</template>

<script>
import ProfileForm from '@components/ProfileForm.vue';
import icons from '../icons';
import DigitalIdCard from '@components/DigitalIdCard.vue';
import ChangePasswordCard from '@components/ChangePasswordCard.vue';
import { mapGetters } from 'vuex';

export default {
  name: 'ProfilePage',
  components: { ChangePasswordCard, DigitalIdCard, ProfileForm },
  data() {
    return {
      text: '',
      digitalId: false,
      changePassword: false,
    };
  },
  computed: {
    ...mapGetters('profile', ['loggedIn', 'profile']),
    icons() {
      return icons;
    },
  },
};
</script>

<style lang="sass">
.profile-action-btn
  max-width: $maxWidthMedium
  width: 100%
</style>
