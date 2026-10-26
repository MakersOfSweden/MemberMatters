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
            <profile-fields
              v-model="profileFields"
              actor="signup"
              layout="grid"
              filled
              autofocus
            />

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

          <captcha-widget
            v-if="features?.enableCaptcha"
            ref="captcha"
            v-model="captchaToken"
            action="register"
          />

          <div class="row">
            <q-space />
            <q-btn
              :label="$t('button.submit')"
              type="submit"
              color="primary-btn"
              :loading="buttonLoading"
              :disable="
                buttonLoading || (features?.enableCaptcha && !captchaToken)
              "
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
import CaptchaWidget from '../CaptchaWidget.vue';
import ProfileFields from '../ProfileFields.vue';
import { emptyProfileFields } from '../../utils/profileFields';

export default defineComponent({
  name: 'RegistrationCard',
  components: { CaptchaWidget, ProfileFields },
  mixins: [formMixin],
  data() {
    return {
      failed: false,
      error: false,
      errorExists: false as boolean | string,
      validationErrors: [] as string[],
      complete: false,
      buttonLoading: false,
      captchaToken: '',
      isPwd: true,
      showPrivacyPolicy: false,
      profileFields: emptyProfileFields(),
      form: {
        password: null,
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
  },
  methods: {
    onReset() {
      this.profileFields.email = '';
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

      // The backend stores the phone number in E.164 and drops the fields
      // the site doesn't collect.
      this.$axios
        .post('/api/register/', {
          ...this.profileFields,
          password: this.form.password,
          captchaToken: this.captchaToken,
        })
        .then(() => {
          this.failed = false;
          this.error = false;
          this.complete = true;

          this.$router.push({ name: 'registerSuccess' });
        })
        .catch((error) => {
          if (error.response?.data?.message === 'error.captchaFailed') {
            this.errorExists = 'error.captchaFailed';
            this.error = false;
          } else if (error.response?.status === 409) {
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
              (key) => i18n.global.t(key) as string
            );
            this.error = this.validationErrors.length === 0;
            this.errorExists = false;
          } else {
            this.error = true;
            this.errorExists = false;
          }
          // The backend verifies (and Turnstile spends) the token before the
          // serializer, so any error consumes it — reset for a fresh retry.
          (this.$refs.captcha as { reset: () => void } | undefined)?.reset();
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
