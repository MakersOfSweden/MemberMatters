<template>
  <div class="">
    <h3 class="q-mt-none q-mb-md">
      {{ selectedMember.name?.first }} {{ selectedMember.name?.last }}
      <span v-if="selectedMember.screenName"
        >({{ selectedMember.screenName }})</span
      >
      <q-icon
        v-if="selectedMember.stateLocked"
        :name="icons.lock"
        color="warning"
        size="md"
        class="q-ml-sm"
      >
        <q-tooltip>{{ $t('adminTools.stateLockedTooltip') }}</q-tooltip>
      </q-icon>
      <q-icon
        v-if="selectedMember.adminDisabledAccess"
        :name="icons.accessDisabled"
        color="negative"
        size="md"
        class="q-ml-sm"
      >
        <q-tooltip>{{ $t('adminTools.accessDisabledTooltip') }}</q-tooltip>
      </q-icon>
    </h3>
    <q-card
      class="q-mb-none"
      style="background-color: transparent"
      :class="{ 'q-pb-lg': $q.screen.xs }"
    >
      <q-tabs
        v-model="tab"
        align="justify"
        narrow-indicator
        class="bg-primary text-white"
      >
        <q-tab name="profile" :label="$t('menuLink.profile')" />
        <q-tab name="access" :label="$t('adminTools.access')" />
        <q-tab name="billing" :label="$t('adminTools.billing')" />
        <q-tab name="log" :label="$t('adminTools.log')" />
      </q-tabs>

      <q-separator />

      <q-tab-panels v-model="tab" animated>
        <q-tab-panel name="profile" class="q-px-lg q-py-lg">
          <member-profile-tab
            :member="selectedMember"
            @memberUpdated="$emit('memberUpdated')"
          />
        </q-tab-panel>

        <q-tab-panel name="access">
          <member-access-tab :member="selectedMember" />
        </q-tab-panel>

        <q-tab-panel name="billing">
          <member-billing-tab
            :member-id="selectedMember.id"
            @memberUpdated="$emit('memberUpdated')"
          />
        </q-tab-panel>

        <q-tab-panel name="log">
          <member-logs-tab
            :member-id="selectedMember.id"
            @memberUpdated="$emit('memberUpdated')"
          />
        </q-tab-panel>
      </q-tab-panels>
    </q-card>
  </div>
</template>

<script lang="ts">
import icons from '@icons';
import MemberProfileTab from '@components/AdminTools/ManageMember/MemberProfileTab.vue';
import MemberAccessTab from '@components/AdminTools/ManageMember/MemberAccessTab.vue';
import MemberBillingTab from '@components/AdminTools/ManageMember/MemberBillingTab.vue';
import MemberLogsTab from '@components/AdminTools/ManageMember/MemberLogsTab.vue';
import { MemberProfile } from 'types/member';
import { defineComponent } from 'vue';

export default defineComponent({
  name: 'ManageMember',
  components: {
    MemberProfileTab,
    MemberAccessTab,
    MemberBillingTab,
    MemberLogsTab,
  },
  props: {
    member: {
      type: Object,
      default: () => ({}),
    },
    members: {
      type: Array,
      default: () => [],
    },
  },
  emits: ['memberUpdated'],
  data() {
    return {
      tab: 'profile',
    };
  },
  computed: {
    icons() {
      return icons;
    },
    selectedMember(): MemberProfile {
      if (this.members) {
        return (this.members as MemberProfile[]).find(
          (member) => member.id === this.member.id
        ) as MemberProfile;
      }
      return this.member as MemberProfile;
    },
  },
});
</script>

<style lang="scss" scoped>
.q-card {
  max-width: 100%;
}
</style>
