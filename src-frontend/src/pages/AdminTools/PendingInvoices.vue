<template>
  <q-page class="q-pa-md">
    <div class="text-h5 q-mb-md">{{ $t('pendingInvoices.title') }}</div>
    <p class="text-grey-7 q-mb-md">{{ $t('pendingInvoices.description') }}</p>

    <q-banner
      v-if="!features.enableInvoiceBilling"
      class="bg-warning text-dark q-mb-md"
    >
      {{ $t('pendingInvoices.invoiceDisabledWarning') }}
    </q-banner>

    <q-table
      :rows="invoices"
      :columns="columns"
      row-key="invoiceId"
      :loading="loading"
      :no-data-label="$t('pendingInvoices.noInvoices')"
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
            :label="$t('pendingInvoices.viewInStripe')"
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
            :label="$t('pendingInvoices.markPaid')"
            @click="openMarkPaidDialog(props.row)"
          />
        </q-td>
      </template>
    </q-table>

    <q-dialog v-model="markPaidDialog">
      <q-card style="min-width: 400px; max-width: 500px">
        <q-card-section>
          <div class="text-h6">{{ $t('pendingInvoices.markPaidTitle') }}</div>
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
            {{ $t('pendingInvoices.markPaidHelp') }}
          </p>
          <q-input
            v-model="comment"
            type="textarea"
            rows="3"
            outlined
            :label="$t('pendingInvoices.commentLabel')"
            :placeholder="$t('pendingInvoices.commentPlaceholder')"
            maxlength="500"
            counter
          />
        </q-card-section>

        <q-card-actions align="right">
          <q-btn
            flat
            :label="$t('button.cancel')"
            v-close-popup
            :disable="submitting"
          />
          <q-btn
            color="positive"
            :label="$t('pendingInvoices.confirmMarkPaid')"
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

export default {
  name: 'PendingInvoices',
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
          label: this.$t('pendingInvoices.columnMember'),
          field: 'memberName',
          align: 'left',
          sortable: true,
        },
        {
          name: 'memberEmail',
          label: this.$t('pendingInvoices.columnEmail'),
          field: 'memberEmail',
          align: 'left',
        },
        {
          name: 'planName',
          label: this.$t('pendingInvoices.columnPlan'),
          field: 'planName',
          align: 'left',
        },
        {
          name: 'amount',
          label: this.$t('pendingInvoices.columnAmount'),
          field: 'amountDue',
          align: 'right',
          sortable: true,
        },
        {
          name: 'created',
          label: this.$t('pendingInvoices.columnCreated'),
          field: 'created',
          align: 'left',
          sortable: true,
        },
        {
          name: 'dueDate',
          label: this.$t('pendingInvoices.columnDue'),
          field: 'dueDate',
          align: 'left',
          sortable: true,
        },
        {
          name: 'actions',
          label: this.$t('pendingInvoices.columnActions'),
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
            message: this.$t('pendingInvoices.fetchError'),
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
    formatDate(unixSeconds) {
      return new Date(unixSeconds * 1000).toLocaleDateString();
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
            message: this.$t('pendingInvoices.markPaidSuccess'),
          });
          this.markPaidDialog = false;
          this.fetchInvoices();
        })
        .catch((e) => {
          console.log(e);
          this.$q.notify({
            type: 'negative',
            message:
              e.response?.data?.message ||
              this.$t('pendingInvoices.markPaidError'),
          });
        })
        .finally(() => {
          this.submitting = false;
        });
    },
  },
};
</script>
