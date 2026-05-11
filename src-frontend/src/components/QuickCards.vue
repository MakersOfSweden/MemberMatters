<template>
  <div class="quick-cards-grid">
    <template v-if="enableSiteSignIn">
      <div v-if="siteSignedIn" class="q-pa-md">
        <a @click="signInCard.click" :disabled="signinDisable">
          <q-card class="q-pa-md column justify-center items-center">
            <q-banner
              inline-actions
              rounded
              class="bg-accent text-white q-mb-md"
            >
              <template v-slot:avatar>
                <q-icon :name="icons.warning" />
              </template>
              {{ $t('dashboard.signedIn') }}
            </q-banner>

            <p class="text-h4 q-pa-md">
              {{ signInCard.title }}
            </p>
            <q-icon style="font-size: 100px" :name="signInCard.icon" />
          </q-card>
        </a>
      </div>

      <div v-else class="q-pa-md">
        <a @click="signInCard.click" :disabled="signinDisable">
          <q-card class="q-pa-xl column justify-center items-center">
            <p class="text-h4">
              {{ signInCard.title }}
            </p>
            <q-icon style="font-size: 100px" :name="signInCard.icon" />
          </q-card>
        </a>
      </div>
    </template>

    <div v-if="enableMembershipStatusCard" class="q-pa-md">
      <membership-status-card />
    </div>

    <div v-if="enableMembersOnSite" class="q-pa-md">
      <members-onsite-card />
    </div>

    <div v-if="enableReportIssue" class="q-pa-md">
      <report-issue-card />
    </div>
  </div>
</template>

<script>
import MembersOnsiteCard from '@components/MembersOnsiteCard.vue';
import ReportIssueCard from '@components/ReportIssueCard.vue';
import MembershipStatusCard from '@components/MembershipStatusCard.vue';
import { mapGetters, mapMutations, mapActions } from 'vuex';
import icons from '@icons';

export default {
  name: 'QuickActions',
  components: { ReportIssueCard, MembersOnsiteCard, MembershipStatusCard },
  mounted() {
    this.getSiteSignedIn();
  },
  data() {
    return {
      signinDisable: false,
    };
  },
  methods: {
    ...mapMutations('profile', ['setSiteSignedIn']),
    ...mapActions('profile', ['getSiteSignedIn']),
    doSignIn() {
      this.signinDisable = true;
      this.$axios
        .post('/api/sitesessions/signin/', { guests: [] })
        .then(() => {
          this.setSiteSignedIn(true);
          this.signinDisable = false;

          try {
            setTimeout(diag.hide, 5000);
          } catch {}
        })
        .catch((e) => {
          console.log(e);
          this.setSiteSignedIn(false);
          let diag = this.$q.dialog({
            title: 'Alert',
            message: this.$t('dashboard.signinError'),
          });
          this.signinDisable = false;

          try {
            setTimeout(diag.hide, 5000);
          } catch {}
        });
    },
    doSignOut() {
      this.$axios
        .put('/api/sitesessions/signout/')
        .then(() => {
          this.setSiteSignedIn(false);
          if (this.$q.platform.is.electron) {
            this.$router.push({ name: 'logout' });
          }
        })
        .catch(() => {
          this.$q
            .dialog({
              title: 'Alert',
              message: this.$t('dashboard.signoutError'),
            })
            .finally(() => (this.signinDisable = false));
        });
    },
  },
  computed: {
    ...mapGetters('profile', ['siteSignedIn']),
    ...mapGetters('config', ['features']),
    enableSiteSignIn() {
      return this.features.enableSiteSignIn;
    },
    enableMembersOnSite() {
      return (
        this.features.enableMembersOnSite && this.features.enableSiteSignIn
      );
    },
    enableReportIssue() {
      return this.features.enableReportIssue;
    },
    enableMembershipStatusCard() {
      return this.features.enableMembershipStatusCard;
    },
    icons() {
      return icons;
    },
    signInCard() {
      if (this.siteSignedIn) {
        return {
          title: this.$t('dashboard.signOut'),
          icon: icons.signout,
          click: this.doSignOut,
        };
      } else {
        return {
          title: this.$t('dashboard.signIn'),
          icon: icons.signin,
          click: this.doSignIn,
        };
      }
    },
  },
};
</script>

<style scoped>
a {
  text-decoration: none;
}

.quick-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 400px), 1fr));
  align-items: stretch;
  width: 100%;
}
</style>
