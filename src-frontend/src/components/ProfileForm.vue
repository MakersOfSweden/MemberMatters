<template>
  <div class="profile-form">
    <q-form ref="formRef" @submit="onSubmit">
      <p class="text-caption q-mb-md">{{ $t('form.allFieldsRequired') }}</p>

      <q-banner
        v-if="!canEditBasicDetails"
        rounded
        class="bg-blue text-white q-mb-md"
      >
        {{ $t('form.basicDetailsLocked') }}
      </q-banner>

      <q-input
        v-model="form.email"
        outlined
        type="email"
        :label="requiredLabel($t('form.email'))"
        :readonly="!canEditBasicDetails"
        lazy-rules
        :rules="[(val) => validateEmail(val) || $t('validation.invalidEmail')]"
      />

      <q-input
        v-model="form.firstName"
        outlined
        :label="requiredLabel($t('form.firstName'))"
        :readonly="!canEditBasicDetails"
        lazy-rules
        :rules="[
          (val) => validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
        ]"
      />

      <q-input
        v-model="form.lastName"
        outlined
        :label="requiredLabel($t('form.lastName'))"
        :readonly="!canEditBasicDetails"
        lazy-rules
        :rules="[
          (val) => validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
        ]"
      />

      <q-input
        v-model="form.phone"
        outlined
        type="tel"
        :label="requiredLabel($t('form.mobile'))"
        :readonly="!canEditBasicDetails"
        lazy-rules
        :rules="[
          (val) => validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
          (val) =>
            validatePhone(val, phoneRegion) || $t('validation.invalidPhone'),
        ]"
      />

      <q-input
        v-model="form.screenName"
        outlined
        :label="
          requiredLabel(
            $t('form.screenName'),
            features?.signup?.requireScreenName !== false,
          )
        "
        lazy-rules
        :rules="
          features?.signup?.requireScreenName !== false
            ? [
                (val) =>
                  validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
              ]
            : []
        "
      />

      <q-input
        v-if="features?.signup?.collectVehicleRegistrationPlate"
        v-model="form.vehicleRegistrationPlate"
        outlined
        :label="$t('form.vehicleRegistrationPlate')"
        lazy-rules
        :rules="[(val) => validateMax30(val) || $t('validation.max30')]"
      />

      <q-banner v-if="success" class="bg-positive text-white q-mt-md">
        {{ $t('form.saved') }}
      </q-banner>

      <q-banner v-if="errorMessageKey" class="bg-negative text-white q-mt-md">
        {{ $t(errorMessageKey) }}
      </q-banner>

      <q-banner
        v-else-if="genericError"
        class="bg-negative text-white q-mt-md"
      >
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
import { parsePhoneNumberFromString } from 'libphonenumber-js';
import formMixin from '../mixins/formMixin';

export default {
  name: 'ProfileForm',
  mixins: [formMixin],
  data() {
    return {
      form: {
        email: '',
        firstName: '',
        lastName: '',
        phone: '',
        screenName: '',
        vehicleRegistrationPlate: '',
      },
      initialFormSnapshot: '',
      saving: false,
      success: false,
      genericError: false,
      errorMessageKey: null,
    };
  },
  computed: {
    ...mapGetters('profile', ['profile']),
    ...mapGetters('config', ['features']),
    isDirty() {
      return JSON.stringify(this.form) !== this.initialFormSnapshot;
    },
    canEditBasicDetails() {
      return this.features?.profile?.canEditBasicDetails !== false;
    },
    // Browser locale provides the region (e.g. 'sv-SE' → 'SE') for
    // parsing locally-formatted numbers; fall back to the server's
    // configured default.
    phoneRegion() {
      return (
        navigator.language?.split('-')[1]?.toUpperCase() ||
        this.features?.signup?.defaultPhoneRegion ||
        'AU'
      );
    },
  },
  methods: {
    ...mapActions('profile', ['getProfile']),
    loadInitialForm() {
      this.form.email = this.profile.email ?? '';
      this.form.firstName = this.profile.firstName ?? '';
      this.form.lastName = this.profile.lastName ?? '';
      this.form.phone = this.profile.phone ?? '';
      this.form.screenName = this.profile.screenName ?? '';
      this.form.vehicleRegistrationPlate =
        this.profile.vehicleRegistrationPlate ?? '';
      this.initialFormSnapshot = JSON.stringify(this.form);
    },
    onSubmit() {
      this.success = false;
      this.genericError = false;
      this.errorMessageKey = null;
      this.saving = true;

      // Normalise to E.164 before posting; the backend re-validates.
      const phone = this.form.phone
        ? parsePhoneNumberFromString(this.form.phone, this.phoneRegion)?.format(
            'E.164',
          ) ?? this.form.phone
        : this.form.phone;

      this.$axios
        .put('/api/profile/', { ...this.form, phone })
        .then(() => {
          this.success = true;
          this.getProfile();
        })
        .catch((err) => {
          const message = err?.response?.data?.message;
          const status = err?.response?.status;
          if ((status === 409 || status === 400) && message) {
            this.errorMessageKey = message;
          } else {
            this.genericError = true;
          }
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
        this.errorMessageKey = null;
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
