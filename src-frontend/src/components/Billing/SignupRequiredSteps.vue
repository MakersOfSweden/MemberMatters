<template>
  <div class="q-gutter-md">
    <div v-if="!steps" class="text-center q-my-xl">
      <q-spinner size="4em" />
    </div>

    <q-stepper v-else v-model="step" ref="stepper" color="primary" animated>
      <q-step
        :name="stepIndex('billing')"
        :title="$t('signup.billing')"
        :icon="icons.billing"
        :active-icon="icons.billing"
        done
      >
        <p class="q-py-md">{{ $t('signup.billingCompletedDescription') }}</p>
      </q-step>

      <q-step
        v-if="steps.includes('terms')"
        :name="stepIndex('terms')"
        :title="$t('signup.termsAcceptance')"
        :icon="icons.terms"
        :active-icon="icons.terms"
        :done="step > stepIndex('terms')"
      >
        <terms-acceptance-step
          :cards="termsAcceptanceCards"
          @accepted="advanceFrom('terms')"
        />
      </q-step>

      <q-step
        v-if="steps.includes('induction')"
        :name="stepIndex('induction')"
        :title="$t('signup.induction')"
        :icon="icons.induction"
        :active-icon="icons.induction"
        :done="step > stepIndex('induction')"
      >
        <div class="text-h6 q-py-md">
          {{ $t('signup.completeInduction') }}
        </div>
        <div class="row items-stretch">
          <div style="width: 100%">
            <p>
              {{ $t('signup.completeInductionDescription') }}
            </p>

            <p
              v-if="
                features.signup.inductionLink.includes('canvas.instructure.com')
              "
            >
              <b>
                {{ $t('signup.canvasEmailWarning', { email: profile.email }) }}
              </b>
            </p>
          </div>

          <template v-if="!inductionComplete">
            <div>
              <p>
                <a
                  v-if="
                    features.signup.inductionLink.includes(
                      'canvas.instructure.com'
                    )
                  "
                  :href="features.signup.inductionLink"
                  target="_blank"
                >
                  <img
                    class="q-pa-sm rounded-borders"
                    style="max-height: 70px; border: 1px solid"
                    src="@assets/img/canvas.png"
                  />
                </a>

                <q-btn
                  v-else
                  :href="features.signup.inductionLink"
                  target="_blank"
                  color="primary"
                  :label="$t('signup.startInduction')"
                />
              </p>
              <p>
                {{ $t('signup.waitingCompletion') }} <br />
                {{ $t('progress', { percent: inductionScore }) }}
              </p>
              <q-spinner size="2em"></q-spinner>
            </div>
          </template>

          <template v-else>
            <div class="q-pt-md">
              <p>
                {{ $t('signup.completedInduction') }}
              </p>
              <q-icon color="success" size="2em" :name="icons.success" />
            </div>
          </template>
        </div>

        <div class="row justify-start q-mt-md">
          <q-space />
          <q-btn
            @click="inductionCompleted()"
            :disable="!inductionComplete"
            color="primary"
            :label="$t('button.continue')"
          />
        </div>
      </q-step>

      <q-step
        v-if="steps.includes('accessCard')"
        :name="stepIndex('accessCard')"
        :title="$t('signup.accessCard')"
        :icon="icons.accessCard"
        :active-icon="icons.accessCard"
        :done="step > stepIndex('accessCard')"
      >
        <div class="text-h6 q-py-md">
          {{ $t('signup.assignAccessCard') }}
        </div>

        <template v-if="features.signup.memberCanEnterAccessCard">
          <div class="row items-stretch">
            <div style="width: 100%">
              <p>
                {{ $t('signup.assignAccessCardDescription') }}
              </p>

              <p>
                <b>
                  {{
                    $t('signup.assignAccessCardWarning', {
                      email: profile.email,
                    })
                  }}
                </b>
              </p>

              <div>
                <q-input
                  style="max-width: 300px"
                  outlined
                  v-model="accessCard"
                  :label="$t('signup.accessCardNumber')"
                />
              </div>
            </div>
          </div>

          <div class="row justify-start q-mt-md">
            <q-space />
            <q-btn
              :disable="accessCardLoading"
              @click="submitAccessCard"
              color="primary"
              :label="$t('button.continue')"
            />
          </div>
        </template>
        <template v-else>
          <div class="row items-stretch">
            <div style="max-width: 400px">
              <p>
                {{ $t('signup.collectAccessCardDescription') }}
              </p>
            </div>
          </div>

          <div class="row justify-start q-mt-md">
            <q-space />
            <q-btn
              :href="features.signup.postInductionUrl"
              target="_blank"
              color="primary"
              :label="$t('button.contactUs')"
            />
          </div>
        </template>
      </q-step>

      <q-step
        :name="stepIndex('confirm')"
        :title="$t('confirm')"
        :icon="icons.success"
        :active-icon="icons.success"
        :done="step >= stepIndex('confirm')"
      >
        <template v-if="awaitingPayment">
          <q-banner class="bg-info text-white">
            <div class="text-h5">{{ $t('signup.awaitingPaymentTitle') }}</div>
            <p>{{ $t('signup.awaitingInvoicePayment') }}</p>
          </q-banner>

          <div class="row justify-start q-mt-md">
            <q-space />
            <q-btn
              :to="{ name: 'dashboard' }"
              color="primary"
              :label="$t('signup.continueToDashboard')"
            />
          </div>
        </template>

        <template v-else-if="signupError">
          <div class="text-h6 q-py-md">
            {{ $t('signup.error') }}
          </div>

          <div style="width: 100%">
            <p>
              {{ $t('signup.errorDescription', { email: contact.admin }) }}
            </p>

            <p>
              {{ $t('signup.errorMessageDescription') }}
              <br />
              <b>{{ signupErrorMessage }}</b>
              <br />
              <b>{{ signupErrorItems }}</b>
            </p>
          </div>
        </template>

        <template v-else>
          <div class="text-h6 q-py-md">
            {{
              $t(
                applicationEmailEnabled
                  ? 'signup.submitted'
                  : 'signup.submittedNoEmail'
              )
            }}
          </div>

          <div class="row items-stretch">
            <div style="width: 100%">
              <p>
                {{
                  $t(
                    applicationEmailEnabled
                      ? 'signup.submittedDescription'
                      : 'signup.submittedDescriptionNoEmail'
                  )
                }}
              </p>
            </div>

            <div class="q-pt-md">
              <q-icon color="success" size="2em" :name="icons.success" />
            </div>
          </div>

          <div class="row justify-start q-mt-md">
            <q-space />
            <q-btn
              :to="{ name: 'dashboard' }"
              color="primary"
              :label="$t('signup.continueToDashboard')"
            />
          </div>
        </template>
      </q-step>
    </q-stepper>
  </div>
</template>

<script lang="ts">
import { defineComponent } from 'vue';
import { mapGetters, mapActions } from 'vuex';
import icons from '@icons';
import { api } from 'boot/axios';
import TermsAcceptanceStep from '@components/Billing/TermsAcceptanceStep.vue';
import {
  nextStepAfter,
  postSignupSteps,
  signupStepStatus,
  SignupStep,
} from '../../utils/signupSteps';

export default defineComponent({
  name: 'SignupRequiredSteps',
  components: { TermsAcceptanceStep },
  data() {
    return {
      steps: null,
      step: 0,
      // can-signup's requiredSteps: what the backend still wants.
      outstanding: [] as string[],
      inductionComplete: false,
      accessCard: null,
      accessCardLoading: false,
      signupError: false,
      signupErrorMessage: 'Unknown',
      signupErrorItems: [],
      awaitingPayment: false,
      inductionScore: 0,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      interval: null as any,
    };
  },
  computed: {
    ...mapGetters('config', ['features', 'contact']),
    ...mapGetters('profile', ['profile']),
    icons() {
      return icons;
    },
    termsAcceptanceCards() {
      return this.features.signup.termsAcceptanceCards || [];
    },
    applicationEmailEnabled(): boolean {
      return this.features.signup.enableMembershipApplicationEmail;
    },
  },
  mounted() {
    this.updateInductionStatus();
    this.interval = setInterval(async () => {
      this.updateInductionStatus();
    }, 10000);

    api
      .get('/api/billing/can-signup/')
      // If we can't tell what's outstanding, assume everything is.
      .catch(() => ({
        data: { requiredSteps: ['termsAcceptance', 'induction', 'accessCard'] },
      }))
      .then((result) => {
        this.outstanding = result.data.requiredSteps || [];
        this.steps = postSignupSteps(this.features);
        // Billing is a done breadcrumb. Start on the first step still
        // required, or complete signup straight away if none is.
        this.advanceFrom('billing');
      });
  },
  beforeUnmount() {
    // beforeRouteLeave only fires on a route change; a parent re-render,
    // layout swap, or logout that unmounts us without one would leave the
    // 10s poller running. beforeUnmount catches every teardown path.
    clearInterval(this.interval);
  },
  methods: {
    stepIndex(name: string) {
      return this.steps.indexOf(name);
    },
    // Skips steps the backend no longer requires (e.g. terms accepted before
    // payment, or an access card kept from a previous membership); finalizes
    // when the next step is 'confirm'.
    advanceFrom(name: string) {
      const next = nextStepAfter(
        this.steps,
        name,
        (step) =>
          step !== 'confirm' &&
          signupStepStatus(step as SignupStep, this.outstanding, null).complete
      );
      if (next === null || next === 'confirm') {
        this.completeSignup();
      } else {
        this.step = this.stepIndex(next);
      }
    },
    async updateInductionStatus() {
      let result = await api.post('/api/billing/check-induction/');
      this.inductionComplete = result.data.success;
      this.inductionScore = Math.floor(result.data.score);

      if (this.inductionComplete || result.data.notRequired) {
        this.inductionCompleted();
      }
    },
    inductionCompleted() {
      // The induction poll can beat can-signup, and until that answers we
      // don't have a step list to check against. Leave the poller running
      // rather than stopping it on a decision we can't make yet.
      if (!this.steps) return;
      // Guard against a late poll firing after can-signup already
      // advanced us off the induction step.
      clearInterval(this.interval);
      if (this.step !== this.stepIndex('induction')) return;
      this.advanceFrom('induction');
    },
    ...mapActions('profile', ['getProfile']),
    async completeSignup() {
      clearInterval(this.interval);
      api
        .post('/api/billing/complete-signup/')
        .then((result) => {
          if (result.data.awaitingPayment) {
            this.awaitingPayment = true;
            // Refresh so the parent re-derives signupStage and swaps to the
            // awaiting-payment view.
            this.getProfile();
          } else if (!result.data.success) {
            this.signupError = true;
            this.signupErrorMessage = result.data.message;
            this.signupErrorItems = result.data.items;
          } else {
            this.signupError = false;
            // Server flipped the member to active — refresh the profile so
            // the parent page re-derives signupStage (-> "managed") and
            // advances off the required-steps view.
            this.getProfile();
          }
        })
        .catch(() => {
          this.signupError = true;
        })
        .finally(() => {
          // Land on the final "Submitted" step regardless of caller.
          this.step = this.stepIndex('confirm');
        });
    },
    async submitAccessCard() {
      this.accessCardLoading = true;
      await api
        .post('/api/billing/access-card/', {
          accessCard: this.accessCard,
        })
        .then((result) => {
          if (result.data.success) {
            this.advanceFrom('accessCard');
          } else {
            this.showAccessCardError(result.data?.message);
          }
        })
        .catch((err) => {
          this.showAccessCardError(err.response?.data?.message);
        })
        .finally(() => {
          this.accessCardLoading = false;
        });
    },
    showAccessCardError(messageKey) {
      this.$q.dialog({
        title: this.$t('error.error'),
        message: messageKey ? this.$t(messageKey) : this.$t('error.contactUs'),
      });
    },
  },
});
</script>
