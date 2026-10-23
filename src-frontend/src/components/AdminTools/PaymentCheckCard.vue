<template>
  <q-card flat bordered>
    <q-card-section class="row items-center q-gutter-sm">
      <q-icon :name="icon" size="sm" />
      <div class="text-h6 col">{{ title }}</div>
      <q-btn
        unelevated
        color="primary"
        :icon="icons.sync"
        label="Test connection"
        :loading="testing"
        :disable="!canTest"
        @click="runTest"
      />
    </q-card-section>
    <q-separator />

    <div v-if="loading" class="q-pa-lg text-center">
      <q-spinner size="2em" />
    </div>
    <q-banner v-else-if="loadError" class="text-negative">
      Could not load the checks.
    </q-banner>
    <template v-else>
      <template v-for="section in sections" :key="section.key">
        <q-separator v-if="section.title" />
        <q-card-section v-if="section.title" class="text-subtitle2 q-pb-none">
          {{ section.title }}
        </q-card-section>
        <q-banner v-if="section.error" class="text-negative">
          {{ section.error }}
        </q-banner>
        <q-list separator>
          <q-item v-for="check in section.checks" :key="check.key">
            <q-item-section avatar>
              <q-icon
                :name="statusIcons[check.status].icon"
                :color="statusIcons[check.status].color"
              />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ check.label }}</q-item-label>
              <!-- On phones the value sits under the label instead of beside it. -->
              <q-item-label class="xs check-value text-grey-8">
                {{ check.value }}
              </q-item-label>
              <q-item-label v-if="check.detail" caption>
                {{ check.detail }}
              </q-item-label>
              <q-item-label v-if="check.items.length" caption>
                <ul class="check-items">
                  <li v-for="item in check.items" :key="item">{{ item }}</li>
                </ul>
              </q-item-label>
            </q-item-section>
            <q-item-section side class="gt-xs check-value check-value--side">
              {{ check.value }}
            </q-item-section>
          </q-item>
        </q-list>
      </template>
    </template>
  </q-card>
</template>

<script lang="ts">
import { defineComponent } from 'vue';
import type { AxiosError } from 'axios';
import { api } from 'boot/axios';
import icons from '@icons';

type CheckStatus = 'ok' | 'warning' | 'error' | 'info' | 'unknown';

interface Check {
  key: string;
  label: string;
  status: CheckStatus;
  value: string;
  detail: string;
  items: string[];
}

interface Section {
  key: string;
  title?: string;
  checks: Check[];
  error?: string;
}

// One payment method's checks: the ones that only read MemberMatters' settings
// load with the page, and the button runs the ones that call the provider.
export default defineComponent({
  name: 'PaymentCheckCard',
  props: {
    title: { type: String, required: true },
    icon: { type: String, required: true },
    checksUrl: { type: String, required: true },
    testUrl: { type: String, required: true },
  },
  data() {
    return {
      checks: [] as Check[],
      canTest: false,
      loading: true,
      loadError: false,
      testing: false,
      testChecks: [] as Check[],
      testError: '',
    };
  },
  computed: {
    icons() {
      return icons;
    },
    statusIcons(): Record<CheckStatus, { icon: string; color: string }> {
      return {
        ok: { icon: icons.success, color: 'positive' },
        warning: { icon: icons.warning, color: 'warning' },
        error: { icon: icons.fail, color: 'negative' },
        info: { icon: icons.info, color: 'grey-7' },
        unknown: { icon: icons.minus, color: 'grey-7' },
      };
    },
    sections(): Section[] {
      const sections: Section[] = [{ key: 'settings', checks: this.checks }];
      if (this.testChecks.length || this.testError) {
        sections.push({
          key: 'test',
          title: 'Connection test',
          checks: this.testChecks,
          error: this.testError,
        });
      }
      return sections;
    },
  },
  mounted() {
    this.loadChecks();
  },
  methods: {
    loadChecks() {
      this.loading = true;
      api
        .get(this.checksUrl)
        .then((response) => {
          this.checks = response.data.checks;
          this.canTest = response.data.canTest;
          this.loadError = false;
        })
        .catch(() => {
          this.loadError = true;
        })
        .finally(() => {
          this.loading = false;
        });
    },
    runTest() {
      this.testing = true;
      this.testError = '';
      api
        .post(this.testUrl)
        .then((response) => {
          this.testChecks = response.data.checks;
        })
        .catch((error: AxiosError<{ detail?: string }>) => {
          this.testChecks = [];
          this.testError =
            error.response?.data?.detail ||
            'The connection test could not be run.';
        })
        .finally(() => {
          this.testing = false;
        });
    },
  },
});
</script>

<style lang="scss" scoped>
.check-value {
  white-space: normal;
  overflow-wrap: anywhere;
}

.check-value--side {
  max-width: 45%;
  text-align: right;
}

.check-items {
  margin: 0;
  padding-left: 1.2em;
}
</style>
