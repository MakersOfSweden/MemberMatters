<template>
  <div class="profile-form">
    <q-form ref="formRef" @submit="onSubmit">
      <p class="text-caption q-mb-md">{{ $t('form.allFieldsRequired') }}</p>

      <profile-fields v-model="form" actor="member" :stored="stored" />

      <q-banner v-if="success" class="bg-positive text-white q-mt-md">
        {{ $t('form.saved') }}
      </q-banner>

      <q-banner
        v-if="errorMessageKeys.length"
        class="bg-negative text-white q-mt-md"
      >
        <div v-for="key in errorMessageKeys" :key="key">{{ $t(key) }}</div>
      </q-banner>

      <q-banner v-else-if="genericError" class="bg-negative text-white q-mt-md">
        {{ $t('error.requestFailed') }}
      </q-banner>

      <q-btn
        :label="$t('button.submit')"
        type="submit"
        color="primary"
        class="full-width q-mt-md"
        :loading="saving"
        :disable="saving || !isDirty"
      />
    </q-form>
  </div>
</template>

<script>
import { mapGetters, mapActions } from 'vuex';
import ProfileFields from './ProfileFields.vue';
import { errorKeys } from '../utils/profileErrors';
import { emptyProfileFields } from '../utils/profileFields';

export default {
  name: 'ProfileForm',
  components: { ProfileFields },
  data() {
    return {
      form: emptyProfileFields(),
      initialFormSnapshot: '',
      saving: false,
      success: false,
      genericError: false,
      errorMessageKeys: [],
    };
  },
  computed: {
    ...mapGetters('profile', ['profile']),
    isDirty() {
      return JSON.stringify(this.form) !== this.initialFormSnapshot;
    },
    // The saved values. Hidden fields aren't in the profile, so they're blank.
    stored() {
      const p = this.profile;
      return {
        email: p.email ?? '',
        firstName: p.firstName ?? '',
        lastName: p.lastName ?? '',
        phone: p.phone ?? '',
        screenName: p.screenName ?? '',
        vehicleRegistrationPlate: p.vehicleRegistrationPlate ?? '',
        address: { ...(p.address ?? {}) },
      };
    },
  },
  methods: {
    ...mapActions('profile', ['getProfile']),
    loadInitialForm() {
      this.form = { ...this.stored, address: { ...this.stored.address } };
      this.initialFormSnapshot = JSON.stringify(this.form);
    },
    onSubmit() {
      this.success = false;
      this.genericError = false;
      this.errorMessageKeys = [];
      this.saving = true;

      // The backend stores the phone number in E.164, and applies each
      // field's setting: locked and hidden fields sent back are ignored.
      this.$axios
        .put('/api/profile/', this.form)
        .then(() => {
          this.success = true;
          this.getProfile();
        })
        .catch((err) => {
          this.errorMessageKeys = errorKeys(err?.response);
          this.genericError = this.errorMessageKeys.length === 0;
        })
        .finally(() => {
          this.saving = false;
        });
    },
  },
  watch: {
    profile() {
      this.loadInitialForm();
    },
    form: {
      deep: true,
      handler() {
        if (!this.isDirty) return;
        this.success = false;
        this.genericError = false;
        this.errorMessageKeys = [];
      },
    },
  },
  beforeMount() {
    this.loadInitialForm();
  },
};
</script>

<style lang="sass">
.profile-form
  max-width: $maxWidthMedium
  width: 100%
</style>
