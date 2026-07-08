<template>
  <div
    :class="`bg-${stateBadgeColor} text-white text-center text-subtitle1 text-weight-medium q-py-sm`"
  >
    {{ $t(`membershipStatusCard.stateBanner.${bannerKey}`) }}
  </div>
</template>

<script>
import { mapGetters } from 'vuex';

export default {
  name: 'MembershipStateBanner',
  computed: {
    ...mapGetters('profile', ['profile']),
    signupStage() {
      return this.profile?.signupStage;
    },
    isSignupInProgress() {
      return ['needs_plan', 'needs_requirements', 'awaiting_payment'].includes(
        this.signupStage
      );
    },
    bannerKey() {
      return this.isSignupInProgress ? 'noob' : this.profile.memberStatus;
    },
    stateBadgeColor() {
      const colors = {
        noob: 'orange',
        active: 'positive',
        inactive: 'yellow-8',
        accountonly: 'grey-7',
      };
      return colors[this.bannerKey] || 'grey-7';
    },
  },
};
</script>
