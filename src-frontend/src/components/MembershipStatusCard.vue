<template>
  <q-card class="membership-status-card">
    <q-card-section class="q-pb-sm">
      <div class="row items-center">
        <q-icon :name="icons.membership" size="sm" class="q-mr-sm" />
        <h6 class="q-ma-none">{{ $t('membershipStatusCard.title') }}</h6>
      </div>
    </q-card-section>

    <div :class="`bg-${stateBadgeColor} text-white text-center text-subtitle1 text-weight-medium q-py-sm q-mb-sm`">
      {{ $t(`membershipStatusCard.stateBanner.${bannerKey}`) }}
    </div>

    <q-card-section class="q-pt-sm">
      <!-- signup checklist: new members, or returning members awaiting invoice payment -->
      <template v-if="isSignupInProgress">
        <template v-if="requiredSteps === null">
          <q-spinner color="primary" size="sm" />
        </template>
        <template v-else-if="hasAnyStep">
          <q-list dense>
            <q-item v-if="showPaymentStep" dense>
              <q-item-section avatar>
                <q-icon
                  :name="paymentComplete ? icons.success : profile.financial.subscriptionState === 'pending' ? icons.warning : icons.fail"
                  :color="paymentComplete ? 'positive' : profile.financial.subscriptionState === 'pending' ? 'warning' : nextStep === 'payment' ? 'negative' : 'grey-5'"
                />
              </q-item-section>
              <q-item-section :class="paymentComplete ? 'text-strike text-grey-6' : nextStep === 'payment' ? 'text-weight-bold' : 'text-grey-6'">
                <q-item-label>{{ $t('membershipStatusCard.payment') }}</q-item-label>
                <q-item-label caption>{{
                  paymentComplete
                    ? $t('membershipStatusCard.paymentComplete')
                    : profile.financial.subscriptionState === 'pending'
                    ? $t('membershipStatusCard.paymentPending')
                    : $t('membershipStatusCard.paymentRequired')
                }}</q-item-label>
              </q-item-section>
            </q-item>

            <q-item v-if="showInductionStep" dense>
              <q-item-section avatar>
                <q-icon
                  :name="inductionComplete ? icons.success : icons.fail"
                  :color="inductionComplete ? 'positive' : nextStep === 'induction' ? 'negative' : 'grey-5'"
                />
              </q-item-section>
              <q-item-section :class="inductionComplete ? 'text-strike text-grey-6' : nextStep === 'induction' ? 'text-weight-bold' : 'text-grey-6'">
                <q-item-label>{{ $t('signup.induction') }}</q-item-label>
                <q-item-label caption>{{
                  inductionComplete
                    ? $t('membershipStatusCard.inductionComplete')
                    : $t('membershipStatusCard.inductionRequired')
                }}</q-item-label>
              </q-item-section>
            </q-item>

            <q-item v-if="showAccessCardStep" dense>
              <q-item-section avatar>
                <q-icon
                  :name="accessCardComplete ? icons.success : icons.fail"
                  :color="accessCardComplete ? 'positive' : nextStep === 'accessCard' ? 'negative' : 'grey-5'"
                />
              </q-item-section>
              <q-item-section :class="accessCardComplete ? 'text-strike text-grey-6' : nextStep === 'accessCard' ? 'text-weight-bold' : 'text-grey-6'">
                <q-item-label>{{ $t('signup.accessCard') }}</q-item-label>
                <q-item-label caption>{{
                  accessCardComplete
                    ? $t('membershipStatusCard.accessCardComplete')
                    : $t('membershipStatusCard.accessCardRequired')
                }}</q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </template>
        <p v-else class="q-mb-none text-grey-7">
          {{ $t('membershipStatusCard.setupInProgress') }}
        </p>
      </template>

      <!-- active -->
      <template v-else-if="isActiveMember">
        <div
          v-if="formattedRenewalDate && profile.financial.subscriptionState !== 'cancelling'"
          class="q-mb-sm text-caption"
        >
          {{ $t('membershipStatusCard.renewalDate') }}: {{ formattedRenewalDate }} ({{ $t('membershipStatusCard.inDays', { days: daysUntilRenewal }) }})
        </div>
        <q-chip
          v-if="features.enableMembershipPayments && profile.financial.subscriptionState"
          :color="
            profile.financial.subscriptionState === 'active'
              ? 'positive'
              : profile.financial.subscriptionState === 'cancelling'
              ? 'orange'
              : 'grey-7'
          "
          text-color="white"
          dense
          :label="subscriptionLabel"
        />
        <q-banner
          v-if="features.enableMembershipPayments && profile.financial.subscriptionState === 'cancelling'"
          inline-actions
          rounded
          class="bg-orange text-white q-mt-sm"
        >
          <template v-slot:avatar>
            <q-icon :name="icons.warning" />
          </template>
          {{ $t('membershipStatusCard.cancellingWarning') }}
          <span v-if="formattedCancelAt">
            {{ $t('membershipStatusCard.membershipExpires', { date: formattedCancelAt }) }}
            ({{ $t('membershipStatusCard.inDays', { days: daysUntilExpiration }) }})
          </span>
        </q-banner>
      </template>

      <!-- inactive (former member, no pending invoice) -->
      <template v-else-if="isInactiveMember">
        <p class="q-mb-none">{{ $t('membershipStatusCard.inactiveDescription') }}</p>
      </template>

      <!-- accountonly -->
      <template v-else-if="profile.memberStatus === 'accountonly'">
        <p class="q-mb-xs">{{ $t('membershipStatusCard.accountOnlyTitle') }}</p>
        <p class="q-mb-none text-grey-7 text-caption">
          {{ $t('membershipStatusCard.accountOnlyDescription') }}
        </p>
      </template>
    </q-card-section>

    <q-card-section class="q-pt-none">
      <div class="row">
        <q-space />
        <q-btn
          v-if="profile.memberStatus === 'accountonly'"
          color="positive"
          :label="$t('membershipStatusCard.becomeMember')"
          class="q-mr-sm"
          @click="$router.push({ name: 'membershipPlan' })"
        />
        <q-btn
          color="primary-btn"
          :label="ctaLabel"
          @click="$router.push({ name: ctaRoute })"
        />
      </div>
    </q-card-section>
  </q-card>
</template>

<script>
import { mapGetters } from 'vuex';
import icons from '@icons';
import dayjs from 'dayjs';

export default {
  name: 'MembershipStatusCard',
  data() {
    return {
      requiredSteps: null,
      currentPeriodEnd: null,
      cancelAt: null,
    };
  },
  watch: {
    isSignupInProgress: {
      immediate: true,
      handler(inProgress) {
        if (inProgress) {
          this.$axios
            .get('/api/billing/can-signup/')
            .then((response) => {
              this.requiredSteps = response.data.requiredSteps || [];
            })
            .catch((e) => {
              console.log(e);
            });
        }
      },
    },
    isActiveMember: {
      immediate: true,
      handler(active) {
        if (active && this.features.enableMembershipPayments) {
          this.$axios
            .get('/api/billing/myplan/')
            .then((response) => {
              if (response.data.success) {
                this.currentPeriodEnd =
                  response.data.subscription.currentPeriodEnd;
                this.cancelAt = response.data.subscription.cancelAt;
              }
            })
            .catch((e) => {
              console.log(e);
            });
        }
      },
    },
  },
  computed: {
    ...mapGetters('profile', ['profile']),
    ...mapGetters('config', ['features']),
    icons() {
      return icons;
    },
    showPaymentStep() {
      return this.features.enableMembershipPayments;
    },
    showInductionStep() {
      return this.features.signup?.enableInduction;
    },
    showAccessCardStep() {
      return this.features.signup?.requireAccessCard;
    },
    hasAnyStep() {
      return this.showPaymentStep || this.showInductionStep || this.showAccessCardStep;
    },
    paymentPending() {
      return this.profile.financial.subscriptionState === 'pending';
    },
    // A returning member (state="inactive") with a pending invoice subscription
    // is mid-signup — treat them like a new "noob" member until payment arrives.
    isSignupInProgress() {
      return (
        this.profile.memberStatus === 'noob' ||
        (this.profile.memberStatus === 'inactive' && this.paymentPending)
      );
    },
    isActiveMember() {
      return this.profile.memberStatus === 'active';
    },
    isInactiveMember() {
      return this.profile.memberStatus === 'inactive' && !this.paymentPending;
    },
    bannerKey() {
      return this.isSignupInProgress ? 'noob' : this.profile.memberStatus;
    },
    nextStep() {
      // When invoice is pending, payment is "in progress" (awaiting invoice) — skip to next actionable step
      if (this.showPaymentStep && !this.paymentComplete && !this.paymentPending) return 'payment';
      if (this.showInductionStep && !this.inductionComplete) return 'induction';
      if (this.showAccessCardStep && !this.accessCardComplete) return 'accessCard';
      return null;
    },
    paymentComplete() {
      return this.profile.financial.subscriptionState === 'active';
    },
    inductionComplete() {
      return this.requiredSteps !== null && !this.requiredSteps.includes('induction');
    },
    accessCardComplete() {
      return this.requiredSteps !== null && !this.requiredSteps.includes('accessCard');
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
    subscriptionLabel() {
      const key = `membershipStatusCard.subscriptionChip.${this.profile.financial.subscriptionState}`;
      return this.$te(key) ? this.$t(key) : this.profile.financial.subscriptionState;
    },
    formattedRenewalDate() {
      if (!this.currentPeriodEnd) return null;
      return new Date(this.currentPeriodEnd * 1000).toLocaleDateString();
    },
    daysUntilRenewal() {
      if (!this.currentPeriodEnd) return null;
      return dayjs(this.currentPeriodEnd * 1000).diff(dayjs(), 'day');
    },
    formattedCancelAt() {
      if (!this.cancelAt) return null;
      return new Date(this.cancelAt * 1000).toLocaleDateString();
    },
    daysUntilExpiration() {
      if (!this.cancelAt) return null;
      return dayjs(this.cancelAt * 1000).diff(dayjs(), 'day');
    },
    ctaLabel() {
      if (this.isSignupInProgress) {
        return this.$t('membershipStatusCard.completeSetup');
      }
      if (this.isActiveMember) {
        return this.$t('membershipStatusCard.viewMembership');
      }
      if (this.isInactiveMember && this.features.enableMembershipPayments) {
        return this.$t('membershipStatusCard.activateMembership');
      }
      return this.$t('membershipStatusCard.viewAccount');
    },
    ctaRoute() {
      if (
        this.isSignupInProgress ||
        this.isActiveMember ||
        (this.isInactiveMember && this.features.enableMembershipPayments)
      ) {
        return 'membershipPlan';
      }
      return 'profile';
    },
  },
};
</script>

<style scoped>
.membership-status-card {
  height: 100%;
}
</style>
