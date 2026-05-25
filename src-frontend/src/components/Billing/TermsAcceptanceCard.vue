<template>
  <div class="q-pa-md flex col">
    <q-card class="flex col items-stretch content-between justify-left">
      <q-item>
        <q-item-section avatar>
          <q-avatar>
            <q-icon :name="icon" />
          </q-avatar>
        </q-item-section>
        <q-item-section>
          <q-item-label>{{ title }}</q-item-label>
        </q-item-section>
      </q-item>

      <q-separator />

      <q-card-section>
        <div v-html="sanitizedBody" />
      </q-card-section>

      <q-separator />

      <q-card-section>
        <q-checkbox
          :model-value="modelValue"
          @update:model-value="$emit('update:modelValue', $event)"
          :label="checkboxText"
        />
      </q-card-section>
    </q-card>
  </div>
</template>

<script lang="ts">
import { defineComponent } from 'vue';
import DOMPurify from 'dompurify';

export default defineComponent({
  name: 'TermsAcceptanceCard',
  props: {
    icon: { type: String, required: true },
    title: { type: String, required: true },
    bodyHtml: { type: String, required: true },
    checkboxText: { type: String, required: true },
    modelValue: { type: Boolean, required: true },
  },
  emits: ['update:modelValue'],
  computed: {
    sanitizedBody(): string {
      // Allow links (with target/rel) so admins can reference policy
      // documents from the cards; everything else falls back to
      // DOMPurify's safe defaults.
      return DOMPurify.sanitize(this.bodyHtml, {
        ADD_ATTR: ['target', 'rel'],
      });
    },
  },
});
</script>
