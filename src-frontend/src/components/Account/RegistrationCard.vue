<template>
  <div class="q-pa-md">
    <q-card class="register-card">
      <q-img
        v-if="images.siteLogo"
        fit="contain"
        :src="images.siteLogo"
        style="max-height: 40px; cursor: pointer"
        class="q-mt-md"
      />

      <h6 class="q-ma-none q-pt-md q-px-md">
        {{ $t('registrationCard.register') }}
      </h6>

      <q-card-section>
        <p class="q-pb-md">
          {{ $t('form.allFieldsRequired') }}
        </p>

        <q-form @submit="onSubmit" @reset="onReset">
          <div class="row q-pb-sm q-col-gutter-sm">
            <q-input
              v-model="form.email"
              class="col-12"
              autofocus
              filled
              type="email"
              :label="requiredLabel($t('form.email'))"
              lazy-rules
              :rules="[
                (val) => validateEmail(val) || $t('validation.invalidEmail'),
              ]"
            />

            <q-input
              v-model="form.firstName"
              class="col-12 col-sm-6"
              filled
              :label="requiredLabel($t('form.firstName'))"
              lazy-rules
              :rules="[
                (val) =>
                  validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
              ]"
            />
            <q-input
              v-model="form.lastName"
              class="col-12 col-sm-6"
              filled
              :label="requiredLabel($t('form.lastName'))"
              lazy-rules
              :rules="[
                (val) =>
                  validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
              ]"
            />

            <q-input
              v-model="form.screenName"
              class="col-12 col-sm-6"
              filled
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
                        validateNotEmpty(val) ||
                        $t('validation.cannotBeEmpty'),
                    ]
                  : []
              "
            />
            <q-input
              v-model="form.mobile"
              class="col-12 col-sm-6"
              filled
              type="tel"
              :label="requiredLabel($t('form.mobile'))"
              lazy-rules
              :rules="[
                (val) =>
                  validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
                (val) =>
                  validatePhone(val, phoneRegion) ||
                  $t('validation.invalidPhone'),
              ]"
            />

            <q-input
              v-if="features?.signup?.collectVehicleRegistrationPlate"
              class="col-12 q-mb-lg"
              v-model="form.vehicleRegistrationPlate"
              :label="$t('form.vehicleRegistrationPlate')"
              :hint="$t('form.vehicleRegistrationNote')"
              filled
              type="text"
              lazy-rules
              :rules="[(val) => validateMax30(val) || $t('validation.max30')]"
            ></q-input>

            <q-input
              class="col-12"
              v-model="form.password"
              :label="requiredLabel($t('form.password'))"
              filled
              :type="isPwd ? 'password' : 'text'"
              lazy-rules
              :rules="[
                (val) =>
                  validateNotEmpty(val) || $t('validation.invalidPassword'),
              ]"
            >
              <template v-slot:append>
                <q-icon
                  :name="isPwd ? icons.visibilityOff : icons.visibility"
                  class="cursor-pointer"
                  @click="isPwd = !isPwd"
                />
              </template>
            </q-input>

            <q-field
              v-if="features?.signup?.requirePrivacyConsent"
              class="col-12"
              borderless
              dense
              :model-value="form.privacyConsent"
              :rules="[
                (val) => val || $t('registrationCard.privacyConsentRequired'),
              ]"
            >
              <q-checkbox
                v-model="form.privacyConsent"
                class="q-mt-sm"
                color="primary"
              >
                <div>
                  <div>{{ $t('registrationCard.privacyConsent') }}</div>
                  <a
                    v-if="features?.signup?.privacyPolicyText"
                    href="#"
                    :class="$q.dark.isActive ? 'text-white' : 'text-black'"
                    @click.stop.prevent="showPrivacyPolicy = true"
                  >
                    {{ $t('registrationCard.privacyPolicyLink') }}
                  </a>
                  <a
                    v-else-if="features?.signup?.privacyPolicyUrl"
                    :href="features.signup.privacyPolicyUrl"
                    target="_blank"
                    rel="noopener"
                    :class="$q.dark.isActive ? 'text-white' : 'text-black'"
                    @click.stop
                  >
                    {{ $t('registrationCard.privacyPolicyLink') }}
                  </a>
                </div>
              </q-checkbox>
            </q-field>
          </div>

          <q-dialog v-model="showPrivacyPolicy">
            <q-card style="max-width: 600px; width: 100%">
              <q-card-section>
                <div class="text-h6">
                  {{ $t('registrationCard.privacyPolicyTitle') }}
                </div>
              </q-card-section>
              <q-card-section class="privacy-policy-text">
                {{ features.signup.privacyPolicyText }}
              </q-card-section>
              <q-card-actions align="right">
                <q-btn
                  v-close-popup
                  :label="$t('button.close')"
                  color="primary-btn"
                  flat
                />
              </q-card-actions>
            </q-card>
          </q-dialog>

          <q-banner v-if="error" class="bg-negative text-white">
            {{ $t('error.requestFailed') }}
          </q-banner>

          <q-banner v-if="errorExists" class="bg-negative text-white">
            {{ $t(errorExists as string) }}
          </q-banner>

          <q-banner
            v-if="validationErrors.length"
            class="bg-negative text-white"
          >
            <ul class="q-my-none">
              <li v-for="(msg, i) in validationErrors" :key="i">{{ msg }}</li>
            </ul>
          </q-banner>

          <p class="text-caption">
            {{ $t('registrationCard.alreadyAMember') }}
            <router-link
              :to="{ name: 'login' }"
              :class="$q.dark.isActive ? 'text-white' : 'text-black'"
            >
              {{ $t('registrationCard.loginHere') }}
            </router-link>
          </p>

          <div class="row">
            <q-space />
            <q-btn
              :label="$t('button.submit')"
              type="submit"
              color="primary-btn"
              :loading="buttonLoading"
              :disable="buttonLoading"
            />
          </div>
        </q-form>
      </q-card-section>
    </q-card>
  </div>
</template>

<script lang="ts">
import { mapGetters } from 'vuex';
import formMixin from '../../mixins/formMixin';
import icons from '../../icons';
import { defineComponent } from 'vue';
import { i18n } from '../../boot/i18n';
import { parsePhoneNumberFromString, type CountryCode } from 'libphonenumber-js';

export default defineComponent({
  name: 'RegistrationCard',
  mixins: [formMixin],
  data() {
    return {
      failed: false,
      error: false,
      errorExists: false as boolean | string,
      validationErrors: [] as string[],
      complete: false,
      buttonLoading: false,
      isPwd: true,
      showPrivacyPolicy: false,
      form: {
        firstName: null,
        lastName: null,
        email: null,
        screenName: null,
        mobile: null,
        password: null,
        vehicleRegistrationPlate: null,
        privacyConsent: false,
      },
    };
  },
  mounted() {
    if (this.loggedIn) this.$router.push({ name: 'dashboard' });
  },
  computed: {
    ...mapGetters('profile', ['loggedIn']),
    ...mapGetters('config', ['features', 'images']),
    icons() {
      return icons;
    },
    // Browser locale provides the region (e.g. 'sv-SE' → 'SE') for
    // parsing locally-formatted numbers; fall back to the server's
    // configured default.
    phoneRegion(): string {
      return (
        navigator.language?.split('-')[1]?.toUpperCase() ||
        this.features?.signup?.defaultPhoneRegion ||
        'AU'
      );
    },
  },
  methods: {
    onReset() {
      this.form.email = null;
      this.form.password = null;
    },
    onSubmit() {
      this.register();
    },
    /**
     * This sends the registration API request to register the user.
     */
    register() {
      this.errorExists = false;
      this.error = false;
      this.validationErrors = [];
      this.buttonLoading = true;

      // Normalise to E.164 before posting; the backend re-validates.
      const mobile = this.form.mobile
        ? parsePhoneNumberFromString(
            this.form.mobile,
            this.phoneRegion as CountryCode,
          )?.format('E.164') ?? this.form.mobile
        : this.form.mobile;

      this.$axios
        .post('/api/register/', {
          firstName: this.form.firstName,
          lastName: this.form.lastName,
          email: this.form.email,
          screenName: this.form.screenName,
          mobile,
          password: this.form.password,
          vehicleRegistrationPlate: this.form.vehicleRegistrationPlate,
        })
        .then(() => {
          this.failed = false;
          this.error = false;
          this.complete = true;

          this.$router.push({ name: 'registerSuccess' });
        })
        .catch((error) => {
          if (error.response?.status === 409) {
            this.errorExists = error.response.data.message;
            this.error = false;
          } else if (error.response?.status === 429) {
            this.errorExists = 'error.tooManyRequests';
            this.error = false;
          } else if (error.response?.status === 503) {
            this.errorExists = 'error.registrationClosed';
            this.error = false;
          } else if (error.response?.status === 400) {
            // DRF serializer errors: { field: ['key', ...] } or
            // { field: 'key' } — every value is an i18n key. Dedupe
            // (a pwned + common password trips two validators) and
            // translate for display.
            const data = (error.response.data || {}) as Record<
              string,
              string | string[]
            >;
            const keys = [...new Set(Object.values(data).flat())];
            this.validationErrors = keys.map(
              (key) => i18n.global.t(key) as string,
            );
            this.error = this.validationErrors.length === 0;
            this.errorExists = false;
          } else {
            this.error = true;
            this.errorExists = false;
          }
        })
        .finally(() => {
          this.buttonLoading = false;
        });
    },
  },
});
</script>

<style scoped>
.register-card {
  width: 100%;
  max-width: 500px;
}

.privacy-policy-text {
  white-space: pre-wrap;
  max-height: 60vh;
  overflow-y: auto;
}
</style>
