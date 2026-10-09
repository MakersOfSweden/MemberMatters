<template>
  <div class="q-gutter-md">
    <div class="text-h5 text-center">{{ $t('tiers.becomeMember') }}</div>

    <div class="column flex content-start justify-center">
      <q-banner
        v-if="profile.memberStatus === 'Account Only'"
        inline-actions
        rounded
        class="bg-blue text-white q-ma-md"
      >
        <template v-slot:avatar>
          <q-icon :name="icons.info" />
        </template>
        {{ $t('paymentPlans.accountOnlyWarning') }}
      </q-banner>
    </div>

    <div v-if="!steps" class="text-center q-my-xl">
      <q-spinner size="4em" />
    </div>

    <q-stepper
      v-else
      v-model="step"
      ref="stepper"
      color="primary"
      :done-icon="icons.success"
      :vertical="$q.screen.xs"
      animated
    >
      <q-step
        v-if="steps.includes('terms')"
        :name="stepIndex('terms')"
        :title="$t('signup.termsAcceptance')"
        :icon="icons.terms"
        :done="step > stepIndex('terms')"
      >
        <terms-acceptance-step
          :cards="termsAcceptanceCards"
          @accepted="advanceFrom('terms')"
        />
      </q-step>

      <q-step
        v-if="steps.includes('tier')"
        :name="stepIndex('tier')"
        :title="$t('tiers.select')"
        :icon="icons.plans"
        :done="step > stepIndex('tier')"
      >
        <template v-if="tiers.length === 0">
          <div class="text-center text-h6">
            {{ $t('tiers.noTiers') }}
          </div>
        </template>
        <template v-else>
          <div class="text-h6 q-py-md">
            {{ $t('tiers.selectToContinue') }}
          </div>
          <div class="row items-stretch">
            <tier-card
              :class="{ featured: tier.featured }"
              class="col-xs-12 col-sm-6 col-md"
              v-for="tier in tiers"
              :key="tier.id"
              :tier="tier"
              @selected="selectedTierEvent"
            />
          </div>
        </template>
      </q-step>

      <q-step
        :name="stepIndex('plan')"
        :title="$t('paymentPlans.select')"
        :icon="icons.dollar"
        :done="step > stepIndex('plan')"
      >
        <div class="q-pa-md">
          <q-card class="bg-white text-black" style="max-width: 500px">
            <q-card-section>
              <div class="row items-center no-wrap">
                <q-icon :name="icons.plans" size="sm" class="q-mr-md" />
                <div>
                  <div class="text-caption">{{ $t('tiers.selected') }}</div>
                  <div class="text-h6">{{ selectedTier.name }}</div>
                  <div v-if="selectedTier.description" class="text-subtitle2">
                    {{ selectedTier.description }}
                  </div>
                </div>
              </div>
            </q-card-section>
          </q-card>
        </div>

        <template v-if="selectedTier.plans && selectedTier.plans.length === 0">
          <div class="text-center text-h6">
            {{ $t('paymentPlans.noPlans') }}
          </div>
        </template>
        <template v-else>
          <div class="text-h6 q-py-md">
            {{ $t('paymentPlans.selectToContinue') }}
          </div>

          <div class="row items-stretch">
            <plan-card
              class="col-xs-12 col-sm-6 col-md"
              v-for="plan in selectedTier.plans"
              :key="plan.id"
              :plan="plan"
              @selected="selectedPlanEvent"
            />
          </div>

          <div class="row justify-start">
            <q-btn
              v-if="steps.includes('tier')"
              class="q-mt-md"
              @click="backToTiers"
              flat
              :label="$t('button.back')"
            />
          </div>
        </template>
      </q-step>

      <q-step
        class="flex flex-center"
        :name="stepIndex('billing')"
        :title="$t('menuLink.billing')"
        :icon="icons.billing"
        :done="step > stepIndex('billing')"
      >
        <div class="text-h6 q-py-md">
          {{ $t('memberbucks.selectToContinue') }}
        </div>

        <div
          v-if="
            features.enableInvoiceBilling && features.enableMembershipPayments
          "
          class="q-mb-md"
          style="max-width: 500px"
        >
          <div class="text-subtitle1 q-mb-sm">
            {{ $t('billing.selectMethod') }}
          </div>
          <q-list bordered separator class="rounded-borders">
            <q-item
              clickable
              v-ripple
              :class="{
                'billing-method-active': selectedBillingMethod === 'invoice',
              }"
              @click="selectedBillingMethod = 'invoice'"
            >
              <q-item-section avatar>
                <q-icon name="mdi-email-outline" />
              </q-item-section>
              <q-item-section>
                <q-item-label>{{ $t('billing.payByInvoice') }}</q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-radio
                  v-model="selectedBillingMethod"
                  val="invoice"
                  color="primary"
                />
              </q-item-section>
            </q-item>

            <q-item
              clickable
              v-ripple
              :class="{
                'billing-method-active': selectedBillingMethod === 'card',
              }"
              @click="selectedBillingMethod = 'card'"
            >
              <q-item-section avatar>
                <q-icon name="mdi-credit-card-outline" />
              </q-item-section>
              <q-item-section>
                <q-item-label>{{ $t('billing.payByCard') }}</q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-radio
                  v-model="selectedBillingMethod"
                  val="card"
                  color="primary"
                />
              </q-item-section>
            </q-item>
          </q-list>

          <div class="text-caption q-mt-sm q-px-sm">
            {{
              selectedBillingMethod === 'card'
                ? $t('billing.cardDescription')
                : $t('billing.invoiceDescription')
            }}
          </div>
          <div
            v-if="
              selectedBillingMethod === 'invoice' && features.invoiceBillingNote
            "
            class="text-caption q-mt-xs q-px-sm"
          >
            {{ features.invoiceBillingNote }}
          </div>
        </div>

        <member-bucks-manage-billing
          v-if="selectedBillingMethod === 'card'"
          style="max-width: 500px"
          flat
          @card-exists="cardExistsHandler"
        />

        <div class="row justify-start q-mt-md">
          <q-btn @click="backToPlans" flat :label="$t('button.back')" />
          <q-space />
          <q-btn
            :disabled="!canContinueBilling"
            @click="selectedBillingMethodEvent"
            color="primary"
            :label="$t('button.continue')"
          />
        </div>
      </q-step>

      <q-step
        :name="stepIndex('confirm')"
        :title="$t('paymentPlans.confirmSelection')"
        :icon="icons.success"
        :done="step > stepIndex('confirm')"
      >
        <div class="row">
          <div class="row col-xs-12 col-sm-6">
            <div class="text-h6 col-12">{{ $t('tiers.selected') }}</div>
            <tier-card class="col-12" :tier="selectedTier" selected />
          </div>
          <div class="row col-xs-12 col-sm-6">
            <div class="text-h6 col-12">{{ $t('paymentPlans.selected') }}</div>
            <plan-card class="col-12" :plan="selectedPlan" selected />
          </div>
        </div>

        <div v-if="planSelected" class="text-h6">
          <template v-if="selectedBillingMethod === 'invoice'">
            {{
              $t('billing.invoiceAmount', {
                amount: $n(
                  selectedPlan.cost / 100,
                  'currency',
                  siteLocaleCurrency
                ),
              })
            }}
          </template>
          <template v-else>
            {{
              $t('paymentPlans.dueToday', {
                amount: $n(
                  selectedPlan.cost / 100,
                  'currency',
                  siteLocaleCurrency
                ),
              })
            }}
          </template>
        </div>

        <p v-if="planSelected" class="q-py-md" style="max-width: 850px">
          {{
            $t('tiers.confirm', {
              intervalDescription: $t('paymentPlans.intervalDescription', {
                currency: selectedPlan.currency.toUpperCase(),
                amount: $n(
                  selectedPlan.cost / 100,
                  'currency',
                  siteLocaleCurrency
                ),
                interval: $t(
                  `paymentPlans.interval.${selectedPlan.interval.toLowerCase()}`,
                  selectedPlan.intervalAmount
                ),
              }),
            })
          }}
        </p>

        <div class="text-subtitle2 q-pb-md">
          {{ $t('tiers.confirmDelay') }}
        </div>

        <div v-if="finishSuccess" class="row">
          <q-banner class="bg-success text-white">
            <div class="text-h5">{{ $t('paymentPlans.signupSuccess') }}</div>
            <p>
              {{
                selectedBillingMethod === 'invoice'
                  ? $t('paymentPlans.signupSuccessInvoiceDescription')
                  : $t('paymentPlans.signupSuccessDescription')
              }}
            </p>
          </q-banner>
        </div>

        <div v-else class="row">
          <q-btn
            flat
            :disable="disableFinish || loading"
            @click="backToBilling"
            :label="$t('button.back')"
          />
          <q-space />
          <q-btn
            :loading="loading"
            :disable="disableFinish"
            @click="finishSignup"
            color="primary"
            :label="
              selectedBillingMethod === 'invoice'
                ? $t('tiers.finishInvoice')
                : $t('tiers.finish')
            "
          />
        </div>
      </q-step>
    </q-stepper>
  </div>
</template>

<script>
import { mapGetters } from 'vuex';
import { defineComponent } from 'vue';
import TierCard from '@components/Billing/TierCard.vue';
import PlanCard from '@components/Billing/PlanCard.vue';
import MemberBucksManageBilling from '@components/MemberBucksManageBilling.vue';
import TermsAcceptanceStep from '@components/Billing/TermsAcceptanceStep.vue';
import icons from '@icons';
import { nextStepAfter, preSignupSteps } from '../../utils/signupSteps';

export default defineComponent({
  name: 'SelectTier',
  data() {
    return {
      steps: null,
      step: 0,
      tiers: [],
      selectedTier: {},
      selectedPlan: {},
      disableFinish: false,
      loading: false,
      finishSuccess: false,
      cardExists: false,
      selectedBillingMethod: 'card',
    };
  },
  computed: {
    ...mapGetters('profile', ['loggedIn', 'profile']),
    ...mapGetters('config', ['siteLocaleCurrency', 'features']),
    icons() {
      return icons;
    },
    canContinueBilling() {
      if (this.selectedBillingMethod === 'invoice') return true;
      return !!this.cardExists;
    },
    termsAcceptanceCards() {
      return this.features.signup?.termsAcceptanceCards || [];
    },
    // The confirm step's summary reads cost/currency/interval off the plan.
    planSelected() {
      const plan = this.selectedPlan;
      return !!(plan.currency && plan.interval && plan.cost != null);
    },
  },
  components: {
    TierCard,
    PlanCard,
    MemberBucksManageBilling,
    TermsAcceptanceStep,
  },
  mounted() {
    // Manual renewal (invoice) is the first/default option, but only when
    // it's actually offered — mirror the picker's own visibility gate.
    if (
      this.features.enableInvoiceBilling &&
      this.features.enableMembershipPayments
    ) {
      this.selectedBillingMethod = 'invoice';
    }
    this.buildSteps();
  },
  methods: {
    async buildSteps() {
      // If can-signup fails, assume terms are outstanding: re-accepting only
      // re-stamps a timestamp, skipping them would bypass a legal gate.
      const [tiers, outstanding] = await Promise.all([
        this.$axios
          .get('/api/billing/tiers/')
          .then((response) => response.data)
          .catch(() => []),
        this.$axios
          .get('/api/billing/can-signup/')
          .then((response) => response.data.requiredSteps || [])
          .catch(() => ['termsAcceptance']),
      ]);
      this.tiers = tiers;

      // Only one membership plan to choose — preselect it.
      if (this.tiers.length === 1) {
        this.selectedTier = this.tiers[0];
      }

      this.steps = preSignupSteps(this.features, {
        tierCount: this.tiers.length,
        outstanding,
      });
    },
    stepIndex(name) {
      return this.steps.indexOf(name);
    },
    advanceFrom(name) {
      const next = nextStepAfter(this.steps, name);
      if (next) this.step = this.stepIndex(next);
    },
    finishSignup() {
      this.disableFinish = true;
      this.loading = true;
      this.$axios
        .post(`/api/billing/plans/${this.selectedPlan.id}/signup/`, {
          billingMethod: this.selectedBillingMethod,
        })
        .then((response) => {
          if (response.data.success) {
            this.finishSuccess = true;
            setTimeout(() => {
              location.reload();
            }, 3000);
          } else if (response.data.message) {
            this.disableFinish = false;
            this.$q.dialog({
              title: this.$t('paymentPlans.signupFailed'),
              message: this.$t(response.data.message),
            });
          } else {
            this.disableFinish = false;
            this.$q.dialog({
              title: this.$t('paymentPlans.signupFailed'),
              message: this.$t('error.contactUs'),
            });
          }
        })
        .catch(() => {
          this.disableFinish = false;
          this.$q.dialog({
            title: this.$t('paymentPlans.signupFailed'),
            message: this.$t('error.contactUs'),
          });
        })
        .finally(() => {
          this.loading = false;
        });
    },
    selectedTierEvent(tier) {
      this.selectedTier = tier;
      this.advanceFrom('tier');
    },
    selectedPlanEvent(plan) {
      this.selectedPlan = plan;
      this.advanceFrom('plan');
    },
    selectedBillingMethodEvent() {
      this.advanceFrom('billing');
    },
    backToTiers() {
      this.selectedPlan = {};
      this.selectedTier = {};
      this.step = this.stepIndex('tier');
    },
    backToPlans() {
      this.selectedPlan = {};
      this.step = this.stepIndex('plan');
    },
    backToBilling() {
      this.step = this.stepIndex('billing');
    },
    cardExistsHandler(value) {
      this.cardExists = value;
    },
  },
});
</script>

<style lang="scss" scoped>
.featured {
  transform: scale(1.1);
}

.q-stepper__step-inner {
  width: 90vw;
  max-width: 1000px;
}

.billing-method-active {
  background-color: color-mix(in srgb, var(--q-primary) 8%, transparent);
}
</style>
