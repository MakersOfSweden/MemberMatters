<template>
  <div class="column q-gutter-y-sm full-width">
    <h6 class="q-mt-md q-mb-sm">
      {{ $t('adminTools.accessDescription') }}
    </h6>

    <access-list :member-id="memberId" :inactive-warning="inactiveWarning" />
  </div>
</template>

<script lang="ts">
import AccessList from '@components/AccessList.vue';
import { MemberProfile } from 'types/member';
import { defineComponent } from 'vue';

export default defineComponent({
  name: 'MemberAccessTab',
  components: { AccessList },
  props: {
    member: {
      type: Object,
      default: () => ({}),
    },
  },
  computed: {
    memberId(): number {
      return (this.member as MemberProfile).id;
    },
    inactiveWarning(): boolean {
      return (this.member as MemberProfile).state === 'inactive';
    },
  },
});
</script>
