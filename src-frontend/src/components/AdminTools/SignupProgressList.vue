<template>
  <div style="max-width: 100%">
    <p class="text-grey-7 q-mb-sm">{{ $t('signupProgress.description') }}</p>

    <member-table-shell
      v-model:pagination="pagination"
      :rows="filteredMembers"
      :columns="columns"
      :csv-columns="csvColumns"
      csv-filename="signup-progress-export.csv"
      :loading="loading"
      :grid="grid"
    >
      <template v-slot:filters>
        <q-select
          v-model="stateFilter"
          outlined
          dense
          emit-value
          map-options
          style="min-width: 140px"
          :options="stateFilterOptions"
          :label="$t('adminTools.filterOptions')"
        />

        <q-btn-dropdown
          v-if="steps.length"
          outline
          color="primary"
          :icon="icons.filter"
          :label="stepsFilterLabel"
        >
          <q-list class="q-py-sm">
            <q-item v-for="step in steps" :key="step" class="q-py-md">
              <q-item-section>
                <q-item-label class="text-body1 q-mb-sm">
                  <q-icon :name="stepIcon(step)" class="q-mr-sm" />
                  {{ stepLabel(step) }}
                </q-item-label>
                <!-- Icon sits in the label, not an avatar column, so the
                     buttons get the full menu width on a phone. -->
                <q-btn-toggle
                  :model-value="stepFilters[step] || 'any'"
                  no-caps
                  unelevated
                  class="step-toggle"
                  :padding="$q.screen.xs ? '6px 8px' : '6px 12px'"
                  color="grey-3"
                  text-color="grey-9"
                  toggle-color="primary"
                  toggle-text-color="white"
                  :options="stepFilterOptions(step)"
                  @update:model-value="setStepFilter(step, $event)"
                />
              </q-item-section>
            </q-item>

            <q-separator />

            <q-item
              v-close-popup
              clickable
              :disable="!activeStepFilters.length"
              @click="stepFilters = {}"
            >
              <q-item-section avatar>
                <q-icon :name="icons.close" />
              </q-item-section>
              <q-item-section>
                {{ $t('signupProgress.clearStepFilters') }}
              </q-item-section>
            </q-item>
          </q-list>
        </q-btn-dropdown>
      </template>

      <template v-slot:toolbar-extra>
        <!-- What the table and exports are narrowed to, at a glance. -->
        <div
          v-if="activeStepFilters.length"
          class="row items-center q-gutter-sm q-mb-sm"
        >
          <q-chip
            v-for="[step, state] in activeStepFilters"
            :key="step"
            removable
            class="q-px-md"
            color="primary"
            text-color="white"
            :icon="stepIcon(step)"
            @remove="setStepFilter(step, 'any')"
          >
            {{ stepLabel(step) }}: {{ stepStateLabel(state) }}
          </q-chip>
        </div>
      </template>

      <!-- Step headers are icons, with the name on hover, to keep the table
           narrow. Cards keep the text: they're what phones get, and phones
           can't hover. -->
      <template
        v-for="step in steps"
        :key="step"
        v-slot:[`header-cell-step_${step}`]="props"
      >
        <q-th :props="props">
          <q-icon
            :name="stepIcon(step)"
            size="sm"
            role="img"
            :aria-label="stepLabel(step)"
          />
          <q-tooltip>{{ stepLabel(step) }}</q-tooltip>
        </q-th>
      </template>

      <template v-slot:row="props">
        <q-td key="member" :props="props">
          {{ props.row.name.full || '—' }}
          <span v-if="props.row.screenName" class="text-grey-7">
            ({{ props.row.screenName }})
          </span>
          <div class="text-caption text-grey-7">{{ props.row.email }}</div>
        </q-td>

        <q-td key="state" :props="props">
          <q-badge :color="memberStateColor(props.row.state)">
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
          {{ props.row.lastSeen ? formatDate(props.row.lastSeen) : '—' }}
        </q-td>
      </template>

      <template v-slot:card="props">
        <q-list dense>
          <q-item
            v-for="step in steps"
            :key="step"
            dense
            class="q-px-none step-item"
          >
            <!-- Same step icon as the table header, then the same status
                 icon as the table cell, so the two views read alike. -->
            <q-item-section avatar class="step-icon">
              <q-icon :name="stepIcon(step)" color="grey-8" size="xs" />
            </q-item-section>
            <q-item-section>{{ stepLabel(step) }}</q-item-section>
            <q-item-section side class="text-caption">
              <div class="row items-center no-wrap">
                {{ cardStatusLabel(step, props.row) }}
                <q-icon
                  :name="iconForStep(step, props.row)"
                  :color="colorForStep(step, props.row)"
                  size="xs"
                  class="q-ml-xs"
                />
              </div>
            </q-item-section>
          </q-item>

          <!-- Dates use the same rows with an empty icon slot, so their labels
               line up with the step names and their values with the statuses. -->
          <q-item
            v-for="(date, i) in cardDates(props.row)"
            :key="date.label"
            dense
            class="q-px-none step-item text-caption text-grey-7"
            :class="{ 'q-mt-xs': i === 0 }"
          >
            <q-item-section avatar class="step-icon">
              <!-- Invisible stand-in so the slot is exactly icon-width. -->
              <q-icon :name="icons.calendar" size="xs" class="invisible" />
            </q-item-section>
            <q-item-section>{{ date.label }}</q-item-section>
            <q-item-section side class="text-caption text-grey-7">
              <!-- Same structure as a step status: text, then an icon-sized
                   gap (invisible), so dates end where the status words do. -->
              <div class="row items-center no-wrap">
                {{ date.value }}
                <!-- No date: the same grey dash as an outstanding step, in
                     the same spot, instead of text. -->
                <q-icon
                  :name="date.value ? icons.calendar : icons.minus"
                  color="grey-4"
                  size="xs"
                  class="q-ml-xs"
                  :class="{ invisible: date.value }"
                />
              </div>
            </q-item-section>
          </q-item>
        </q-list>
      </template>
    </member-table-shell>
  </div>
</template>

<script lang="ts">
import { defineComponent } from 'vue';
import { mapGetters } from 'vuex';
import icons from '@icons';
import formatMixin, { formatDate } from '@mixins/formatMixin';
import MemberTableShell from '@components/AdminTools/MemberTableShell.vue';
import { MemberProfile } from 'types/member';
import { memberMatchesQuery } from '../../utils/fuzzySearch';
import { fetchAdminList } from '../../utils/adminFetch';
import { CsvColumn } from '../../utils/memberExport';
import { memberStateColor } from '../../utils/memberStatus';
import {
  enabledSignupSteps,
  matchesStepFilters,
  nextSignupStep,
  signupStepState,
  SignupStep,
  SignupStepFilters,
  SignupStepStateName,
} from '../../utils/signupSteps';

interface SignupRow extends MemberProfile {
  requiredSteps: string[];
}

const STEP_LABEL_KEYS: Record<SignupStep, string> = {
  payment: 'membershipStatusCard.payment',
  terms: 'signup.termsAcceptance',
  induction: 'signup.induction',
  accessCard: 'signup.accessCard',
};

const STEP_STATE_LABEL_KEYS: Record<SignupStepStateName, string> = {
  complete: 'signupProgress.complete',
  pending: 'signupProgress.pending',
  outstanding: 'signupProgress.required',
};

// Noob/inactive members and how far through signup each one is. The search
// query comes from the parent so it can be shared with the members tab.
export default defineComponent({
  name: 'SignupProgressList',
  components: { MemberTableShell },
  mixins: [formatMixin],
  props: {
    grid: {
      type: Boolean,
      default: false,
    },
    search: {
      type: String,
      default: '',
    },
  },
  data() {
    return {
      members: [] as SignupRow[],
      loading: false,
    };
  },
  computed: {
    ...mapGetters('config', ['features']),
    icons() {
      return icons;
    },
    stateFilter: {
      get(): string {
        return this.$store.getters['adminTools/signupState'];
      },
      set(value: string) {
        this.$store.commit('adminTools/setSignupState', value);
      },
    },
    stepFilters: {
      get(): SignupStepFilters {
        return this.$store.getters['adminTools/signupStepFilters'];
      },
      set(value: SignupStepFilters) {
        this.$store.commit('adminTools/setSignupStepFilters', value);
      },
    },
    pagination: {
      get() {
        return this.$store.getters['adminTools/signupPagination'];
      },
      set(value: object) {
        this.$store.commit('adminTools/setSignupPagination', value);
      },
    },
    steps(): SignupStep[] {
      return enabledSignupSteps(this.features);
    },
    // Only filters on enabled steps count; the rest are ignored anyway.
    activeStepFilters(): [SignupStep, SignupStepStateName][] {
      return this.steps
        .filter((step) => this.stepFilters[step])
        .map((step) => [step, this.stepFilters[step] as SignupStepStateName]);
    },
    stepsFilterLabel(): string {
      const label = this.$t('signupProgress.stepsFilter');
      const count = this.activeStepFilters.length;
      return count ? `${label} (${count})` : label;
    },
    stateFilterOptions() {
      return [
        { label: this.$t('adminTools.all'), value: 'all' },
        { label: this.$t('adminTools.new'), value: 'noob' },
        { label: this.$t('adminTools.inactive'), value: 'inactive' },
      ];
    },
    filteredMembers(): SignupRow[] {
      return this.members.filter(
        (member) =>
          (this.stateFilter === 'all' || member.state === this.stateFilter) &&
          matchesStepFilters(
            this.features,
            this.stepFilters,
            member.requiredSteps,
            member.subscriptionStatus
          ) &&
          memberMatchesQuery(member, this.search)
      );
    },
    columns() {
      return [
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
          headerStyle: 'width: 56px',
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
    csvColumns(): CsvColumn<SignupRow>[] {
      return [
        { header: this.$t('tableHeading.name'), value: (m) => m.name.full },
        {
          header: this.$t('tableHeading.screenName'),
          value: (m) => m.screenName,
        },
        { header: this.$t('tableHeading.email'), value: (m) => m.email },
        {
          header: this.$t('tableHeading.status'),
          value: (m) => this.$t(`adminTools.memberStatusString.${m.state}`),
        },
        {
          header: this.$t('tableHeading.subscriptionStatus'),
          value: (m) =>
            this.$t(
              `adminTools.subscriptionStatusString.${m.subscriptionStatus}`
            ),
        },
        ...this.steps.map((step) => ({
          header: this.stepLabel(step),
          value: (m: SignupRow) =>
            this.stepStateLabel(
              signupStepState(step, m.requiredSteps, m.subscriptionStatus)
            ),
        })),
        {
          header: this.$t('adminTools.registrationDate'),
          value: (m) => formatDate(m.registrationDate as unknown as Date),
        },
        {
          header: this.$t('adminTools.lastSeen'),
          value: (m) =>
            m.lastSeen ? formatDate(m.lastSeen as unknown as Date) : '',
        },
      ];
    },
  },
  mounted() {
    this.getMembers();
  },
  methods: {
    memberStateColor,
    async getMembers() {
      this.loading = true;
      this.members = await fetchAdminList<SignupRow>(
        '/api/admin/signup-progress/'
      );
      this.loading = false;
    },
    stepLabel(step: SignupStep): string {
      return this.$t(STEP_LABEL_KEYS[step]);
    },
    stepStateLabel(state: SignupStepStateName): string {
      return this.$t(STEP_STATE_LABEL_KEYS[state]);
    },
    stepIcon(step: SignupStep): string {
      return step === 'payment' ? icons.billing : icons[step];
    },
    // Only payment can be pending.
    stepFilterOptions(step: SignupStep) {
      const states: SignupStepStateName[] =
        step === 'payment'
          ? ['complete', 'pending', 'outstanding']
          : ['complete', 'outstanding'];
      return [
        { label: this.$t('signupProgress.any'), value: 'any' },
        ...states.map((state) => ({
          label: this.stepStateLabel(state),
          value: state,
        })),
      ];
    },
    setStepFilter(step: SignupStep, value: SignupStepStateName | 'any') {
      const filters = { ...this.stepFilters };
      if (value === 'any') delete filters[step];
      else filters[step] = value;
      this.stepFilters = filters;
    },
    nextStepFor(row: SignupRow): SignupStep | null {
      return nextSignupStep(
        this.features,
        row.requiredSteps,
        row.subscriptionStatus
      );
    },
    iconForStep(step: SignupStep, row: SignupRow): string {
      const state = signupStepState(
        step,
        row.requiredSteps,
        row.subscriptionStatus
      );
      if (state === 'complete') return icons.success;
      if (state === 'pending') return icons.clock;
      if (this.nextStepFor(row) === step) return icons.crosshairs;
      return icons.minus;
    },
    colorForStep(step: SignupStep, row: SignupRow): string {
      const state = signupStepState(
        step,
        row.requiredSteps,
        row.subscriptionStatus
      );
      if (state === 'complete') return 'positive';
      if (state === 'pending') return 'warning';
      if (this.nextStepFor(row) === step) return 'blue';
      return 'grey-4';
    },
    // Card text next to the status icon. Plain "Outstanding" is left out:
    // the dash says the same and it's the most common state.
    cardStatusLabel(step: SignupStep, row: SignupRow): string {
      if (
        this.nextStepFor(row) !== step &&
        signupStepState(step, row.requiredSteps, row.subscriptionStatus) ===
          'outstanding'
      ) {
        return '';
      }
      return this.tooltipForStep(step, row);
    },
    cardDates(row: SignupRow): { label: string; value: string | null }[] {
      return [
        {
          label: this.$t('adminTools.registrationDate'),
          value: formatDate(row.registrationDate as unknown as Date, false),
        },
        {
          label: this.$t('adminTools.lastSeen'),
          value: row.lastSeen
            ? formatDate(row.lastSeen as unknown as Date, false)
            : null,
        },
      ];
    },
    tooltipForStep(step: SignupStep, row: SignupRow): string {
      if (this.nextStepFor(row) === step) {
        return this.$t('signupProgress.nextStep');
      }
      return this.stepStateLabel(
        signupStepState(step, row.requiredSteps, row.subscriptionStatus)
      );
    },
  },
});
</script>

<style scoped lang="scss">
// Quasar caps the menu at the space beside the button; wrap rather than
// clip if the options still don't fit.
.step-toggle {
  flex-wrap: wrap;
}

.step-item {
  min-height: 26px;
  // Flush right, so the statuses line up with the dates below. Quasar's dense
  // item padding otherwise wins over q-px-none.
  padding-left: 0;
  padding-right: 0;
}

.step-icon {
  min-width: 28px;
}
</style>
