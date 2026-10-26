<template>
  <q-table
    :rows="rows"
    :columns="columns"
    :no-data-label="$t('adminTools.noMembers')"
    row-key="id"
    :pagination="pagination"
    :loading="loading"
    :grid="grid"
    class="full-width"
    @update:pagination="$emit('update:pagination', $event)"
    @row-click="(evt, row) => goToMember(row)"
  >
    <template v-slot:top>
      <div class="full-width">
        <div class="row items-start justify-between">
          <div class="row items-center q-gutter-sm q-mb-sm">
            <slot name="filters" />
            <card-sort-control
              v-if="grid"
              :pagination="pagination"
              :columns="columns"
              @update:pagination="$emit('update:pagination', $event)"
            />
          </div>

          <member-export-buttons
            :members="rows"
            :csv-columns="csvColumns"
            :filename="csvFilename"
          />
        </div>

        <slot name="toolbar-extra" />
      </div>
    </template>

    <!-- A list that needs full control of its rows provides `row`; the
         default rendering (plus any body-cell-* overrides) is used otherwise. -->
    <template v-if="$slots.row" v-slot:body="props">
      <q-tr
        :props="props"
        class="cursor-pointer"
        @click="goToMember(props.row)"
      >
        <slot name="row" v-bind="props" />
      </q-tr>
    </template>

    <!-- body-cell-* / header-cell-* overrides, passed straight to QTable. -->
    <template v-for="name in cellSlotNames" :key="name" v-slot:[name]="props">
      <slot :name="name" v-bind="props" />
    </template>

    <template v-slot:item="props">
      <div class="q-pa-xs col-xs-12 col-sm-6 col-md-4 col-lg-3">
        <member-summary-card :member="props.row" @click="goToMember(props.row)">
          <template v-if="$slots.card" #default>
            <slot name="card" v-bind="props" />
          </template>
        </member-summary-card>
      </div>
    </template>
  </q-table>
</template>

<script lang="ts">
import { defineComponent, PropType } from 'vue';
import CardSortControl from '@components/AdminTools/CardSortControl.vue';
import MemberExportButtons from '@components/AdminTools/MemberExportButtons.vue';
import MemberSummaryCard from '@components/AdminTools/MemberSummaryCard.vue';
import { MemberProfile } from 'types/member';
import { CsvColumn } from '../../utils/memberExport';

// The table, toolbar, card grid, sorting and export shared by the tabs of the
// admin members page. Each tab supplies its rows (already filtered), columns
// and the parts that are its own: filters, row/cell content and card body.
export default defineComponent({
  name: 'MemberTableShell',
  components: { CardSortControl, MemberExportButtons, MemberSummaryCard },
  props: {
    rows: {
      type: Array as PropType<MemberProfile[]>,
      required: true,
    },
    columns: {
      type: Array as PropType<
        { name: string; label: string; sortable?: boolean }[]
      >,
      required: true,
    },
    csvColumns: {
      type: Array as PropType<CsvColumn<MemberProfile>[]>,
      required: true,
    },
    csvFilename: {
      type: String,
      default: 'member-export.csv',
    },
    pagination: {
      type: Object,
      required: true,
    },
    loading: {
      type: Boolean,
      default: false,
    },
    grid: {
      type: Boolean,
      default: false,
    },
  },
  emits: ['update:pagination'],
  computed: {
    cellSlotNames(): string[] {
      return Object.keys(this.$slots).filter(
        (name) =>
          name.startsWith('body-cell-') || name.startsWith('header-cell-')
      );
    },
  },
  methods: {
    goToMember(member: MemberProfile) {
      this.$router.push({
        name: 'manageMember',
        params: { memberId: member.id },
      });
    },
  },
});
</script>
