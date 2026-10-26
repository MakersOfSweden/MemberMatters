<template>
  <div class="row items-start">
    <q-btn-dropdown
      v-if="$q.screen.lt.md"
      class="q-mb-sm"
      color="primary"
      :icon="icons.export"
      :label="$t('adminTools.exportOptions')"
    >
      <q-list>
        <q-item v-close-popup clickable @click="exportCsv">
          <q-item-section>
            <q-item-label>{{ $t('adminTools.exportCsv') }}</q-item-label>
          </q-item-section>
        </q-item>

        <q-item v-close-popup clickable @click="copyEmailsToClipboard">
          <q-item-section>
            <q-item-label>{{ $t('adminTools.emailAddresses') }}</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-btn-dropdown>

    <template v-else>
      <q-btn
        class="q-mr-sm q-mb-sm"
        color="primary"
        :icon="icons.export"
        :label="$t('adminTools.exportCsv')"
        @click="exportCsv"
      />
      <q-btn
        class="q-mb-sm"
        color="primary"
        :icon="icons.email"
        :label="$t('adminTools.emailAddresses')"
        @click="copyEmailsToClipboard"
      />
    </template>
  </div>
</template>

<script lang="ts">
import { defineComponent, PropType } from 'vue';
import { copyToClipboard, exportFile } from 'quasar';
import icons from '@icons';
import { MemberProfile } from 'types/member';
import {
  CsvColumn,
  emailExportMembers,
  memberEmailList,
  toCsv,
} from '../../utils/memberExport';

// Export CSV / Copy Email List for whatever rows the parent list is showing.
export default defineComponent({
  name: 'MemberExportButtons',
  props: {
    members: {
      type: Array as PropType<MemberProfile[]>,
      required: true,
    },
    csvColumns: {
      type: Array as PropType<CsvColumn<MemberProfile>[]>,
      required: true,
    },
    filename: {
      type: String,
      default: 'member-export.csv',
    },
  },
  computed: {
    icons() {
      return icons;
    },
  },
  methods: {
    exportCsv() {
      const status = exportFile(
        this.filename,
        toCsv(this.members, this.csvColumns),
        'text/csv'
      );

      if (status !== true) {
        this.$q.notify({
          message: this.$t('error.downloadFailed'),
          color: 'negative',
          icon: 'warning',
        });
      }
    },
    copyEmailsToClipboard() {
      copyToClipboard(memberEmailList(this.members))
        .then(() => {
          this.$q.dialog({
            dark: true,
            title: this.$t(
              'adminTools.copyEmailListSuccess',
              this.members.length
            ),
            message: this.$t(
              'adminTools.copyEmailListSuccessDescription',
              this.members.length - emailExportMembers(this.members).length
            ),
          });
        })
        .catch(() => {
          this.$q.dialog({
            dark: true,
            title: this.$t('error.copyToClipboard'),
            message: this.$t('error.copyToClipboardDescription'),
          });
        });
    },
  },
});
</script>
