<template>
  <q-page class="column flex justify-start items-center">
    <div style="width: 100%; max-width: 400px">
      <q-banner
        v-if="isInvoiceBilling"
        class="bg-info text-white q-mb-md"
        rounded
      >
        <template v-slot:avatar>
          <q-icon :name="icons.info" />
        </template>
        {{
          features.enableMemberBucks
            ? $t('billing.invoiceMethodMemberbucksInfo')
            : $t('billing.invoiceMethodNoCardNeeded')
        }}
      </q-banner>

      <member-bucks-manage-billing
        v-if="!isInvoiceBilling || features.enableMemberBucks"
        style="width: 100%"
      />
    </div>
  </q-page>
</template>

<script>
import { mapGetters } from 'vuex';
import MemberBucksManageBilling from '@components/MemberBucksManageBilling.vue';
import icons from '@icons';

export default {
  name: 'ManageBillingPage',
  components: {
    MemberBucksManageBilling,
  },
  computed: {
    ...mapGetters('profile', ['profile']),
    ...mapGetters('config', ['features']),
    icons() {
      return icons;
    },
    isInvoiceBilling() {
      return this.profile?.financial?.billingMethod === 'invoice';
    },
  },
};
</script>
