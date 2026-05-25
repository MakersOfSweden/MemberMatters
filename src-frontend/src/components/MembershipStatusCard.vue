<template>
  <q-card class="membership-status-card">
    <q-card-section class="q-pb-sm">
      <div class="row items-center">
        <q-icon :name="icons.membership" size="sm" class="q-mr-sm" />
        <h6 class="q-ma-none">{{ $t('membershipStatusCard.title') }}</h6>
      </div>
    </q-card-section>

    <div
      :class="`bg-${stateBadgeColor} text-white text-center text-subtitle1 text-weight-medium q-py-sm q-mb-sm`"
    >
      {{ $t(`membershipStatusCard.stateBanner.${bannerKey}`) }}
    </div>

    <q-card-section class="q-pt-sm">
      <!-- account blocked by an admin -->
      <template v-if="isLocked">
        <div class="row items-center no-wrap">
          <q-icon
            :name="icons.lock"
            color="warning"
            size="sm"
            class="q-mr-sm"
          />
          <div class="col">
            {{ $t('membershipStatusCard.lockedDescription') }}
          </div>
        </div>
      </template>

      <!-- signup checklist: new members, or returning members awaiting invoice payment -->
      <template v-else-if="isSignupInProgress">
        <template v-if="requiredSteps === null">
          <q-spinner color="primary" size="sm" />
        </template>
        <template v-else-if="hasAnyStep">
          <q-list dense>
            <q-item v-for="step in checklistSteps" :key="step.name" dense>
              <q-item-section avatar>
                <q-icon :name="iconForStep(step)" :color="colorForStep(step)" />
              </q-item-section>
              <q-item-section :class="textClassForStep(step)">
                <q-item-label>{{ step.label }}</q-item-label>
                <q-item-label caption>{{ captionForStep(step) }}</q-item-label>
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
          v-if="profile.financial.subscriptionState !== 'cancelling'"
          class="q-mb-sm text-caption"
        >
          {{ $t('membershipStatusCard.renewalDate') }}:
          <template v-if="formattedRenewalDate">
            {{ formattedRenewalDate }} ({{
              $t('membershipStatusCard.inDays', { days: daysUntilRenewal })
            }})
          </template>
          <template v-else>{{ $t('membershipStatusCard.unknown') }}</template>
        </div>
        <q-banner
          v-if="
            features.enableMembershipPayments &&
            profile.financial.subscriptionState === 'cancelling'
          "
          inline-actions
          rounded
          class="bg-orange text-white q-mt-sm"
        >
          <template v-slot:avatar>
            <q-icon :name="icons.warning" />
          </template>
          {{ $t('membershipStatusCard.cancellingWarning') }}
          <span v-if="formattedCancelAt">
            {{
              $t('membershipStatusCard.membershipExpires', {
                date: formattedCancelAt,
              })
            }}
            ({{
              $t('membershipStatusCard.inDays', { days: daysUntilExpiration })
            }})
          </span>
        </q-banner>
      </template>

      <!-- inactive (former member, no pending invoice) -->
      <template v-else-if="isInactiveMember">
        <p class="q-mb-none">
          {{ $t('membershipStatusCard.inactiveDescription') }}
        </p>
      </template>

      <!-- accountonly -->
      <template v-else-if="signupStage === 'account_only'">
        <p class="q-mb-xs">{{ $t('membershipStatusCard.accountOnlyTitle') }}</p>
        <p class="q-mb-none text-grey-7 text-caption">
          {{ $t('membershipStatusCard.accountOnlyDescription') }}
        </p>
      </template>
    </q-card-section>

    <q-card-section class="status-card-actions q-pt-none">
      <div class="row">
        <q-btn
          flat
          :label="$t('membershipStatusCard.viewMembership')"
          @click="$router.push({ name: 'membershipPlan' })"
        />
        <q-space />
        <q-btn
          v-if="actionLabel"
          color="accent"
          :label="actionLabel"
          @click="$router.push({ name: 'membershipPlan' })"
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
    // Order here = visual order in the checklist. Adding a step is one entry.
    // `complete` is null until requiredSteps loads from /api/billing/can-signup/.
    checklistSteps() {
      const steps = [];
      if (this.features.enableMembershipPayments) {
        steps.push({
          name: 'payment',
          complete: this.paymentComplete,
          pending: this.paymentPending,
          label: this.$t('membershipStatusCard.payment'),
          captionComplete: this.$t('membershipStatusCard.paymentComplete'),
          captionRequired: this.$t('membershipStatusCard.paymentRequired'),
          captionPending: this.$t('membershipStatusCard.paymentPending'),
        });
      }
      if ((this.features.signup?.termsAcceptanceCards || []).length > 0) {
        steps.push({
          name: 'terms',
          complete: this.termsComplete,
          label: this.$t('signup.termsAcceptance'),
          captionComplete: this.$t('membershipStatusCard.termsComplete'),
          captionRequired: this.$t('membershipStatusCard.termsRequired'),
        });
      }
      if (this.features.signup?.enableInduction) {
        steps.push({
          name: 'induction',
          complete: this.inductionComplete,
          label: this.$t('signup.induction'),
          captionComplete: this.$t('membershipStatusCard.inductionComplete'),
          captionRequired: this.$t('membershipStatusCard.inductionRequired'),
        });
      }
      if (this.features.signup?.requireAccessCard) {
        steps.push({
          name: 'accessCard',
          complete: this.accessCardComplete,
          label: this.$t('signup.accessCard'),
          captionComplete: this.$t('membershipStatusCard.accessCardComplete'),
          captionRequired: this.$t('membershipStatusCard.accessCardRequired'),
        });
      }
      return steps;
    },
    hasAnyStep() {
      return this.checklistSteps.length > 0;
    },
    signupStage() {
      return this.profile?.signupStage;
    },
    isLocked() {
      return this.signupStage === 'locked';
    },
    paymentPending() {
      return this.profile.financial.subscriptionState === 'pending';
    },
    isSignupInProgress() {
      return ['needs_plan', 'needs_requirements', 'awaiting_payment'].includes(
        this.signupStage
      );
    },
    isActiveMember() {
      return this.signupStage === 'managed';
    },
    isInactiveMember() {
      return this.signupStage === 'lapsed';
    },
    bannerKey() {
      return this.isSignupInProgress ? 'noob' : this.profile.memberStatus;
    },
    nextStep() {
      // Pending (e.g. awaiting invoice payment) is not actionable from here.
      const next = this.checklistSteps.find((s) => !s.complete && !s.pending);
      return next?.name || null;
    },
    paymentComplete() {
      return this.profile.financial.subscriptionState === 'active';
    },
    termsComplete() {
      return (
        this.requiredSteps !== null &&
        !this.requiredSteps.includes('termsAcceptance')
      );
    },
    inductionComplete() {
      return (
        this.requiredSteps !== null && !this.requiredSteps.includes('induction')
      );
    },
    accessCardComplete() {
      return (
        this.requiredSteps !== null &&
        !this.requiredSteps.includes('accessCard')
      );
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
    actionLabel() {
      if (this.isSignupInProgress) {
        return this.$t('membershipStatusCard.completeSetup');
      }
      if (this.signupStage === 'account_only') {
        return this.$t('membershipStatusCard.becomeMember');
      }
      if (this.isInactiveMember && this.features.enableMembershipPayments) {
        return this.$t('membershipStatusCard.activateMembership');
      }
      return null;
    },
  },
  methods: {
    iconForStep(step) {
      if (step.complete) return this.icons.success;
      if (step.pending) return this.icons.warning;
      return this.icons.fail;
    },
    colorForStep(step) {
      if (step.complete) return 'positive';
      if (step.pending) return 'warning';
      if (this.nextStep === step.name) return 'negative';
      return 'grey-5';
    },
    textClassForStep(step) {
      if (step.complete) return 'text-strike text-grey-6';
      if (this.nextStep === step.name) return 'text-weight-bold';
      return 'text-grey-6';
    },
    captionForStep(step) {
      if (step.complete) return step.captionComplete;
      if (step.pending) return step.captionPending;
      return step.captionRequired;
    },
  },
};
</script>

<style scoped>
.membership-status-card {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.membership-status-card > .status-card-actions {
  margin-top: auto;
}
</style>
