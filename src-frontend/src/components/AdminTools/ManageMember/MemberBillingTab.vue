<template>
  <div class="column flex content-start items-start q-gutter-y-lg">
    <div class="column q-gutter-y-sm full-width">
      <div class="text-h6">
        {{ $t('adminTools.subscriptionInfo') }}
      </div>

      <q-markup-table
        v-if="billing?.subscription"
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
              {{ $t(`adminTools.billingCycleAnchor`) }}
            </th>
            <th class="text-left">{{ $t(`adminTools.startDate`) }}</th>
            <th class="text-left">
              {{ $t(`adminTools.currentPeriodEnd`) }}
            </th>
            <template v-if="billing.subscription.cancelAt">
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
                    planId: billing.subscription.membershipPlan.id,
                  },
                }"
                >{{ billing.subscription.membershipTier.name }}</router-link
              >
            </td>
            <td class="text-left">
              {{
                $t('paymentPlans.intervalDescription', {
                  currency:
                    billing.subscription.membershipPlan.currency.toUpperCase(),
                  amount: $n(
                    billing.subscription.membershipPlan.cost / 100,
                    'currency',
                    siteLocaleCurrency
                  ),
                  interval: $tc(
                    `paymentPlans.interval.${billing.subscription.membershipPlan.interval.toLowerCase()}`,
                    billing.subscription.membershipPlan.intervalAmount
                  ),
                })
              }}
            </td>
            <td class="text-left">
              {{ formatDate(billing.subscription.billingCycleAnchor) }}
            </td>
            <td class="text-left">
              {{ formatDate(billing.subscription.startDate) }}
            </td>
            <td class="text-left">
              {{ formatDate(billing.subscription.currentPeriodEnd) }}
            </td>
            <template v-if="billing.subscription.cancelAt">
              <td class="text-left">
                {{ formatDate(billing.subscription.cancelAt) }}
              </td>
              <td class="text-left">
                {{ formatBooleanYesNo(billing.subscription.cancelAtPeriodEnd) }}
              </td>
            </template>
          </tr>
        </tbody>
      </q-markup-table>

      <q-list
        v-if="billing?.subscription"
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
                inactive: billing.subscription.status === 'inactive',
                active: billing.subscription.status === 'active',
                cancelling: billing.subscription.status === 'cancelling',
              }"
            >
              {{
                $t(
                  `adminTools.subscriptionStatusString.${billing.subscription.status}`
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
              {{ formatDate(billing.subscription.billingCycleAnchor) }}
            </q-item-label>
            <q-item-label caption>
              {{ $t(`adminTools.billingCycleAnchor`) }}
            </q-item-label>
          </q-item-section>
        </q-item>

        <q-item>
          <q-item-section>
            <q-item-label lines="1">
              {{ formatDate(billing.subscription.startDate) }}
            </q-item-label>
            <q-item-label caption>
              {{ $t(`adminTools.startDate`) }}
            </q-item-label>
          </q-item-section>
        </q-item>

        <q-item>
          <q-item-section>
            <q-item-label lines="1">
              {{ formatDate(billing.subscription.currentPeriodEnd) }}
            </q-item-label>
            <q-item-label caption>
              {{ $t(`adminTools.currentPeriodEnd`) }}
            </q-item-label>
          </q-item-section>
        </q-item>

        <q-item v-if="billing.subscription.cancelAt">
          <q-item-section>
            <q-item-label lines="1">
              {{ formatDate(billing.subscription.cancelAt) }}
            </q-item-label>
            <q-item-label caption>
              {{ $t(`adminTools.cancelAt`) }}
            </q-item-label>
          </q-item-section>
        </q-item>

        <q-item v-if="billing.subscription.cancelAtPeriodEnd">
          <q-item-section>
            <q-item-label lines="1">
              {{ billing.subscription.cancelAtPeriodEnd }}
            </q-item-label>
            <q-item-label caption>
              {{ $t(`adminTools.cancelAtPeriodEnd`) }}
            </q-item-label>
          </q-item-section>
        </q-item>
      </q-list>

      <div v-else>
        {{ $t(`adminTools.noSubscription`) }}
      </div>
    </div>

    <div class="column q-gutter-y-sm full-width">
      <div class="text-h6">
        {{ $t('adminTools.billingInfo') }}
      </div>

      <q-markup-table
        v-if="billing?.subscription"
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
  </div>
</template>

<script lang="ts">
import formatMixin from '@mixins/formatMixin';
import icons from '@icons';
import { mapGetters } from 'vuex';
import { MemberBillingInfo } from 'types/member';
import { defineComponent } from 'vue';

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
      filter: '',
      loading: false,
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
  },
  watch: {
    memberId() {
      this.getMemberBilling();
    },
  },
  mounted() {
    if (this.memberId) this.getMemberBilling();
  },
  methods: {
    getMemberBilling() {
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
          if (this.billing && !this.billing?.subscription)
            this.billing.subscription = null;
        })
        .finally(() => {
          this.$emit('memberUpdated');
        });
    },
  },
});
</script>
