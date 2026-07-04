<template>
  <div>
    <div
      class="row justify-start q-pt-sm"
      :class="{ 'q-px-sm': $q.screen.xs, 'q-px-lg': !$q.screen.xs }"
    >
      <q-btn
        class="q-mr-sm q-mb-sm"
        :color="selectedMember.adminDisabledAccess ? 'positive' : 'warning'"
        :label="
          selectedMember.adminDisabledAccess
            ? $t('adminTools.resumeAccess')
            : $t('adminTools.pauseAccess')
        "
        :loading="adminDialogs.toggleAccess.loading"
        @click="openToggleAccessDialog"
      />
      <q-btn
        v-if="isSettledNonMember"
        class="q-mr-sm q-mb-sm"
        color="primary"
        :label="$t('adminTools.makeMember')"
        :loading="adminDialogs.makeMember.loading"
        @click="openMakeMemberDialog"
      />
      <q-btn
        v-else
        class="q-mr-sm q-mb-sm"
        color="negative"
        :label="$t('adminTools.cancelMembership')"
        :loading="adminDialogs.cancelMembership.loading"
        @click="openCancelMembershipDialog"
      />
      <q-btn
        class="q-mr-sm q-mb-sm"
        :color="
          selectedMember.stateLocked
            ? 'positive'
            : isSettledNonMember
            ? 'warning'
            : 'grey-7'
        "
        :label="
          selectedMember.stateLocked
            ? $t('adminTools.unlockAccount')
            : $t('adminTools.lockAccount')
        "
        :disable="!selectedMember.stateLocked && !isSettledNonMember"
        :loading="adminDialogs.lock.loading"
        @click="openLockDialog"
      >
        <q-tooltip v-if="!selectedMember.stateLocked && !isSettledNonMember">
          {{ $t('adminTools.lockUnavailableTooltip') }}
        </q-tooltip>
      </q-btn>

      <q-btn-dropdown
        class="q-mr-sm q-mb-sm"
        color="primary"
        :label="$t('adminTools.title')"
      >
        <q-list>
          <q-item v-close-popup clickable @click="sendWelcomeEmail">
            <q-item-section>
              <q-item-label
                >{{ $t('adminTools.sendWelcomeEmail') }}
              </q-item-label>
            </q-item-section>
          </q-item>

          <!-- Opt out of email exports -->
          <q-item
            v-if="!selectedMember.excludeFromEmailExport"
            v-close-popup
            clickable
            @click="optOutEmailExport"
          >
            <q-item-section>
              <q-item-label
                >{{ $t('adminTools.optOutEmailExport') }}
              </q-item-label>
            </q-item-section>
          </q-item>

          <!-- Opt in to email exports -->
          <q-item
            v-if="selectedMember.excludeFromEmailExport"
            v-close-popup
            clickable
            @click="optOutEmailExport"
          >
            <q-item-section>
              <q-item-label
                >{{ $t('adminTools.optInEmailExport') }}
              </q-item-label>
            </q-item-section>
          </q-item>

          <!-- Open the send sms modal -->
          <q-item
            v-if="features.sms.enable"
            :disable="profileForm.phone"
            v-close-popup
            clickable
            @click="openSmsModal"
          >
            <q-item-section>
              <q-item-label>{{ $t('adminTools.sendSms') }}</q-item-label>
            </q-item-section>
          </q-item>

          <!-- Ensure Stripe customer exists -->
          <q-item
            v-if="features.enableStripe"
            v-close-popup
            clickable
            :disable="ensureStripeLoading"
            @click="ensureStripeCustomer"
          >
            <q-item-section>
              <q-item-label
                >{{ $t('adminTools.ensureStripeCustomer') }}
              </q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-btn-dropdown>
    </div>

    <div class="row q-pt-md">
      <div
        class="col-12 col-md-6"
        :class="{ 'q-px-sm': $q.screen.xs, 'q-px-lg': !$q.screen.xs }"
      >
        <q-form ref="formRef" @submit="onSubmit">
          <h5 class="q-my-sm">
            {{ $t('adminTools.mainProfile') }}
          </h5>
          <q-input
            v-model="profileForm.email"
            outlined
            type="email"
            :label="requiredLabel($t('form.email'))"
            lazy-rules
            :rules="[
              (val) => validateEmail(val) || $t('validation.invalidEmail'),
            ]"
          />

          <q-input
            v-model="profileForm.rfidCard"
            outlined
            :label="$t('form.rfidCard')"
          />

          <q-input
            v-model="profileForm.firstName"
            outlined
            :label="requiredLabel($t('form.firstName'))"
            lazy-rules
            :rules="[
              (val) => validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
            ]"
          />

          <q-input
            v-model="profileForm.lastName"
            outlined
            :label="requiredLabel($t('form.lastName'))"
            lazy-rules
            :rules="[
              (val) => validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
            ]"
          />

          <q-input
            v-model="profileForm.phone"
            outlined
            type="tel"
            :label="requiredLabel($t('form.mobile'))"
            lazy-rules
            :rules="[
              (val) => validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
              (val) =>
                validatePhone(val, phoneRegion) ||
                $t('validation.invalidPhone'),
            ]"
          />

          <q-input
            v-model="profileForm.screenName"
            outlined
            :label="
              requiredLabel(
                $t('form.screenName'),
                features?.signup?.requireScreenName !== false
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
            v-if="
              features?.signup?.collectVehicleRegistrationPlate ||
              profileForm.vehicleRegistrationPlate
            "
            v-model="profileForm.vehicleRegistrationPlate"
            :disable="!features?.signup?.collectVehicleRegistrationPlate"
            outlined
            :label="$t('form.vehicleRegistrationPlate')"
            lazy-rules
            :rules="[(val) => validateMax30(val) || $t('validation.max30')]"
          />

          <q-banner v-if="success" class="bg-positive text-white q-mt-md">
            {{ $t('form.saved') }}
          </q-banner>

          <q-banner
            v-if="errorMessageKey"
            class="bg-negative text-white q-mt-md"
          >
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

      <div
        class="col-12 col-md-6"
        :class="{ 'q-px-sm': $q.screen.xs, 'q-px-lg': !$q.screen.xs }"
      >
        <h5 class="q-my-sm">
          {{ $t('adminTools.otherAttributes') }}
        </h5>

        <q-list bordered padding class="rounded-borders">
          <q-item>
            <q-item-section>
              <q-item-label
                :class="{
                  inactive: selectedMember.state === 'inactive',
                  active: selectedMember.state === 'active',
                  cancelling: ['accountonly', 'noob'].includes(
                    selectedMember.state
                  ),
                }"
              >
                {{
                  $t(`adminTools.memberStatusString.${selectedMember.state}`)
                }}
              </q-item-label>

              <q-item-label caption>
                {{ $t('adminTools.memberState') }}
              </q-item-label>
            </q-item-section>
          </q-item>

          <q-item key="excludeFromEmailExport">
            <q-item-section>
              <q-item-label
                >{{ formatBooleanYesNo(selectedMember.excludeFromEmailExport) }}
              </q-item-label>

              <q-item-label caption>
                {{ $t(`form.excludeFromEmailExport`) }}
              </q-item-label>
            </q-item-section>
          </q-item>

          <q-item v-for="item in ['id']" :key="item">
            <q-item-section>
              <q-item-label
                >{{
                  selectedMember[item as keyof MemberProfile] != null ||
                  selectedMember[item as keyof MemberProfile] != undefined
                    ? selectedMember[item as keyof MemberProfile]
                    : $t('error.noValue')
                }}
              </q-item-label>

              <q-item-label caption>
                {{ $t(`form.${item}`) }}
              </q-item-label>
            </q-item-section>
          </q-item>
        </q-list>

        <h5 class="q-mt-md q-mb-sm">
          {{ $t('menuLink.memberbucks') }}
        </h5>
        <q-list bordered padding class="rounded-borders">
          <q-item>
            <q-item-section>
              <q-item-label lines="1">
                {{
                  $n(
                    selectedMember.memberBucks.balance || 0,
                    'currency',
                    siteLocaleCurrency
                  )
                }}
              </q-item-label>
              <q-item-label caption>
                {{ $t(`memberbucks.currentBalance`) }}
              </q-item-label>
            </q-item-section>
          </q-item>
          <q-item>
            <q-item-section>
              <q-item-label lines="1">
                {{
                  selectedMember.memberBucks.lastPurchase
                    ? formatDate(selectedMember.memberBucks.lastPurchase)
                    : $t('error.noValue')
                }}
              </q-item-label>
              <q-item-label caption>
                {{ $t(`memberbucks.lastPurchase`) }}
              </q-item-label>
            </q-item-section>
          </q-item>
        </q-list>

        <h5 class="q-mb-sm q-mt-md">
          {{ $t('adminTools.memberDates') }}
        </h5>
        <q-list bordered padding class="rounded-borders">
          <q-item
            v-for="item in [
              'lastInduction',
              'registrationDate',
              'lastUpdatedProfile',
              'lastSeen',
              'termsAcceptedAt',
            ]"
            :key="item"
          >
            <q-item-section>
              <q-item-label lines="1">
                <template v-if="item === 'registrationDate'">
                  {{
                    selectedMember[item]
                      ? formatDate(selectedMember[item])
                      : $t('error.noValue')
                  }}
                </template>
                <template v-else>
                  {{
                    selectedMember[item as keyof MemberProfile]
                      ? formatDate(selectedMember[item as keyof MemberProfile])
                      : $t('error.noValue')
                  }}
                </template>
              </q-item-label>
              <q-item-label caption>
                {{ $t(`adminTools.${item}`) }}
              </q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </div>
    </div>

    <!-- Toggle Access dialog (admin_disabled_access) -->
    <q-dialog v-model="adminDialogs.toggleAccess.isOpen">
      <q-card style="min-width: 360px">
        <q-card-section>
          <div class="text-h6">
            {{
              selectedMember.adminDisabledAccess
                ? $t('adminTools.resumeAccessTitle')
                : $t('adminTools.pauseAccessTitle')
            }}
          </div>
        </q-card-section>
        <q-card-section class="q-pt-none">
          <p>
            {{
              selectedMember.adminDisabledAccess
                ? $t('adminTools.resumeAccessDescription')
                : $t('adminTools.pauseAccessDescription')
            }}
          </p>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn
            flat
            :label="$t('button.cancel')"
            :disable="adminDialogs.toggleAccess.loading"
            v-close-popup
          />
          <q-btn
            color="primary"
            :label="$t('button.confirm')"
            :loading="adminDialogs.toggleAccess.loading"
            @click="submitToggleAccess"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Make Member dialog -->
    <q-dialog v-model="adminDialogs.makeMember.isOpen">
      <q-card style="min-width: 360px">
        <q-card-section>
          <div class="text-h6">{{ $t('adminTools.makeMemberTitle') }}</div>
        </q-card-section>
        <q-card-section class="q-pt-none">
          <p>{{ $t('adminTools.makeMemberDescription') }}</p>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn
            flat
            :label="$t('button.cancel')"
            :disable="adminDialogs.makeMember.loading"
            v-close-popup
          />
          <q-btn
            color="primary"
            :label="$t('button.confirm')"
            :loading="adminDialogs.makeMember.loading"
            @click="submitMakeMember"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Cancel Membership dialog -->
    <q-dialog v-model="adminDialogs.cancelMembership.isOpen">
      <q-card style="min-width: 400px">
        <q-card-section>
          <div class="text-h6">
            {{ $t('adminTools.cancelMembershipTitle') }}
          </div>
        </q-card-section>
        <q-card-section class="q-pt-none">
          <p>{{ $t('adminTools.cancelMembershipDescription') }}</p>
          <template v-if="hasLiveSub">
            <div class="q-mb-sm text-weight-medium">
              {{ $t('adminTools.cancelTimingLabel') }}
            </div>
            <q-option-group
              v-model="adminDialogs.cancelMembership.timing"
              :options="[
                {
                  label: $t('adminTools.cancelTimingAtPeriodEnd'),
                  value: 'at_period_end',
                },
                {
                  label: $t('adminTools.cancelTimingImmediately'),
                  value: 'immediately',
                },
              ]"
            />
          </template>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn
            flat
            :label="$t('button.cancel')"
            :disable="adminDialogs.cancelMembership.loading"
            v-close-popup
          />
          <q-btn
            color="primary"
            :label="$t('button.confirm')"
            :loading="adminDialogs.cancelMembership.loading"
            @click="submitCancelMembership"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Lock / Unlock account dialog -->
    <q-dialog v-model="adminDialogs.lock.isOpen">
      <q-card style="min-width: 360px">
        <q-card-section>
          <div class="text-h6">
            {{
              selectedMember.stateLocked
                ? $t('adminTools.unlockAccountTitle')
                : $t('adminTools.lockAccountTitle')
            }}
          </div>
        </q-card-section>
        <q-card-section class="q-pt-none">
          <p>
            {{
              selectedMember.stateLocked
                ? $t('adminTools.unlockAccountDescription')
                : $t('adminTools.lockAccountDescription')
            }}
          </p>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn
            flat
            :label="$t('button.cancel')"
            :disable="adminDialogs.lock.loading"
            v-close-popup
          />
          <q-btn
            color="primary"
            :label="$t('button.confirm')"
            :loading="adminDialogs.lock.loading"
            @click="submitLock"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog v-model="smsModalIsOpen">
      <q-card>
        <q-card-section>
          <div class="text-h6">
            {{
              $t('adminTools.sendSmsModalTitle', {
                name: `${profileForm.firstName} ${profileForm.lastName}`,
              })
            }}
          </div>
        </q-card-section>

        <q-card-section class="q-pt-none">
          <q-input
            v-model="smsBody"
            autofocus
            :maxlength="320"
            counter
            type="textarea"
            :placeholder="$t('adminTools.smsContentPlaceholder')"
            outlined
            :debounce="debounceLength"
            :label="$t('adminTools.smsContentTitle')"
            :rules="[
              (val) => validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
            ]"
          >
          </q-input>
        </q-card-section>

        <q-card-section>
          <div class="text-h6">
            {{
              $t('adminTools.sendSmsModalPreviewTitle', {
                name: `${profileForm.firstName} ${profileForm.lastName}`,
              })
            }}
          </div>
          <div class="text-body">
            {{
              $t('adminTools.smsCostEstimate', {
                cost: smsCost,
              })
            }}
          </div>
        </q-card-section>

        <q-card-section class="q-pt-none">
          <div class="q-pa-md row justify-center">
            <div style="width: 100%; max-width: 400px">
              <q-chat-message
                :text="[
                  (smsBody.length
                    ? $t('adminTools.smsOneWayBody', { message: smsBody })
                    : $t('adminTools.smsOneWayBody', {
                        message: $t('adminTools.smsContentPlaceholder'),
                      })) +
                    ' ' +
                    features.sms.footer,
                ]"
                sent
                :name="features.sms.senderId"
              />
            </div>
          </div>
        </q-card-section>

        <q-card-actions align="right" class="text-primary">
          <q-btn
            flat
            :label="$t('button.cancel')"
            :disable="smsSendLoading"
            @click="resetSmsModal"
          />
          <q-btn
            color="primary"
            :label="$t('button.send')"
            :loading="smsSendLoading"
            :disable="smsSendLoading"
            type="submit"
            @click="submitSmsModal"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script lang="ts">
import formMixin from '@mixins/formMixin';
import formatMixin from '@mixins/formatMixin';
import icons from '@icons';
import { mapGetters } from 'vuex';
import { MemberProfile } from 'types/member';
import { defineComponent } from 'vue';
import {
  parsePhoneNumberFromString,
  type CountryCode,
} from 'libphonenumber-js';

export default defineComponent({
  name: 'MemberProfileTab',
  mixins: [formMixin, formatMixin],
  props: {
    member: {
      type: Object,
      default: () => ({}),
    },
  },
  emits: ['memberUpdated'],
  data() {
    return {
      adminDialogs: {
        toggleAccess: { isOpen: false, loading: false },
        makeMember: { isOpen: false, loading: false },
        cancelMembership: {
          isOpen: false,
          loading: false,
          timing: 'at_period_end',
        },
        lock: { isOpen: false, loading: false },
      },
      welcomeLoading: false,
      ensureStripeLoading: false,
      profileForm: {
        email: '',
        rfidCard: '',
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
      errorMessageKey: null as string | null,
      smsSendLoading: false,
      smsModalIsOpen: false,
      smsBody: '',
    };
  },
  beforeMount() {
    this.loadInitialForm();
  },
  methods: {
    // Normalise a phone number to E.164 using the region computed
    // above; returns the original string if it can't be parsed (the
    // backend will then reject it).
    toE164Phone(value: string): string {
      if (!value) return value;
      return (
        parsePhoneNumberFromString(
          value,
          this.phoneRegion as CountryCode
        )?.format('E.164') ?? value
      );
    },
    loadInitialForm() {
      this.profileForm.email = this.selectedMember.email ?? '';
      this.profileForm.rfidCard = this.selectedMember.rfid ?? '';
      this.profileForm.firstName = this.selectedMember.name?.first ?? '';
      this.profileForm.lastName = this.selectedMember.name?.last ?? '';
      this.profileForm.phone = this.selectedMember.phone ?? '';
      this.profileForm.screenName = this.selectedMember.screenName ?? '';
      this.profileForm.vehicleRegistrationPlate =
        this.selectedMember.vehicleRegistrationPlate ?? '';
      this.initialFormSnapshot = JSON.stringify(this.profileForm);
    },
    onSubmit() {
      this.success = false;
      this.genericError = false;
      this.errorMessageKey = null;
      this.saving = true;

      this.$axios
        .put(`/api/admin/members/${this.member.id}/profile/`, {
          ...this.profileForm,
          phone: this.toE164Phone(this.profileForm.phone),
          excludeFromEmailExport: this.selectedMember.excludeFromEmailExport,
        })
        .then(() => {
          this.success = true;
          this.$emit('memberUpdated');
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
    sendWelcomeEmail() {
      this.welcomeLoading = true;
      this.$axios
        .post(`/api/admin/members/${this.member.id}/sendwelcome/`)
        .then(() => {
          this.$q.dialog({
            title: this.$t('actionSuccess'),
            message: this.$t('adminTools.sendWelcomeEmailSuccess'),
          });
        })
        .catch(() => {
          this.$q.dialog({
            title: this.$t('error.error'),
            message: this.$t('error.requestFailed'),
          });
        })
        .finally(() => {
          this.welcomeLoading = false;
        });
    },
    ensureStripeCustomer() {
      this.ensureStripeLoading = true;
      this.$axios
        .post(`/api/admin/members/${this.member.id}/ensurestripecustomer/`)
        .then((res) => {
          this.$q.dialog({
            title: this.$t('actionSuccess'),
            message:
              res.data?.message ||
              this.$t('adminTools.ensureStripeCustomerSuccess'),
          });
        })
        .catch(() => {
          this.$q.dialog({
            title: this.$t('error.error'),
            message: this.$t('error.requestFailed'),
          });
        })
        .finally(() => {
          this.ensureStripeLoading = false;
        });
    },
    openToggleAccessDialog() {
      this.adminDialogs.toggleAccess.isOpen = true;
    },
    submitToggleAccess() {
      this.adminDialogs.toggleAccess.loading = true;
      this.$axios
        .post(`/api/admin/members/${this.member.id}/admin-disabled-access/`, {
          disabled: !this.selectedMember.adminDisabledAccess,
        })
        .then(() => {
          this.adminDialogs.toggleAccess.isOpen = false;
          this.$emit('memberUpdated');
        })
        .catch(() => {
          this.$q.dialog({
            title: this.$t('error.error'),
            message: this.$t('error.requestFailed'),
          });
        })
        .finally(() => {
          this.adminDialogs.toggleAccess.loading = false;
        });
    },
    openMakeMemberDialog() {
      this.adminDialogs.makeMember.isOpen = true;
    },
    submitMakeMember() {
      this.adminDialogs.makeMember.loading = true;
      this.$axios
        .post(`/api/admin/members/${this.member.id}/make-member/`)
        .then(() => {
          this.adminDialogs.makeMember.isOpen = false;
          this.$emit('memberUpdated');
        })
        .catch(() => {
          this.$q.dialog({
            title: this.$t('error.error'),
            message: this.$t('error.requestFailed'),
          });
        })
        .finally(() => {
          this.adminDialogs.makeMember.loading = false;
        });
    },
    openCancelMembershipDialog() {
      this.adminDialogs.cancelMembership.timing = 'at_period_end';
      this.adminDialogs.cancelMembership.isOpen = true;
    },
    submitCancelMembership() {
      this.adminDialogs.cancelMembership.loading = true;
      this.$axios
        .post(`/api/admin/members/${this.member.id}/cancel-membership/`, {
          timing: this.adminDialogs.cancelMembership.timing,
        })
        .then(() => {
          this.adminDialogs.cancelMembership.isOpen = false;
          this.$emit('memberUpdated');
        })
        .catch(() => {
          this.$q.dialog({
            title: this.$t('error.error'),
            message: this.$t('error.requestFailed'),
          });
        })
        .finally(() => {
          this.adminDialogs.cancelMembership.loading = false;
        });
    },
    openLockDialog() {
      this.adminDialogs.lock.isOpen = true;
    },
    submitLock() {
      this.adminDialogs.lock.loading = true;
      this.$axios
        .post(`/api/admin/members/${this.member.id}/state-lock/`, {
          locked: !this.selectedMember.stateLocked,
        })
        .then(() => {
          this.adminDialogs.lock.isOpen = false;
          this.$emit('memberUpdated');
        })
        .catch(() => {
          this.$q.dialog({
            title: this.$t('error.error'),
            message: this.$t('error.requestFailed'),
          });
        })
        .finally(() => {
          this.adminDialogs.lock.loading = false;
        });
    },
    optOutEmailExport() {
      this.$axios
        .put(`/api/admin/members/${this.member.id}/profile/`, {
          excludeFromEmailExport: !this.selectedMember.excludeFromEmailExport,
          ...this.profileForm,
          phone: this.toE164Phone(this.profileForm.phone),
        })
        .then(() => {
          this.$emit('memberUpdated');
        })
        .catch((err) => {
          const message = err?.response?.data?.message;
          const status = err?.response?.status;
          const key =
            (status === 409 || status === 400) && message
              ? message
              : 'error.requestFailed';
          this.$q.dialog({
            title: this.$t('error.error'),
            message: this.$t(key),
          });
        });
    },
    openSmsModal() {
      this.smsModalIsOpen = true;
    },
    resetSmsModal() {
      this.smsModalIsOpen = false;
      this.smsBody = '';
      this.smsSendLoading = false;
    },
    submitSmsModal() {
      this.smsSendLoading = true;
      this.$axios
        .post(`/api/admin/members/${this.member.id}/sendsms/`, {
          smsBody: this.$t('adminTools.smsOneWayBody', {
            message: this.smsBody,
          }),
        })
        .then(() => {
          this.resetSmsModal();
          this.$q.notify({
            message: this.$t('adminTools.sendSmsSuccess', {
              name: `${this.profileForm.firstName} ${this.profileForm.lastName}`,
            }),
            type: 'positive',
          });
        })
        .catch(() => {
          this.smsSendLoading = false;
          this.$q.dialog({
            title: this.$t('error.error'),
            message: this.$t('adminTools.sendSmsFail', {
              name: `${this.profileForm.firstName} ${this.profileForm.lastName}`,
            }),
          });
        });
      return;
    },
  },
  computed: {
    ...mapGetters('config', ['siteLocaleCurrency', 'features']),
    // Match backend: parse national-format with PROFILE_DEFAULT_PHONE_REGION.
    phoneRegion(): string {
      return (this as any).features?.signup?.defaultPhoneRegion || 'AU';
    },
    selectedMember(): MemberProfile {
      return this.member as MemberProfile;
    },
    // A settled non-member: not active and without a live subscription.
    // Button 2 reads "Make Member" for these; the Lock button is enabled.
    isSettledNonMember(): boolean {
      return (
        this.selectedMember.state !== 'active' &&
        this.selectedMember.subscriptionStatus === 'inactive'
      );
    },
    hasLiveSub(): boolean {
      return this.selectedMember.subscriptionStatus !== 'inactive';
    },
    icons() {
      return icons;
    },
    smsCost() {
      const smsContainsUnicode = /[^\u0000-\u00ff]/.test(this.smsBody);
      const charsPerSms = smsContainsUnicode ? 70 : 160;
      return Math.ceil(this.smsBody.length / charsPerSms);
    },
    isDirty(): boolean {
      return JSON.stringify(this.profileForm) !== this.initialFormSnapshot;
    },
  },
  watch: {
    member() {
      this.loadInitialForm();
    },
    profileForm: {
      deep: true,
      handler() {
        if (!this.isDirty) return;
        this.success = false;
        this.genericError = false;
        this.errorMessageKey = null;
      },
    },
  },
});
</script>

<style lang="scss" scoped>
.active {
  color: green;
}

.inactive {
  color: red;
}

.cancelling {
  color: orange;
}

.q-field__after,
.q-field__append {
  padding-left: 0;
}

.subheading {
  padding-top: 20px;
}
</style>
