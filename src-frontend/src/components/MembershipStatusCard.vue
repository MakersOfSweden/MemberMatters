<template>
  <q-card class="membership-status-card">
    <q-card-section>
      <div class="row items-center q-mb-sm">
        <q-icon :name="icons.membership" size="sm" class="q-mr-sm" />
        <h6 class="q-ma-none">Membership Status</h6>
        <q-space />
        <q-chip
          :color="stateBadgeColor"
          text-color="white"
          :label="stateBadgeLabel"
          dense
        />
      </div>

      <!-- noob: signup checklist -->
      <template v-if="profile.memberStatus === 'noob'">
        <template v-if="hasAnyStep">
          <q-list dense>
            <q-item v-if="showPaymentStep" dense>
              <q-item-section avatar>
                <q-icon
                  :name="paymentComplete ? icons.success : icons.fail"
                  :color="paymentComplete ? 'positive' : 'negative'"
                />
              </q-item-section>
              <q-item-section>
                <q-item-label>Payment</q-item-label>
                <q-item-label caption>{{
                  paymentComplete
                    ? 'Subscription active'
                    : 'Membership payment required'
                }}</q-item-label>
              </q-item-section>
            </q-item>

            <q-item v-if="showInductionStep" dense>
              <q-item-section avatar>
                <q-icon
                  :name="inductionComplete ? icons.success : icons.fail"
                  :color="inductionComplete ? 'positive' : 'negative'"
                />
              </q-item-section>
              <q-item-section>
                <q-item-label>Induction</q-item-label>
                <q-item-label caption>{{
                  inductionComplete
                    ? 'Induction completed'
                    : 'Online induction required'
                }}</q-item-label>
              </q-item-section>
            </q-item>

            <q-item v-if="showAccessCardStep" dense>
              <q-item-section avatar>
                <q-icon
                  :name="accessCardComplete ? icons.success : icons.fail"
                  :color="accessCardComplete ? 'positive' : 'negative'"
                />
              </q-item-section>
              <q-item-section>
                <q-item-label>Access Card</q-item-label>
                <q-item-label caption>{{
                  accessCardComplete
                    ? 'Access card registered'
                    : 'Access card registration required'
                }}</q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </template>
        <p v-else class="q-mb-none text-grey-7">Setup in progress.</p>
      </template>

      <!-- active -->
      <template v-else-if="profile.memberStatus === 'active'">
        <p class="q-mb-sm">You are an active member.</p>
        <q-chip
          :color="
            profile.subscriptionStatus === 'active' ? 'positive' : 'orange'
          "
          text-color="white"
          dense
          :label="subscriptionLabel"
        />
        <q-banner
          v-if="profile.subscriptionStatus === 'cancelling'"
          inline-actions
          rounded
          class="bg-orange text-white q-mt-sm"
        >
          <template v-slot:avatar>
            <q-icon :name="icons.warning" />
          </template>
          Your subscription is cancelling. Access will end at the next renewal
          date.
        </q-banner>
      </template>

      <!-- inactive -->
      <template v-else-if="profile.memberStatus === 'inactive'">
        <p class="q-mb-none">Your membership is inactive.</p>
      </template>

      <!-- accountonly -->
      <template v-else-if="profile.memberStatus === 'accountonly'">
        <p class="q-mb-xs">Account only — not an active member.</p>
        <p class="q-mb-none text-grey-7 text-caption">
          You have an account but have not been granted full membership access.
        </p>
      </template>
    </q-card-section>

    <q-card-actions>
      <q-btn
        flat
        color="primary"
        :label="ctaLabel"
        @click="$router.push({ name: ctaRoute })"
      />
    </q-card-actions>
  </q-card>
</template>

<script>
import { mapGetters } from 'vuex';
import icons from '@icons';

export default {
  name: 'MembershipStatusCard',
  data() {
    return {
      requiredSteps: [],
    };
  },
  mounted() {
    if (this.profile.memberStatus === 'noob') {
      this.$axios
        .get('/api/billing/can-signup/')
        .then((response) => {
          this.requiredSteps = response.data.requiredSteps || [];
        })
        .catch(() => {
          this.requiredSteps = [];
        });
    }
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
    paymentComplete() {
      return this.profile.subscriptionStatus === 'active';
    },
    inductionComplete() {
      return !this.requiredSteps.includes('induction');
    },
    accessCardComplete() {
      return !this.requiredSteps.includes('accessCard');
    },
    stateBadgeColor() {
      const colors = {
        noob: 'orange',
        active: 'positive',
        inactive: 'yellow-8',
        accountonly: 'grey-7',
      };
      return colors[this.profile.memberStatus] || 'grey-7';
    },
    stateBadgeLabel() {
      const labels = {
        noob: 'Needs Setup',
        active: 'Active',
        inactive: 'Inactive',
        accountonly: 'Account Only',
      };
      return labels[this.profile.memberStatus] || this.profile.memberStatus;
    },
    subscriptionLabel() {
      const labels = {
        active: 'Subscription active',
        cancelling: 'Subscription cancelling',
        inactive: 'No active subscription',
      };
      return labels[this.profile.subscriptionStatus] || this.profile.subscriptionStatus;
    },
    ctaLabel() {
      if (this.profile.memberStatus === 'noob' || this.profile.memberStatus === 'active') {
        return 'View Membership';
      }
      return 'View Account';
    },
    ctaRoute() {
      if (this.profile.memberStatus === 'noob' || this.profile.memberStatus === 'active') {
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
