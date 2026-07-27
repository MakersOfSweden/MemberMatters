<template>
  <q-page class="row flex content-start justify-center">
    <div v-if="loggedIn" class="dashboard-root">
      <div class="column flex content-start justify-center">
        <q-banner
          v-if="
            profile.memberStatus !== 'active' &&
            profile.memberStatus !== 'accountonly'
          "
          inline-actions
          rounded
          class="bg-orange text-white q-ma-md"
        >
          <template v-slot:avatar>
            <q-icon :name="icons.warning" />
          </template>
          {{ $t('access.inactive') }}
        </q-banner>
      </div>

      <template v-if="hasVisibleCards">
        <h5 class="q-ma-md">
          {{ $t('dashboard.quickCards') }}
        </h5>
        <quick-cards />
      </template>

      <h5 class="q-ma-md">
        {{ $t('dashboard.usefulResources') }}
      </h5>
      <div class="dashboard-grid">
        <dashboard-card
          v-for="card in homepageCards"
          :key="card.title"
          :title="card.title"
          :icon="card.icon"
          :description="card.description"
          :link-text="card.btn_text"
          :link-location="card.url"
          :router-link="card.routerLink ? card.routerLink : false"
          :links="card.links"
        />
      </div>
    </div>
  </q-page>
</template>

<script>
import { mapGetters, mapActions } from 'vuex';
import QuickCards from '@components/QuickCards.vue';
import { Platform } from 'quasar';
import DashboardCard from '@components/DashboardCard.vue';
import icons from 'src/icons';

export default {
  name: 'DashboardPage',
  components: { QuickCards, DashboardCard },
  computed: {
    Platform() {
      return Platform;
    },
    ...mapGetters('config', ['homepageCards', 'features']),
    ...mapGetters('profile', ['loggedIn', 'profile']),
    icons() {
      return icons;
    },
    hasVisibleCards() {
      return (
        this.features.enableMembershipStatusCard ||
        this.features.enableSiteSignIn ||
        this.features.enableReportIssue
      );
    },
  },
  methods: {
    ...mapActions('profile', ['getProfile']),
  },
  async mounted() {
    await this.getProfile();
  },
};
</script>

<style lang="sass" scoped>
// Shared containing block for every dashboard row.
.dashboard-root
  width: 100%
  max-width: $maxWidth
  margin: auto

.dashboard-grid
  display: grid
  // auto-fill keeps unused slots empty; min(...) prevents overflow on narrow containers.
  grid-template-columns: repeat(auto-fill, minmax(min(400px, 100%), 1fr))
  align-items: stretch

  > *
    min-width: 0
</style>
