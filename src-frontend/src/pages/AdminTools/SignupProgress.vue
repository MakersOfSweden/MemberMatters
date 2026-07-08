<template>
  <q-page class="q-pa-md">
    <div class="text-h5 q-mb-xs">{{ $t('menuLink.signupProgress') }}</div>
    <p class="text-grey-7">{{ $t('signupProgress.description') }}</p>

    <q-table
      :rows="displayMembers"
      :columns="columns"
      :no-data-label="$t('adminTools.noMembers')"
      row-key="id"
      :filter="filter"
      v-model:pagination="pagination"
      :loading="loading"
      class="full-width"
      @row-click="(evt, row) => goToMember(row)"
    >
      <template v-slot:top-left>
        <q-select
          v-model="stateFilter"
          outlined
          dense
          emit-value
          map-options
          class="q-mr-sm"
          style="min-width: 140px"
          :options="stateFilterOptions"
          :label="$t('adminTools.filterOptions')"
        />
      </template>

      <template v-slot:top-right>
        <q-input
          v-model="filter"
          outlined
          dense
          debounce="300"
          placeholder="Search"
        >
          <template v-slot:append>
            <q-icon :name="icons.search" />
          </template>
        </q-input>
      </template>

      <template v-slot:body="props">
        <q-tr
          :props="props"
          class="cursor-pointer"
          @click="goToMember(props.row)"
        >
          <q-td key="nextStep" :props="props">
            <q-chip
              v-if="nextStepFor(props.row)"
              color="blue"
              text-color="white"
              dense
            >
              {{ stepLabel(nextStepFor(props.row)) }}
            </q-chip>
            <span v-else class="text-grey-5">—</span>
          </q-td>

          <q-td key="member" :props="props">
            {{ props.row.name.full || $t('error.noValue') }}
            <span v-if="props.row.screenName" class="text-grey-7">
              ({{ props.row.screenName }})
            </span>
            <div class="text-caption text-grey-7">{{ props.row.email }}</div>
          </q-td>

          <q-td key="state" :props="props">
            <q-badge :color="stateColor(props.row.state)">
              {{ $t(`adminTools.memberStatusString.${props.row.state}`) }}
            </q-badge>
          </q-td>

          <q-td
            v-for="step in steps"
            :key="`step_${step}`"
            :props="props"
            class="text-center"
          >
            <q-icon
              :name="iconForStep(step, props.row)"
              :color="colorForStep(step, props.row)"
              size="sm"
            >
              <q-tooltip>{{ tooltipForStep(step, props.row) }}</q-tooltip>
            </q-icon>
          </q-td>

          <q-td key="registered" :props="props">
            {{ formatDate(props.row.registrationDate) }}
          </q-td>

          <q-td key="lastSeen" :props="props">
            {{
              props.row.lastSeen
                ? formatDate(props.row.lastSeen)
                : $t('error.noValue')
            }}
          </q-td>
        </q-tr>
      </template>
    </q-table>
  </q-page>
</template>

<script lang="ts">
import { defineComponent } from 'vue';
import { mapGetters } from 'vuex';
import icons from '@icons';
import formatMixin from '@mixins/formatMixin';
import { MemberProfile } from 'types/member';
import {
  enabledSignupSteps,
  signupStepStatus,
  nextSignupStep,
  SignupStep,
} from '../../utils/signupSteps';

interface SignupRow extends MemberProfile {
  requiredSteps: string[];
  signupStage: string;
}

export default defineComponent({
  name: 'SignupProgress',
  mixins: [formatMixin],
  data() {
    return {
      members: [] as SignupRow[],
      loading: false,
      filter: '',
      stateFilter: 'all',
      pagination: {
        sortBy: 'registered',
        descending: false,
        rowsPerPage: 15,
      },
    };
  },
  computed: {
    ...mapGetters('config', ['features']),
    icons() {
      return icons;
    },
    steps(): SignupStep[] {
      return enabledSignupSteps(this.features);
    },
    stateFilterOptions() {
      return [
        { label: this.$t('adminTools.all'), value: 'all' },
        { label: this.$t('adminTools.new'), value: 'noob' },
        { label: this.$t('adminTools.inactive'), value: 'inactive' },
      ];
    },
    columns() {
      return [
        {
          name: 'nextStep',
          label: this.$t('signupProgress.nextStep'),
          align: 'left' as const,
          sortable: false,
        },
        {
          name: 'member',
          label: this.$t('tableHeading.name'),
          field: (row: SignupRow) =>
            `${row.name.full} ${row.screenName} ${row.email}`,
          align: 'left' as const,
          sortable: true,
        },
        {
          name: 'state',
          label: this.$t('tableHeading.status'),
          field: 'state',
          align: 'left' as const,
          sortable: true,
        },
        ...this.steps.map((step) => ({
          name: `step_${step}`,
          label: this.stepLabel(step),
          field: step,
          align: 'center' as const,
          sortable: false,
        })),
        {
          name: 'registered',
          label: this.$t('adminTools.registrationDate'),
          field: 'registrationDate',
          align: 'left' as const,
          sortable: true,
        },
        {
          name: 'lastSeen',
          label: this.$t('adminTools.lastSeen'),
          field: 'lastSeen',
          align: 'left' as const,
          sortable: true,
        },
      ];
    },
    displayMembers(): SignupRow[] {
      if (this.stateFilter === 'all') return this.members;
      return this.members.filter((m) => m.state === this.stateFilter);
    },
  },
  mounted() {
    this.getMembers();
  },
  methods: {
    getMembers() {
      this.loading = true;
      this.$axios
        .get('/api/admin/signup-progress/')
        .then((response) => {
          this.members = response.data;
        })
        .catch(() => {
          this.$q.dialog({
            title: this.$t('error.error'),
            message: this.$t('error.requestFailed'),
          });
        })
        .finally(() => {
          this.loading = false;
        });
    },
    goToMember(row: SignupRow) {
      this.$router.push({ name: 'manageMember', params: { memberId: row.id } });
    },
    stepLabel(step: SignupStep | null): string {
      if (!step) return '';
      const keys: Record<SignupStep, string> = {
        payment: 'membershipStatusCard.payment',
        terms: 'signup.termsAcceptance',
        induction: 'signup.induction',
        accessCard: 'signup.accessCard',
      };
      return this.$t(keys[step]);
    },
    nextStepFor(row: SignupRow): SignupStep | null {
      return nextSignupStep(
        this.features,
        row.requiredSteps,
        row.subscriptionStatus
      );
    },
    iconForStep(step: SignupStep, row: SignupRow): string {
      const status = signupStepStatus(
        step,
        row.requiredSteps,
        row.subscriptionStatus
      );
      if (status.complete) return icons.success;
      if (status.pending) return icons.clock;
      if (this.nextStepFor(row) === step) return icons.crosshairs;
      return icons.minus;
    },
    colorForStep(step: SignupStep, row: SignupRow): string {
      const status = signupStepStatus(
        step,
        row.requiredSteps,
        row.subscriptionStatus
      );
      if (status.complete) return 'positive';
      if (status.pending) return 'warning';
      if (this.nextStepFor(row) === step) return 'blue';
      return 'grey-4';
    },
    tooltipForStep(step: SignupStep, row: SignupRow): string {
      const status = signupStepStatus(
        step,
        row.requiredSteps,
        row.subscriptionStatus
      );
      if (status.complete) return this.$t('signupProgress.complete');
      if (status.pending) return this.$t('signupProgress.pending');
      return this.$t('signupProgress.required');
    },
    stateColor(state: string): string {
      const colors: Record<string, string> = {
        noob: 'orange',
        inactive: 'yellow-8',
      };
      return colors[state] || 'grey-7';
    },
  },
});
</script>
