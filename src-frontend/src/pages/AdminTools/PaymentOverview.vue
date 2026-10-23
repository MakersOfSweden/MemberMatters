<template>
  <q-page class="q-pa-md">
    <div class="text-h5 q-mb-lg">Payment Overview</div>

    <div class="row q-col-gutter-md q-mb-lg">
      <div class="col-12 col-lg-6">
        <payment-check-card
          title="Stripe"
          :icon="icons.billing"
          checks-url="/api/admin/billing/stripe/checks/"
          test-url="/api/admin/billing/stripe/connection-test/"
        />
      </div>
    </div>

    <div class="text-h6 q-mb-md">
      <q-icon :name="icons.pendingInvoices" class="q-mr-sm" />
      Stripe Subscription Invoices
    </div>

    <q-banner
      v-if="!features.enableInvoiceBilling"
      class="bg-warning text-dark q-mb-md"
    >
      Invoice billing is currently disabled, so new members cannot sign up via
      invoice. Existing invoice subscriptions are still being billed by Stripe —
      use this page to record off-Stripe payments for those members.
    </q-banner>

    <q-table
      :rows="invoices"
      :columns="columns"
      row-key="invoiceId"
      :loading="loading"
      no-data-label="No pending invoices."
      flat
      bordered
    >
      <template v-slot:body-cell-amount="props">
        <q-td :props="props">
          {{ formatAmount(props.row.amountDue, props.row.currency) }}
        </q-td>
      </template>

      <template v-slot:body-cell-created="props">
        <q-td :props="props">
          {{ formatDate(props.row.created) }}
        </q-td>
      </template>

      <template v-slot:body-cell-dueDate="props">
        <q-td :props="props">
          {{ props.row.dueDate ? formatDate(props.row.dueDate) : '—' }}
        </q-td>
      </template>

      <template v-slot:body-cell-actions="props">
        <q-td :props="props">
          <q-btn
            flat
            dense
            color="primary"
            :icon="icons.billing"
            label="View in Stripe"
            type="a"
            :href="props.row.hostedInvoiceUrl"
            target="_blank"
            rel="noopener"
            class="q-mr-sm"
          />
          <q-btn
            dense
            color="positive"
            :icon="icons.success"
            label="Mark as Paid"
            @click="openMarkPaidDialog(props.row)"
          />
        </q-td>
      </template>
    </q-table>

    <q-dialog v-model="markPaidDialog">
      <q-card style="min-width: 400px; max-width: 500px">
        <q-card-section>
          <div class="text-h6">Mark Invoice as Paid</div>
        </q-card-section>

        <q-card-section v-if="selectedInvoice" class="q-pt-none">
          <div class="q-mb-sm">
            <strong>{{ selectedInvoice.memberName }}</strong>
            —
            {{
              formatAmount(selectedInvoice.amountDue, selectedInvoice.currency)
            }}
          </div>
          <p class="text-caption text-grey-7 q-mb-md">
            This marks the invoice as paid out-of-band in Stripe (no card
            charge). The subscription will activate via the paid webhook. Add an
            optional note for the audit trail.
          </p>
          <q-input
            v-model="comment"
            type="textarea"
            rows="3"
            outlined
            label="Comment (optional)"
            placeholder="e.g. Paid by bank transfer on 2026-04-10"
            maxlength="500"
            counter
          />
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat label="Cancel" v-close-popup :disable="submitting" />
          <q-btn
            color="positive"
            label="Mark as Paid"
            :loading="submitting"
            @click="confirmMarkPaid"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script>
import icons from '@icons';
import { mapGetters } from 'vuex';
import PaymentCheckCard from '@components/AdminTools/PaymentCheckCard.vue';

export default {
  name: 'PaymentOverview',
  components: { PaymentCheckCard },
  data() {
    return {
      invoices: [],
      loading: false,
      markPaidDialog: false,
      selectedInvoice: null,
      comment: '',
      submitting: false,
    };
  },
  computed: {
    ...mapGetters('config', ['features']),
    icons() {
      return icons;
    },
    columns() {
      return [
        {
          name: 'memberName',
          label: 'Member',
          field: 'memberName',
          align: 'left',
          sortable: true,
        },
        {
          name: 'memberEmail',
          label: 'Email',
          field: 'memberEmail',
          align: 'left',
        },
        {
          name: 'planName',
          label: 'Plan',
          field: 'planName',
          align: 'left',
        },
        {
          name: 'amount',
          label: 'Amount Due',
          field: 'amountDue',
          align: 'right',
          sortable: true,
        },
        {
          name: 'created',
          label: 'Created',
          field: 'created',
          align: 'left',
          sortable: true,
        },
        {
          name: 'dueDate',
          label: 'Due',
          field: 'dueDate',
          align: 'left',
          sortable: true,
        },
        {
          name: 'actions',
          label: 'Actions',
          field: 'actions',
          align: 'right',
        },
      ];
    },
  },
  mounted() {
    this.fetchInvoices();
  },
  methods: {
    fetchInvoices() {
      this.loading = true;
      this.$axios
        .get('/api/admin/billing/pending-invoices/')
        .then((response) => {
          this.invoices = response.data;
        })
        .catch((e) => {
          console.log(e);
          this.$q.notify({
            type: 'negative',
            message: 'Failed to load pending invoices.',
          });
        })
        .finally(() => {
          this.loading = false;
        });
    },
    formatAmount(cents, currency) {
      return new Intl.NumberFormat(undefined, {
        style: 'currency',
        currency: (currency || 'aud').toUpperCase(),
      }).format((cents || 0) / 100);
    },
    formatDate(isoDate) {
      return new Date(isoDate).toLocaleDateString();
    },
    openMarkPaidDialog(row) {
      this.selectedInvoice = row;
      this.comment = '';
      this.markPaidDialog = true;
    },
    confirmMarkPaid() {
      if (!this.selectedInvoice) return;
      this.submitting = true;
      this.$axios
        .post(
          `/api/admin/billing/invoices/${this.selectedInvoice.invoiceId}/mark-paid/`,
          { comment: this.comment }
        )
        .then(() => {
          this.$q.notify({
            type: 'positive',
            message: 'Invoice marked as paid.',
          });
          this.markPaidDialog = false;
          this.fetchInvoices();
        })
        .catch((e) => {
          console.log(e);
          this.$q.notify({
            type: 'negative',
            message:
              e.response?.data?.message || 'Failed to mark invoice as paid.',
          });
        })
        .finally(() => {
          this.submitting = false;
        });
    },
  },
};
</script>
