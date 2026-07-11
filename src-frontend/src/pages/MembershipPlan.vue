<template>
  <q-page class="column flex justify-start items-center">
    <template v-if="!profileLoaded">
      <q-spinner size="4em" />
    </template>

    <template v-else-if="signupStage === 'locked'">
      <div class="q-pa-lg text-center" style="max-width: 480px">
        <div class="text-h6 q-mb-sm">
          {{ $t('paymentPlans.lockedTitle') }}
        </div>
        <p>{{ $t('paymentPlans.lockedMessage') }}</p>
      </div>
    </template>

    <template
      v-else-if="['needs_plan', 'account_only', 'lapsed'].includes(signupStage)"
    >
      <q-banner
        v-if="features.enableNewSubscriptions === false"
        class="bg-info text-white q-pa-md"
      >
        {{ $t('billing.newSubscriptionsDisabled') }}
      </q-banner>
      <select-tier v-else />
    </template>

    <template v-else-if="signupStage === 'needs_requirements'">
      <div class="text-h6 q-pb-md">
        {{ $t('signup.requiredSteps') }}
      </div>

      <signup-required-steps />
    </template>

    <template v-else>
      <membership-state-banner class="full-width q-mb-md" />

      <selected-tier :plan="membershipPlan" :tier="currentTier" />

      <q-banner
        v-if="subscriptionStatus === 'pending'"
        class="bg-orange text-white q-mb-md"
        inline-actions
        rounded
      >
        <template v-slot:avatar>
          <q-icon name="mdi-alert" />
        </template>
        {{ $t('billing.awaitingInvoicePayment') }}
        <template v-slot:action>
          <q-spinner v-if="loadingSubscription" color="white" size="sm" />
          <q-btn
            v-else-if="subscriptionInfo?.invoiceUrl"
            flat
            no-caps
            text-color="white"
            :label="$tc('billing.viewInvoice')"
            :href="subscriptionInfo.invoiceUrl"
            target="_blank"
            icon="mdi-open-in-new"
          />
        </template>
      </q-banner>

      <div v-if="cancelSuccess" class="row q-mb-md">
        <q-banner class="bg-success text-white">
          <div class="text-h5">{{ $tc('actionSuccess') }}</div>
          <p>{{ $tc('paymentPlans.cancelSuccessDescription') }}</p>
        </q-banner>
      </div>

      <div v-if="subscriptionStatus === 'cancelling'" class="row q-mb-md">
        <q-banner class="bg-error text-white">
          <div class="text-h5">{{ $tc('paymentPlans.cancelling') }}</div>
          <p>
            {{
              $t('paymentPlans.cancellingDescription', { date: cancelAtDate })
            }}
          </p>
        </q-banner>
      </div>

      <div
        v-if="
          subscriptionStatus !== 'cancelling' &&
          (loadingSubscription ||
            subscriptionUnavailable ||
            subscriptionInfo?.currentPeriodEnd)
        "
        class="q-mb-md"
      >
        <div class="text-h6 q-py-md">
          {{ $t('paymentPlans.subscriptionInfo') }}
        </div>

        <div v-if="loadingSubscription" class="q-pa-md">
          <q-spinner color="primary" size="md" />
        </div>

        <q-banner
          v-else-if="subscriptionUnavailable"
          class="bg-warning text-white rounded-borders"
        >
          {{ $t('paymentPlans.subscriptionUnavailable') }}
        </q-banner>

        <q-card v-else>
          <q-list bordered separator>
            <q-item>
              <q-item-section>
                <q-item-label>{{ paymentMethodLabel }}</q-item-label>
                <q-item-label caption>{{
                  $tc('paymentPlans.paymentMethod')
                }}</q-item-label>
              </q-item-section>
            </q-item>
            <q-item>
              <q-item-section>
                <q-item-label>{{ currentPeriodEnd }}</q-item-label>
                <q-item-label caption>{{
                  $tc('paymentPlans.renewalDate')
                }}</q-item-label>
              </q-item-section>
            </q-item>
            <q-item>
              <q-item-section>
                <q-item-label>{{ signupDate }}</q-item-label>
                <q-item-label caption>{{
                  $tc('paymentPlans.signupDate')
                }}</q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </q-card>
      </div>

      <q-btn
        v-if="
          subscriptionStatus === 'active' || subscriptionStatus === 'pending'
        "
        :disable="disableButton"
        :loading="loadingButton"
        @click="cancelPlan"
        color="error"
        :label="$tc('paymentPlans.cancelButton')"
      />
      <member-bucks-manage-billing
        v-else-if="!cardExists && billingMethod !== 'invoice'"
      />
      <q-btn
        v-else
        :disable="disableButton"
        :loading="loadingButton"
        @click="resumePlan"
        color="success"
        :label="$tc('paymentPlans.resumeButton')"
      />
    </template>
  </q-page>
</template>

<script>
import { defineComponent } from 'vue';
import { mapGetters, mapActions } from 'vuex';
import SelectTier from '@components/Billing/SelectTier.vue';
import SelectedTier from '@components/Billing/SelectedTier.vue';
import SignupRequiredSteps from '@components/Billing/SignupRequiredSteps.vue';
import MemberBucksManageBilling from 'components/MemberBucksManageBilling.vue';
import MembershipStateBanner from '@components/MembershipStateBanner.vue';

export default defineComponent({
  name: 'MembershipTierPage',
  components: {
    MemberBucksManageBilling,
    SelectTier,
    SelectedTier,
    SignupRequiredSteps,
    MembershipStateBanner,
  },
  data() {
    return {
      disableButton: false,
      loadingButton: false,
      cancelSuccess: false,
      loadingSubscription: true,
      subscriptionUnavailable: false,
      subscriptionInfo: {
        billingCycleAnchor: null,
        currentPeriodEnd: null,
        cancelAt: null,
        cancelAtPeriodEnd: null,
        startDate: null,
      },
    };
  },
  computed: {
    ...mapGetters('profile', ['profile']),
    ...mapGetters('config', ['features']),
    profileLoaded() {
      return Object.keys(this.profile).length > 0;
    },
    signupStage() {
      return this.profile?.signupStage;
    },
    membershipPlan() {
      return this.profile?.financial?.membershipPlan;
    },
    cardExists() {
      return this?.profile?.financial?.memberBucks?.savedCard?.last4;
    },
    currentTier() {
      return this.profile.financial.membershipTier;
    },
    subscriptionStatus() {
      return this.profile.financial.subscriptionState;
    },
    billingMethod() {
      return this?.profile?.financial?.billingMethod;
    },
    currentPeriodEnd() {
      return new Date(
        this.subscriptionInfo?.currentPeriodEnd * 1000
      ).toLocaleString('en-au');
    },
    signupDate() {
      return new Date(this.subscriptionInfo?.startDate * 1000).toLocaleString(
        'en-au'
      );
    },
    cancelAtDate() {
      return new Date(this.subscriptionInfo?.cancelAt * 1000).toLocaleString(
        'en-au'
      );
    },
    paymentMethodLabel() {
      const method = this.profile?.financial?.billingMethod;
      return method === 'invoice'
        ? this.$t('paymentPlans.paymentMethodInvoice')
        : this.$t('paymentPlans.paymentMethodCard');
    },
  },
  methods: {
    ...mapActions('profile', ['getProfile']),
    getSubscriptionInfo() {
      this.loadingSubscription = true;
      this.subscriptionUnavailable = false;
      this.$axios
        .get('/api/billing/myplan/')
        .then((result) => {
          if (result.data.success) {
            this.subscriptionInfo = result.data.subscription;
          } else if (result.data.unavailable) {
            this.subscriptionUnavailable = true;
          }
        })
        .catch(() => {
          this.subscriptionUnavailable = true;
        })
        .finally(() => {
          this.loadingSubscription = false;
        });
    },
    cancelPlan() {
      this.$q
        .dialog({
          title: this.$t('confirmAction'),
          message: this.$t('paymentPlans.cancelConfirmDescription'),
          cancel: this.$t('button.back'),
          persistent: true,
        })
        .onOk(() => {
          this.disableButton = true;
          this.loadingButton = true;
          this.$axios
            .post('/api/billing/myplan/cancel/')
            .then((result) => {
              if (result.data.success) {
                this.cancelSuccess = true;
                setTimeout(() => {
                  location.reload();
                }, 3000);
              } else {
                this.$q.dialog({
                  title: this.$t('paymentPlans.cancelFailed'),
                  message: this.$t('error.contactUs'),
                });
                this.disableButton = false;
              }
            })
            .catch(() => {
              this.$q.dialog({
                title: this.$t('paymentPlans.cancelFailed'),
                message: this.$t('error.contactUs'),
              });
              this.disableButton = false;
            })
            .finally(() => {
              this.loadingButton = false;
            });
        });
    },
    resumePlan() {
      this.disableButton = true;
      this.loadingButton = true;
      this.$axios
        .post('/api/billing/myplan/resume/')
        .then((result) => {
          if (result.data.success) {
            location.reload();
          } else {
            this.$q.dialog({
              title: this.$t('paymentPlans.resumeFailed'),
              message: this.$t('error.contactUs'),
            });
            this.disableButton = false;
          }
        })
        .catch(() => {
          this.$q.dialog({
            title: this.$t('paymentPlans.resumeFailed'),
            message: this.$t('error.contactUs'),
          });
          this.disableButton = false;
        })
        .finally(() => {
          this.loadingButton = false;
        });
    },
  },
  async mounted() {
    await this.getProfile();
    this.getSubscriptionInfo();
  },
});
</script>
