<template>
  <div>
    <div class="text-h6 q-pb-sm">
      {{ $t('adminTools.userEvents') }}
    </div>

    <q-table
      :rows="logs.userEventLogs"
      :columns="[
        {
          name: 'logtype',
          label: 'Log Type',
          field: 'logtype',
          sortable: true,
        },
        {
          name: 'description',
          label: 'Description',
          field: 'description',
          sortable: true,
        },
        {
          name: 'date',
          label: 'Date',
          field: 'date',
          sortable: true,
        },
      ]"
      row-key="id"
      :filter="userEventsFilter"
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

      <template v-slot:item="props">
        <div
          class="q-pa-sm col-xs-12 col-sm-6 col-md-4 col-lg-3 grid-style-transition"
        >
          <q-card class="q-py-sm">
            <q-list dense>
              <q-item
                v-for="col in props.cols.filter((col) => col.name !== 'desc')"
                :key="col.name"
              >
                <q-item-section>
                  <q-item-label>{{ col.label }}</q-item-label>
                </q-item-section>
                <q-item-section side>
                  <q-item-label caption>
                    <template v-if="col.name === 'date'">
                      <div>
                        {{ this.formatWhen(col.value) }}
                        <q-tooltip :delay="500">
                          {{ this.formatDate(col.value) }}
                        </q-tooltip>
                      </div>
                    </template>

                    <template v-else>
                      {{ col.value }}
                    </template>
                  </q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </q-card>
        </div>
      </template>

      <template v-slot:body="props">
        <q-tr :props="props">
          <q-td v-for="col in props.cols" :key="col.name" :props="props">
            <template v-if="col.name === 'date'">
              <div>
                {{ this.formatWhen(col.value) }}
                <q-tooltip :delay="500">
                  {{ this.formatDate(col.value) }}
                </q-tooltip>
              </div>
            </template>

            <template v-else>
              {{ col.value }}
            </template>
          </q-td>
        </q-tr>
      </template>
    </q-table>

    <div class="text-h6 q-pb-sm subheading">
      {{ $t('adminTools.userDoorLogs') }}
    </div>

    <q-table
      :rows="logs.doorLogs"
      :columns="[
        {
          name: 'door',
          label: 'Door Name',
          field: 'door',
          sortable: true,
        },
        {
          name: 'success',
          label: 'Swipe Status',
          field: 'success',
          sortable: true,
        },
        {
          name: 'date',
          label: 'Date',
          field: 'date',
          sortable: true,
        },
      ]"
      row-key="id"
      :filter="doorFilter"
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

      <template v-slot:item="props">
        <div
          class="q-pa-sm col-xs-12 col-sm-6 col-md-4 col-lg-3 grid-style-transition"
        >
          <q-card class="q-py-sm">
            <q-list dense>
              <q-item
                v-for="col in props.cols.filter((col) => col.name !== 'desc')"
                :key="col.name"
              >
                <q-item-section>
                  <q-item-label>{{ col.label }}</q-item-label>
                </q-item-section>
                <q-item-section side>
                  <q-item-label caption>
                    <template v-if="col.name === 'date'">
                      <div>
                        {{ this.formatWhen(col.value) }}
                        <q-tooltip :delay="500">
                          {{ this.formatDate(col.value) }}
                        </q-tooltip>
                      </div>
                    </template>

                    <template v-else-if="col.name === 'success'">
                      <div
                        :class="col.value ? 'text-positive' : 'text-negative'"
                      >
                        {{ $t(col.value ? 'success' : 'rejected') }}
                      </div>
                    </template>

                    <template v-else>
                      {{ col.value }}
                    </template>
                  </q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </q-card>
        </div>
      </template>

      <template v-slot:body="props">
        <q-tr :props="props">
          <q-td v-for="col in props.cols" :key="col.name" :props="props">
            <template v-if="col.name === 'date'">
              <div>
                {{ this.formatWhen(col.value) }}
                <q-tooltip :delay="500">
                  {{ this.formatDate(col.value) }}
                </q-tooltip>
              </div>
            </template>

            <template v-else-if="col.name === 'success'">
              <div :class="col.value ? 'text-positive' : 'text-negative'">
                {{ $t(col.value ? 'success' : 'rejected') }}
              </div>
            </template>

            <template v-else>
              {{ col.value }}
            </template>
          </q-td>
        </q-tr>
      </template>
    </q-table>

    <div class="text-h6 q-pb-sm subheading">
      {{ $t('adminTools.userInterlockLogs') }}
    </div>

    <q-table
      :rows="logs.interlockLogs"
      :columns="[
        {
          name: 'interlock',
          label: 'Interlock',
          field: 'interlockName',
          sortable: true,
        },
        {
          name: 'dateStarted',
          label: 'Date',
          field: 'dateStarted',
          sortable: true,
        },
        {
          name: 'totalTime',
          label: 'Total Time',
          field: 'totalTime',
          sortable: true,
          sort: sortByFloat,
        },
        {
          name: 'totalCost',
          label: 'Total Cost',
          field: 'totalCost',
          sortable: true,
          sort: sortByFloat,
          format: (val) => $n(val || 0, 'currency', siteLocaleCurrency),
        },
        {
          name: 'userEnded',
          label: 'Swiped Off By',
          field: 'userEnded',
          sortable: true,
        },
        {
          name: 'status',
          label: 'Status',
          field: 'status',
          sortable: true,
        },
      ]"
      row-key="id"
      :filter="doorFilter"
      :pagination="{
        ...pagination,
        sortBy: 'dateStarted',
      }"
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

      <template v-slot:item="props">
        <div
          class="q-pa-sm col-xs-12 col-sm-6 col-md-4 col-lg-3 grid-style-transition"
        >
          <q-card class="q-py-sm">
            <q-list dense>
              <q-item
                v-for="col in props.cols.filter((col) => col.name !== 'desc')"
                :key="col.name"
              >
                <q-item-section>
                  <q-item-label>{{ col.label }}</q-item-label>
                </q-item-section>
                <q-item-section side>
                  <q-item-label caption>
                    <template v-if="col.name === 'dateStarted'">
                      <div>
                        {{ this.formatWhen(col.value) }}
                        <q-tooltip :delay="500">
                          {{ this.formatDate(col.value) }}
                        </q-tooltip>
                      </div>
                    </template>

                    <template v-else-if="col.name === 'totalTime'">
                      <div v-if="col.value > 1">
                        {{ this.humanizeDurationOfSeconds(col.value) }}
                        <q-tooltip :delay="500">
                          {{ this.humanizeDurationOfSecondsPrecise(col.value) }}
                        </q-tooltip>
                      </div>
                      <div v-else></div>
                    </template>

                    <template v-else-if="col.name === 'status'">
                      <div class="text-negative" v-if="col.value === -1">
                        {{ $t('rejected') }}
                      </div>
                      <div class="text-positive" v-else-if="col.value === 1">
                        {{ $t('interlocks.finished') }}
                      </div>
                      <div class="text-warning" v-else>
                        {{ $t('interlocks.inProgress') }}
                        <q-spinner-dots></q-spinner-dots>
                      </div>
                    </template>

                    <template v-else>
                      {{ col.value }}
                    </template>
                  </q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </q-card>
        </div>
      </template>

      <template v-slot:body="props">
        <q-tr :props="props">
          <q-td v-for="col in props.cols" :key="col.name" :props="props">
            <template v-if="col.name === 'dateStarted'">
              <div>
                {{ this.formatWhen(col.value) }}
                <q-tooltip :delay="500">
                  {{ this.formatDate(col.value) }}
                </q-tooltip>
              </div>
            </template>

            <template v-else-if="col.name === 'totalTime'">
              <div v-if="col.value > 1">
                {{ this.humanizeDurationOfSeconds(col.value) }}
                <q-tooltip :delay="500">
                  {{ this.humanizeDurationOfSecondsPrecise(col.value) }}
                </q-tooltip>
              </div>
              <div v-else></div>
            </template>

            <template v-else-if="col.name === 'status'">
              <div class="text-negative" v-if="col.value === -1">
                {{ $t('rejected') }}
              </div>
              <div class="text-positive" v-else-if="col.value === 1">
                {{ $t('interlocks.finished') }}
              </div>
              <div class="text-warning" v-else>
                {{ $t('interlocks.inProgress') }}
                <q-spinner-dots></q-spinner-dots>
              </div>
            </template>

            <template v-else>
              {{ col.value }}
            </template>
          </q-td>
        </q-tr>
      </template>
    </q-table>
  </div>
</template>

<script lang="ts">
import formatMixin from '@mixins/formatMixin';
import icons from '@icons';
import { mapGetters } from 'vuex';
import { defineComponent } from 'vue';

export default defineComponent({
  name: 'MemberLogsTab',
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
      logs: {
        userEventLogs: [],
        doorLogs: [],
        interlockLogs: [],
      },
      filter: '',
      userEventsFilter: '',
      doorFilter: '',
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
      this.getMemberLogs();
    },
  },
  mounted() {
    if (this.memberId) this.getMemberLogs();
  },
  methods: {
    getMemberLogs() {
      this.$axios
        .get(`/api/admin/members/${this.memberId}/logs/`)
        .catch(() => {
          this.$q.dialog({
            title: this.$t('error.error'),
            message: this.$t('error.requestFailed'),
          });
        })
        .then((res) => {
          if (!res) return;
          this.logs = res.data;
        })
        .finally(() => {
          this.$emit('memberUpdated');
        });
    },
  },
});
</script>
