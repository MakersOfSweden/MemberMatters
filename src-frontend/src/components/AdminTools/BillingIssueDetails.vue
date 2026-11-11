<template>
  <div class="q-gutter-y-xs">
    <div v-if="issue.cause">
      <strong>Likely cause:</strong> {{ issue.cause }}
    </div>
    <div v-if="issue.action">
      <strong>Next step:</strong> {{ issue.action }}
    </div>
    <div v-if="events.length">
      <strong>Events:</strong>
      <ul class="q-my-none">
        <li v-for="event in events" :key="event.id">
          {{ event.type }} · {{ event.id }}
          <span v-if="event.customer">· {{ event.customer }}</span>
        </li>
      </ul>
    </div>
    <div v-if="issue.acknowledgedAt" class="text-grey-7">
      Acknowledged by {{ issue.acknowledgedBy || '—' }} on
      {{ formatDate(issue.acknowledgedAt)
      }}<span v-if="issue.notes">: {{ issue.notes }}</span>
    </div>
    <div v-if="issue.resolvedAt" class="text-grey-7">
      Resolved on {{ formatDate(issue.resolvedAt) }}
    </div>
    <div class="text-caption text-grey-7">Check: {{ issue.check }}</div>
  </div>
</template>

<script lang="ts">
// What a billing integrity issue is about, beyond its one-line summary. Shown
// in the expanded table row and on the issue's card.
import { defineComponent, PropType } from 'vue';
import formatMixin from '@mixins/formatMixin';
import type { IntegrityIssue } from 'types/billingIntegrity';
import { issueEvents, UndeliveredEvent } from '../../utils/billingIntegrity';

export default defineComponent({
  name: 'BillingIssueDetails',
  mixins: [formatMixin],
  props: {
    issue: {
      type: Object as PropType<IntegrityIssue>,
      required: true,
    },
  },
  computed: {
    events(): UndeliveredEvent[] {
      return issueEvents(this.issue);
    },
  },
});
</script>
