<template>
  <q-page :class="$q.screen.xs ? 'q-pa-sm' : 'q-pa-md'">
    <div class="row items-center q-col-gutter-sm q-mb-sm">
      <div class="col-12 col-md">
        <!-- On phones the icon goes above the label so long labels (e.g. the
             Swedish "Registreringsstatus") still fit; if they don't, the scroll
             arrows sit outside the tabs instead of on top of them. -->
        <q-tabs
          v-model="tab"
          :inline-label="!$q.screen.xs"
          outside-arrows
          mobile-arrows
          align="left"
          active-color="primary"
          indicator-color="primary"
        >
          <q-tab
            name="members"
            :icon="icons.manageMembers"
            :label="$t('menuLink.members')"
          />
          <q-tab
            name="signup"
            :icon="icons.signupProgress"
            :label="$t('menuLink.signupProgress')"
          />
        </q-tabs>
      </div>

      <div class="col-12 col-md-auto row items-center no-wrap">
        <q-input
          ref="searchInput"
          v-model="search"
          class="col"
          outlined
          dense
          clearable
          :clear-icon="icons.close"
          debounce="300"
          :placeholder="$t('adminTools.searchMembers')"
        >
          <template v-slot:append>
            <q-icon :name="icons.search" />
          </template>
        </q-input>

        <q-btn-toggle
          v-model="view"
          class="q-ml-sm"
          unelevated
          toggle-color="primary"
          :options="viewOptions"
        >
          <template v-slot:list>
            <q-tooltip>{{ $t('adminTools.listView') }}</q-tooltip>
          </template>
          <template v-slot:grid>
            <q-tooltip>{{ $t('adminTools.cardView') }}</q-tooltip>
          </template>
        </q-btn-toggle>
      </div>
    </div>

    <q-tab-panels v-model="tab" keep-alive animated>
      <q-tab-panel name="members" class="q-pa-none">
        <members-list :grid="view === 'grid'" :search="search" />
      </q-tab-panel>
      <q-tab-panel name="signup" class="q-pa-none">
        <signup-progress-list :grid="view === 'grid'" :search="search" />
      </q-tab-panel>
    </q-tab-panels>
  </q-page>
</template>

<script lang="ts">
import { defineComponent } from 'vue';
import type { QInput } from 'quasar';
import icons from '@icons';
import MembersList from '@components/AdminTools/MembersList.vue';
import SignupProgressList from '@components/AdminTools/SignupProgressList.vue';

// Members and Signup Progress as two tabs of one page, sharing the search box
// and the list/card toggle.
export default defineComponent({
  name: 'MembersPage',
  components: { MembersList, SignupProgressList },
  computed: {
    icons() {
      return icons;
    },
    tab: {
      get(): string {
        return this.$store.getters['adminTools/membersTab'];
      },
      set(value: string) {
        this.$store.commit('adminTools/setMembersTab', value);
      },
    },
    search: {
      get(): string {
        return this.$store.getters['adminTools/membersFilter'];
      },
      // The clear button hands back null, but the lists expect a string.
      set(value: string | null) {
        this.$store.commit('adminTools/setMembersFilter', value ?? '');
      },
    },
    view: {
      get(): 'list' | 'grid' | null {
        return this.$store.getters['adminTools/membersView'];
      },
      set(value: 'list' | 'grid') {
        this.$store.commit('adminTools/setMembersView', value);
      },
    },
    viewOptions() {
      return [
        {
          value: 'list',
          icon: icons.viewList,
          slot: 'list',
          attrs: { 'aria-label': this.$t('adminTools.listView') },
        },
        {
          value: 'grid',
          icon: icons.viewGrid,
          slot: 'grid',
          attrs: { 'aria-label': this.$t('adminTools.cardView') },
        },
      ];
    },
  },
  created() {
    // The old Signup Progress URL lands here on its tab.
    if (this.$route.name === 'signupProgress') {
      this.tab = 'signup';
      this.$router.replace({ name: 'members' });
    }
    // First visit on this device: cards on small screens, a table otherwise.
    // Stored, so it sticks until the admin toggles it.
    if (!this.view) {
      this.view = this.$q.screen.lt.md ? 'grid' : 'list';
    }
  },
  mounted() {
    window.addEventListener('keydown', this.onKeydown);
  },
  beforeUnmount() {
    window.removeEventListener('keydown', this.onKeydown);
  },
  methods: {
    // Ctrl/Cmd+F jumps to the member search instead of the browser's find bar,
    // which can only see the current page of the table anyway. Typing in any
    // other field still gets native find.
    onKeydown(event: KeyboardEvent) {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) {
        return;
      }
      // Caps Lock reports 'F' even with shift up.
      if (event.key.toLowerCase() !== 'f') return;

      const target = event.target as HTMLElement | null;
      const tag = target?.tagName?.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || target?.isContentEditable) {
        return;
      }

      event.preventDefault();
      (this.$refs.searchInput as QInput | undefined)?.focus();
    },
  },
});
</script>
