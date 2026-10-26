<template>
  <!--
    The basic profile fields, each shown according to its PROFILE_FIELD_*
    setting (see utils/profileFields.ts). Rendered without a wrapper so the
    fields sit directly in the parent's form, or in its row for the grid
    layout.
  -->
  <q-input
    v-if="shown('email')"
    :model-value="modelValue.email"
    :class="col('col-12')"
    v-bind="inputProps('email')"
    type="email"
    :label="label('email', $t('form.email'))"
    :autofocus="autofocus"
    :rules="rules('email', [validEmail])"
    @update:model-value="update('email', $event)"
  />

  <slot name="after-email" />

  <q-input
    v-if="shown('firstName')"
    :model-value="modelValue.firstName"
    :class="col('col-12 col-sm-6')"
    v-bind="inputProps('firstName')"
    :label="label('firstName', $t('form.firstName'))"
    :rules="rules('firstName', [maxLength(30)])"
    @update:model-value="update('firstName', $event)"
  />

  <q-input
    v-if="shown('lastName')"
    :model-value="modelValue.lastName"
    :class="col('col-12 col-sm-6')"
    v-bind="inputProps('lastName')"
    :label="label('lastName', $t('form.lastName'))"
    :rules="rules('lastName', [maxLength(30)])"
    @update:model-value="update('lastName', $event)"
  />

  <q-input
    v-if="shown('screenName')"
    :model-value="modelValue.screenName"
    :class="col('col-12 col-sm-6')"
    v-bind="inputProps('screenName')"
    :label="label('screenName', $t('form.screenName'))"
    :rules="rules('screenName', [maxLength(30)])"
    @update:model-value="update('screenName', $event)"
  />

  <q-input
    v-if="shown('phone')"
    :model-value="modelValue.phone"
    :class="col('col-12 col-sm-6')"
    v-bind="inputProps('phone')"
    type="tel"
    :label="label('phone', $t('form.mobile'))"
    :rules="rules('phone', [validPhone])"
    @update:model-value="update('phone', $event)"
  />

  <q-input
    v-if="shown('vehicleRegistrationPlate')"
    :model-value="modelValue.vehicleRegistrationPlate"
    :class="col('col-12')"
    v-bind="inputProps('vehicleRegistrationPlate')"
    :label="
      label('vehicleRegistrationPlate', $t('form.vehicleRegistrationPlate'))
    "
    :rules="rules('vehicleRegistrationPlate', [maxLength(30)])"
    @update:model-value="update('vehicleRegistrationPlate', $event)"
  />

  <template v-if="shown('address')">
    <div :class="col('col-12')" class="text-subtitle2 q-mt-sm q-mb-sm">
      {{ label('address', $t('form.address')) }}
      <div v-if="hint('address')" class="text-caption text-grey-7">
        {{ hint('address') }}
      </div>
    </div>

    <template v-for="part in parts" :key="part.key">
      <q-select
        v-if="part.key === 'country'"
        :model-value="address.country || null"
        :class="col('col-12')"
        v-bind="addressInputProps"
        :options="countryOptions"
        emit-value
        map-options
        use-input
        input-debounce="0"
        clearable
        :label="addressLabel(part)"
        :rules="addressRules(part)"
        @filter="filterCountries"
        @update:model-value="updateAddress('country', $event)"
      />
      <q-input
        v-else
        :model-value="address[part.key]"
        :class="col(addressCol(part.key))"
        v-bind="addressInputProps"
        :label="addressLabel(part)"
        :rules="addressRules(part)"
        @update:model-value="updateAddress(part.key, $event)"
      />
    </template>
  </template>
</template>

<script lang="ts">
import { defineComponent, type PropType } from 'vue';
import { mapGetters } from 'vuex';
import { getCountries } from 'libphonenumber-js';
import formMixin from '@mixins/formMixin';
import { i18n } from 'src/boot/i18n';
import {
  addressParts,
  canEdit,
  fieldMode,
  isBlank,
  isRequired,
  isShown,
  onlyAdminsEdit,
  type Actor,
  type Address,
  type AddressPart,
  type FieldMode,
  type ProfileFieldKey,
  type ProfileFieldValues,
} from 'src/utils/profileFields';

type Rule = (value: string) => boolean | string;

const ADDRESS_LABELS: Record<keyof Address, string> = {
  line1: 'form.addressLine1',
  line2: 'form.addressLine2',
  postal_code: 'form.postalCode',
  city: 'form.city',
  country: 'form.country',
};

export default defineComponent({
  name: 'ProfileFields',
  mixins: [formMixin],
  inheritAttrs: false,
  props: {
    modelValue: {
      type: Object as PropType<ProfileFieldValues>,
      required: true,
    },
    // Who is filling in the form: 'signup', 'member' or 'admin'.
    actor: {
      type: String as PropType<Actor>,
      required: true,
    },
    // The values stored for the member, which decide whether a member may
    // still fill in an "only admins edit" field, and whether an admin sees a
    // hidden field. Empty at signup.
    stored: {
      type: Object as PropType<Partial<ProfileFieldValues>>,
      default: () => ({}),
    },
    // 'grid' puts two fields per line on wider screens, for signup.
    layout: {
      type: String as PropType<'stacked' | 'grid'>,
      default: 'stacked',
    },
    filled: {
      type: Boolean,
      default: false,
    },
    autofocus: {
      type: Boolean,
      default: false,
    },
  },
  emits: ['update:modelValue'],
  data() {
    return {
      countryFilter: '',
    };
  },
  computed: {
    ...mapGetters('config', ['features']),
    // Match backend: parse national-format with PROFILE_DEFAULT_PHONE_REGION.
    phoneRegion(): string {
      return this.features?.signup?.defaultPhoneRegion || 'AU';
    },
    parts(): AddressPart[] {
      return addressParts(this.features);
    },
    address(): Address {
      return this.modelValue.address || {};
    },
    addressInputProps(): Record<string, unknown> {
      return this.inputProps('address');
    },
    countries(): { label: string; value: string }[] {
      let names: Intl.DisplayNames | null = null;
      try {
        names = new Intl.DisplayNames([i18n.global.locale.value], {
          type: 'region',
        });
      } catch {
        // An old browser without Intl.DisplayNames shows the codes.
      }
      return getCountries()
        .map((code) => ({ value: code, label: names?.of(code) || code }))
        .sort((a, b) => a.label.localeCompare(b.label));
    },
    countryOptions(): { label: string; value: string }[] {
      const needle = this.countryFilter.toLowerCase();
      if (!needle) return this.countries;
      return this.countries.filter(
        (country) =>
          country.label.toLowerCase().includes(needle) ||
          country.value.toLowerCase() === needle
      );
    },
  },
  methods: {
    mode(key: ProfileFieldKey): FieldMode {
      return fieldMode(this.features, key);
    },
    shown(key: ProfileFieldKey): boolean {
      return isShown(this.mode(key), this.actor, this.stored[key]);
    },
    editable(key: ProfileFieldKey): boolean {
      return canEdit(this.mode(key), this.actor, this.stored[key]);
    },
    required(key: ProfileFieldKey): boolean {
      return this.editable(key) && isRequired(this.mode(key));
    },
    label(key: ProfileFieldKey, text: string): string {
      return this.requiredLabel(text, this.required(key));
    },
    hint(key: ProfileFieldKey): string | undefined {
      const mode = this.mode(key);
      if (this.actor === 'admin' && mode === 'hidden') {
        return this.$t('form.storedButHidden');
      }
      if (this.actor === 'member' && onlyAdminsEdit(mode)) {
        return this.editable(key)
          ? this.$t('form.fillInOnce')
          : this.$t('form.onlyAdminsEdit');
      }
      if (this.actor === 'signup' && key === 'vehicleRegistrationPlate') {
        return this.$t('form.vehicleRegistrationNote');
      }
      return undefined;
    },
    inputProps(key: ProfileFieldKey): Record<string, unknown> {
      return {
        outlined: !this.filled,
        filled: this.filled,
        readonly: !this.editable(key),
        hint: key === 'address' ? undefined : this.hint(key),
        'lazy-rules': true,
      };
    },
    col(classes: string): string {
      return this.layout === 'grid' ? classes : '';
    },
    // A locked field gets no rules: there is nothing the person can fix.
    rules(key: ProfileFieldKey, rules: Rule[]): Rule[] {
      if (!this.editable(key)) return [];
      const required: Rule[] = this.required(key)
        ? [(value) => !isBlank(value) || this.$t('validation.cannotBeEmpty')]
        : [];
      return [...required, ...rules];
    },
    validEmail(value: string): boolean | string {
      return (
        !value ||
        this.validateEmail(value) ||
        this.$t('validation.invalidEmail')
      );
    },
    validPhone(value: string): boolean | string {
      return (
        this.validatePhone(value, this.phoneRegion) ||
        this.$t('validation.invalidPhone')
      );
    },
    maxLength(max: number): Rule {
      return (value) =>
        value == null ||
        String(value).length <= max ||
        this.$t('validation.maxLength', { max });
    },
    update(key: ProfileFieldKey, value: unknown) {
      this.$emit('update:modelValue', { ...this.modelValue, [key]: value });
    },
    addressLabel(part: AddressPart): string {
      // Each part is required while the address is, or once any part is
      // filled in: an address is either blank or complete.
      const required =
        part.required &&
        this.editable('address') &&
        (isRequired(this.mode('address')) || !isBlank(this.address));
      return this.requiredLabel(this.$t(ADDRESS_LABELS[part.key]), required);
    },
    addressRules(part: AddressPart): Rule[] {
      if (!this.editable('address')) return [];
      const rules: Rule[] = [];
      if (part.required) {
        // Needed while the address is required, or once any part is filled
        // in: an address is either blank or complete.
        rules.push(
          (value) =>
            !isBlank(value) ||
            (!isRequired(this.mode('address')) && isBlank(this.address)) ||
            this.$t('validation.cannotBeEmpty')
        );
      }
      // The country comes from the list, so it can't be too long.
      if (part.key !== 'country') rules.push(this.maxLength(part.maxLength));
      return rules;
    },
    addressCol(key: keyof Address): string {
      if (key === 'postal_code') return 'col-12 col-sm-4';
      if (key === 'city') return 'col-12 col-sm-8';
      return 'col-12';
    },
    updateAddress(key: keyof Address, value: string | null) {
      const address: Address = { ...this.address, [key]: value || '' };
      if (key !== 'country') {
        const others = this.parts.filter((part) => part.key !== 'country');
        const anyFilledIn = others.some((part) => !isBlank(address[part.key]));
        // Start with the site's own country once someone types an address,
        // and drop it again when they clear every other part, so a blank
        // address isn't saved as just a country.
        if (anyFilledIn && !address.country) address.country = this.phoneRegion;
        if (!anyFilledIn) address.country = '';
      }
      this.update('address', address);
    },
    filterCountries(value: string, update: (fn: () => void) => void) {
      update(() => {
        this.countryFilter = value;
      });
    },
  },
});
</script>
