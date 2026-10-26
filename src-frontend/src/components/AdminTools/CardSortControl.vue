<template>
  <div class="row items-center no-wrap">
    <q-select
      :model-value="pagination.sortBy || null"
      outlined
      dense
      emit-value
      map-options
      clearable
      :clear-icon="icons.close"
      style="min-width: 160px"
      :options="options"
      :label="$t('adminTools.sortBy')"
      @update:model-value="setSortBy"
    />
    <q-btn
      flat
      round
      color="primary"
      class="q-ml-xs"
      :disable="!pagination.sortBy"
      :icon="pagination.descending ? icons.sortDescending : icons.sortAscending"
      :aria-label="directionLabel"
      @click="update({ descending: !pagination.descending })"
    >
      <q-tooltip>{{ directionLabel }}</q-tooltip>
    </q-btn>
  </div>
</template>

<script lang="ts">
import { defineComponent, PropType } from 'vue';
import icons from '@icons';

interface SortableColumn {
  name: string;
  label: string;
  sortable?: boolean;
}

interface Pagination {
  sortBy: string | null;
  descending: boolean;
  page?: number;
}

// QTable hides its column headers in grid mode, and with them the only way to
// sort. This drives the same pagination.sortBy / descending the headers do, so
// a sort chosen in either view carries over to the other.
export default defineComponent({
  name: 'CardSortControl',
  props: {
    columns: {
      type: Array as PropType<SortableColumn[]>,
      required: true,
    },
    pagination: {
      type: Object as PropType<Pagination>,
      required: true,
    },
  },
  emits: ['update:pagination'],
  computed: {
    icons() {
      return icons;
    },
    options() {
      return this.columns
        .filter((column) => column.sortable)
        .map((column) => ({ label: column.label, value: column.name }));
    },
    directionLabel(): string {
      return this.pagination.descending
        ? this.$t('adminTools.sortDescending')
        : this.$t('adminTools.sortAscending');
    },
  },
  methods: {
    update(changes: Partial<Pagination>) {
      this.$emit('update:pagination', { ...this.pagination, ...changes });
    },
    setSortBy(sortBy: string | null) {
      this.update({ sortBy, page: 1 });
    },
  },
});
</script>
