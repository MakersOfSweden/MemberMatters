<template>
  <div class="column flex content-start items-start q-gutter-y-lg">
    <q-banner
      v-if="integrityIssues.length"
      :class="integrityBannerClass"
      class="rounded-borders full-width"
    >
      <template v-slot:avatar>
        <q-icon :name="icons.billingIntegrity" />
      </template>
      <div class="text-subtitle2">
        {{ integrityIssues.length }} billing
        {{ integrityIssues.length === 1 ? 'issue' : 'issues' }}: MemberMatters
        and Stripe disagree
      </div>
      <ul class="q-my-xs q-pl-md">
        <li v-for="issue in integrityIssues" :key="issue.id">
          {{ issue.message }}
          <span class="text-caption">
            — MemberMatters says: {{ issue.mm || '—' }} · Stripe says:
            {{ issue.stripe || '—' }}
          </span>
          <span v-if="issue.acknowledged" class="text-caption">
            (acknowledged)
          </span>
        </li>
      </ul>
      <template v-slot:action>
        <q-btn
          flat
          label="Re-check"
          :loading="recheckingIntegrity"
          @click="recheckIntegrity"
        />
        <q-btn
          flat
          label="All billing issues"
          :to="{ name: 'billingIntegrity' }"
        />
      </template>
    </q-banner>

    <div class="column q-gutter-y-sm full-width">
      <div class="text-h6">
        {{ $t('adminTools.subscriptionInfo') }}
      </div>

      <div
        v-if="loadingSubscription"
        class="full-width flex flex-center q-pa-lg"
      >
        <q-spinner color="primary" size="40px" />
      </div>

      <template v-else>
        <q-markup-table
          v-if="subscription"
          bordered
          padding
          class="rounded-borders desktop-only"
        >
          <thead>
            <tr>
              <th class="text-left">
                {{ $t(`adminTools.membershipTier`) }}
              </th>
              <th class="text-left">
                {{ $t(`adminTools.billingPlan`) }}
              </th>
              <th class="text-left">
                {{ $t(`paymentPlans.paymentMethod`) }}
              </th>
              <th class="text-left">
                {{ $t(`adminTools.billingCycleAnchor`) }}
              </th>
              <th class="text-left">{{ $t(`adminTools.startDate`) }}</th>
              <th class="text-left">
                {{ $t(`adminTools.currentPeriodEnd`) }}
              </th>
              <template v-if="subscription.cancelAt">
                <th class="text-left">
                  {{ $t(`adminTools.cancelAt`) }}
                </th>
                <th class="text-left">
                  {{ $t(`adminTools.cancelAtPeriodEnd`) }}
                </th>
              </template>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td class="text-left">
                <router-link
                  :to="{
                    name: 'manageTier',
                    params: {
                      planId: subscription.membershipPlan.id,
                    },
                  }"
                  >{{ subscription.membershipTier.name }}</router-link
                >
              </td>
              <td class="text-left">
                {{
                  $t('paymentPlans.intervalDescription', {
                    currency:
                      subscription.membershipPlan.currency.toUpperCase(),
                    amount: $n(
                      subscription.membershipPlan.cost / 100,
                      'currency',
                      siteLocaleCurrency
                    ),
                    interval: $t(
                      `paymentPlans.interval.${subscription.membershipPlan.interval.toLowerCase()}`,
                      subscription.membershipPlan.intervalAmount
                    ),
                  })
                }}
              </td>
              <td class="text-left">
                {{ paymentMethodLabel }}
              </td>
              <td class="text-left">
                {{ formatDate(subscription.billingCycleAnchor) }}
              </td>
              <td class="text-left">
                {{ formatDate(subscription.startDate) }}
              </td>
              <td class="text-left">
                {{ formatDate(subscription.currentPeriodEnd) }}
              </td>
              <template v-if="subscription.cancelAt">
                <td class="text-left">
                  {{ formatDate(subscription.cancelAt) }}
                </td>
                <td class="text-left">
                  {{ formatBooleanYesNo(subscription.cancelAtPeriodEnd) }}
                </td>
              </template>
            </tr>
          </tbody>
        </q-markup-table>

        <q-list
          v-if="subscription"
          bordered
          padding
          class="rounded-borders desktop-hide"
          style="max-width: 350px"
        >
          <q-item>
            <q-item-section>
              <q-item-label
                lines="1"
                :class="{
                  inactive: subscription.status === 'inactive',
                  active: subscription.status === 'active',
                  cancelling: subscription.status === 'cancelling',
                }"
              >
                {{
                  $t(
                    `adminTools.subscriptionStatusString.${subscription.status}`
                  )
                }}
              </q-item-label>
              <q-item-label caption>
                {{ $t(`adminTools.subscriptionStatus`) }}
              </q-item-label>
            </q-item-section>
          </q-item>

          <q-item>
            <q-item-section>
              <q-item-label lines="1">
                {{ paymentMethodLabel }}
              </q-item-label>
              <q-item-label caption>
                {{ $t(`paymentPlans.paymentMethod`) }}
              </q-item-label>
            </q-item-section>
          </q-item>

          <q-item>
            <q-item-section>
              <q-item-label lines="1">
                {{ formatDate(subscription.billingCycleAnchor) }}
              </q-item-label>
              <q-item-label caption>
                {{ $t(`adminTools.billingCycleAnchor`) }}
              </q-item-label>
            </q-item-section>
          </q-item>

          <q-item>
            <q-item-section>
              <q-item-label lines="1">
                {{ formatDate(subscription.startDate) }}
              </q-item-label>
              <q-item-label caption>
                {{ $t(`adminTools.startDate`) }}
              </q-item-label>
            </q-item-section>
          </q-item>

          <q-item>
            <q-item-section>
              <q-item-label lines="1">
                {{ formatDate(subscription.currentPeriodEnd) }}
              </q-item-label>
              <q-item-label caption>
                {{ $t(`adminTools.currentPeriodEnd`) }}
              </q-item-label>
            </q-item-section>
          </q-item>

          <q-item v-if="subscription.cancelAt">
            <q-item-section>
              <q-item-label lines="1">
                {{ formatDate(subscription.cancelAt) }}
              </q-item-label>
              <q-item-label caption>
                {{ $t(`adminTools.cancelAt`) }}
              </q-item-label>
            </q-item-section>
          </q-item>

          <q-item v-if="subscription.cancelAtPeriodEnd">
            <q-item-section>
              <q-item-label lines="1">
                {{ subscription.cancelAtPeriodEnd }}
              </q-item-label>
              <q-item-label caption>
                {{ $t(`adminTools.cancelAtPeriodEnd`) }}
              </q-item-label>
            </q-item-section>
          </q-item>
        </q-list>

        <q-btn
          v-if="subscription?.invoiceUrl"
          outline
          no-caps
          color="primary"
          class="self-start"
          icon="mdi-open-in-new"
          :label="$t('billing.viewInvoice')"
          :href="subscription.invoiceUrl"
          target="_blank"
        />

        <q-banner
          v-if="subscriptionUnavailable"
          class="bg-warning text-white rounded-borders"
        >
          {{ $t('adminTools.subscriptionUnavailable') }}
        </q-banner>

        <div v-else-if="!subscription">
          {{ $t(`adminTools.noSubscription`) }}
        </div>
      </template>
    </div>

    <div v-if="loading" class="full-width flex flex-center q-pa-xl">
      <q-spinner color="primary" size="40px" />
    </div>

    <template v-else>
      <div class="column q-gutter-y-sm full-width">
        <div class="text-h6">
          {{ $t('adminTools.billingInfo') }}
        </div>

        <q-markup-table
          v-if="billing?.memberbucks"
          bordered
          padding
          class="rounded-borders desktop-only"
        >
          <thead>
            <tr>
              <th class="text-left">
                {{ $t(`memberbucks.lastPurchase`) }}
              </th>
              <th class="text-left">
                {{ $t(`memberbucks.cardExpiry`) }}
              </th>
              <th class="text-left">{{ $t(`memberbucks.last4`) }}</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td class="text-left">
                <div v-if="billing?.memberbucks.lastPurchase">
                  {{ this.formatWhen(billing?.memberbucks.lastPurchase) }}
                  <q-tooltip :delay="500">
                    {{ this.formatDate(billing?.memberbucks.lastPurchase) }}
                  </q-tooltip>
                </div>
                <div v-else>
                  {{ $t('error.noValue') }}
                </div>
              </td>
              <td class="text-left">
                {{
                  billing?.memberbucks.stripe_card_expiry || $t('error.noValue')
                }}
              </td>
              <td class="text-left">
                {{
                  billing?.memberbucks.stripe_card_last_digits ||
                  $t('error.noValue')
                }}
              </td>
            </tr>
          </tbody>
        </q-markup-table>

        <q-list
          bordered
          padding
          class="rounded-borders mobile-only"
          style="max-width: 350px"
        >
          <q-item>
            <q-item-section>
              <q-item-label lines="1">
                <div v-if="billing?.memberbucks.lastPurchase">
                  {{ this.formatWhen(billing?.memberbucks.lastPurchase) }}
                  <q-tooltip :delay="500">
                    {{ this.formatDate(billing?.memberbucks.lastPurchase) }}
                  </q-tooltip>
                </div>
                <div v-else>
                  {{ $t('error.noValue') }}
                </div>
              </q-item-label>
              <q-item-label caption>
                {{ $t(`memberbucks.lastPurchase`) }}
              </q-item-label>
            </q-item-section>
          </q-item>

          <q-item>
            <q-item-section>
              <q-item-label lines="1">
                {{
                  billing?.memberbucks.stripe_card_expiry || $t('error.noValue')
                }}
              </q-item-label>
              <q-item-label caption>
                {{ $t(`memberbucks.cardExpiry`) }}
              </q-item-label>
            </q-item-section>
          </q-item>

          <q-item>
            <q-item-section>
              <q-item-label lines="1">
                {{
                  billing?.memberbucks.stripe_card_last_digits ||
                  $t('error.noValue')
                }}
              </q-item-label>
              <q-item-label caption>
                {{ $t(`memberbucks.last4`) }}
              </q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </div>

      <div class="column q-gutter-y-sm full-width">
        <div class="text-h6">
          {{ $t('adminTools.memberbucksTransactions') }}
        </div>

        <q-table
          :rows="billing?.memberbucks?.transactions ?? []"
          :columns="[
            {
              name: 'description',
              label: 'Description',
              field: 'description',
              sortable: true,
            },
            {
              name: 'amount',
              label: 'Amount',
              field: 'amount',
              sortable: true,
            },
            {
              name: 'date',
              label: 'When',
              field: 'date',
              sortable: true,
              format: (val) => formatWhen(val),
            },
          ]"
          row-key="id"
          :filter="filter"
          v-model:pagination="pagination"
          :loading="loading"
          :grid="$q.screen.xs"
        >
          <template v-slot:top-left>
            <div class="row">
              <q-input
                v-if="$q.screen.xs"
                v-model="filter"
                outlined
                dense
                debounce="300"
                placeholder="Search"
                style="margin-top: -3px"
              >
                <template v-slot:append>
                  <q-icon :name="icons.search" />
                </template>
              </q-input>
            </div>
            <div class="row">
              {{ $t('memberbucks.currentBalance') }}
              {{
                $n(
                  billing?.memberbucks.balance || 0,
                  'currency',
                  siteLocaleCurrency
                )
              }}
            </div>
          </template>

          <template v-if="$q.screen.gt.xs" v-slot:top-right>
            <q-input
              v-model="filter"
              outlined
              dense
              debounce="300"
              placeholder="Search"
              style="margin-top: -3px"
            >
              <template v-slot:append>
                <q-icon :name="icons.search" />
              </template>
            </q-input>
          </template>

          <template v-slot:body-cell-amount="props">
            <q-td>
              <div
                :class="{
                  credit: props.value > 0,
                  debit: props.value < 0,
                }"
              >
                ${{ props.value }}
              </div>
            </q-td>
          </template>
        </q-table>
      </div>
    </template>
  </div>
</template>

<script lang="ts">
import formatMixin from '@mixins/formatMixin';
import icons from '@icons';
import { mapGetters } from 'vuex';
import { MemberBillingInfo } from 'types/member';
import { MemberSubscription } from 'types/subscriptions';
import type { IntegrityIssue } from 'types/billingIntegrity';
import { defineComponent } from 'vue';
import { apiMessage, compareIssues } from '../../../utils/billingIntegrity';

export default defineComponent({
  name: 'MemberBillingTab',
  mixins: [formatMixin],
  props: {
    memberId: {
      type: Number,
      default: null,
    },
  },
  emits: ['memberUpdated'],
  data() {
    return {
      billing: null as MemberBillingInfo | null,
      subscription: null as MemberSubscription | null,
      subscriptionUnavailable: false,
      filter: '',
      loading: true,
      loadingSubscription: true,
      integrityIssues: [] as IntegrityIssue[],
      recheckingIntegrity: false,
      pagination: {
        sortBy: 'date',
        descending: true,
        rowsPerPage: this.$q.screen.xs ? 3 : 5,
      },
    };
  },
  computed: {
    ...mapGetters('config', ['siteLocaleCurrency']),
    icons() {
      return icons;
    },
    integrityBannerClass(): string {
      const critical = this.integrityIssues.some(
        (issue) => issue.severity === 'critical' && !issue.acknowledged
      );
      return critical ? 'bg-negative text-white' : 'bg-warning text-dark';
    },
    paymentMethodLabel(): string {
      return this.subscription?.billingMethod === 'invoice'
        ? this.$t('paymentPlans.paymentMethodInvoice')
        : this.$t('paymentPlans.paymentMethodCard');
    },
  },
  watch: {
    memberId() {
      this.getMemberBilling();
      this.getMemberSubscription();
      this.getMemberIntegrity();
    },
  },
  mounted() {
    if (this.memberId) {
      this.getMemberBilling();
      this.getMemberSubscription();
      this.getMemberIntegrity();
    } else {
      this.loading = false;
      this.loadingSubscription = false;
    }
  },
  methods: {
    getMemberBilling() {
      this.loading = true;
      this.$axios
        .get(`/api/admin/members/${this.memberId}/billing/`)
        .catch(() => {
          this.$q.dialog({
            title: this.$t('error.error'),
            message: this.$t('error.requestFailed'),
          });
        })
        .then((res) => {
          if (!res) return;
          this.billing = res.data;
        })
        .finally(() => {
          this.loading = false;
          this.$emit('memberUpdated');
        });
    },
    getMemberSubscription() {
      this.loadingSubscription = true;
      this.$axios
        .get(`/api/admin/members/${this.memberId}/subscription/`)
        .then((res) => {
          this.subscription = res.data.subscription;
          this.subscriptionUnavailable = res.data.subscriptionUnavailable;
        })
        .catch(() => {
          // couldn't reach our endpoint at all — surface the same notice
          this.subscriptionUnavailable = true;
        })
        .finally(() => {
          this.loadingSubscription = false;
        });
    },
    integrityUrl(): string {
      return `/api/admin/members/${this.memberId}/billing-integrity/`;
    },
    showIntegrity(data: { enabled: boolean; issues: IntegrityIssue[] }) {
      this.integrityIssues = data.enabled
        ? [...data.issues].sort(compareIssues)
        : [];
    },
    getMemberIntegrity() {
      // The banner is a hint: if the check can't be read, the tab works
      // without it.
      this.$axios
        .get(this.integrityUrl())
        .then((res) => this.showIntegrity(res.data))
        .catch(() => {
          this.integrityIssues = [];
        });
    },
    recheckIntegrity() {
      this.recheckingIntegrity = true;
      this.$axios
        .post(this.integrityUrl())
        .then((res) => {
          this.showIntegrity(res.data);
          this.$q.notify({
            type: 'positive',
            message: this.integrityIssues.length
              ? 'Re-checked against Stripe.'
              : 'Re-checked: MemberMatters and Stripe agree about this member.',
          });
        })
        .catch((error) => {
          this.$q.notify({
            type: 'negative',
            message: apiMessage(
              error.response?.data?.message,
              "Couldn't re-check this member."
            ),
          });
        })
        .finally(() => {
          this.recheckingIntegrity = false;
        });
    },
  },
});
</script>
