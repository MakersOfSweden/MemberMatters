<template>
  <div class="">
    <h3 class="q-mt-none q-mb-md">
      {{ profileForm.firstName }} {{ profileForm.lastName }} ({{
        profileForm.screenName
      }})
      <q-icon
        v-if="selectedMember.stateLocked"
        :name="icons.lock"
        color="warning"
        size="md"
        class="q-ml-sm"
      >
        <q-tooltip>{{ $t('adminTools.stateLockedTooltip') }}</q-tooltip>
      </q-icon>
    </h3>
    <q-card
      class="q-mb-none"
      style="background-color: transparent"
      :class="{ 'q-pb-lg': $q.screen.xs }"
    >
      <q-tabs
        v-model="tab"
        align="justify"
        narrow-indicator
        class="bg-primary text-white"
      >
        <q-tab name="profile" :label="$t('menuLink.profile')" />
        <q-tab name="access" :label="$t('adminTools.access')" />
        <q-tab name="billing" :label="$t('adminTools.billing')" />
        <q-tab name="log" :label="$t('adminTools.log')" />
      </q-tabs>

      <q-separator />

      <q-tab-panels v-model="tab" animated>
        <q-tab-panel name="profile" class="q-px-lg q-py-lg">
          <div
            class="row justify-start q-pt-sm"
            :class="{ 'q-px-sm': $q.screen.xs, 'q-px-lg': !$q.screen.xs }"
          >
            <q-btn
              class="q-mr-sm q-mb-sm"
              :color="
                selectedMember.adminDisabledAccess ? 'positive' : 'warning'
              "
              :icon="
                selectedMember.adminDisabledAccess ? icons.lock : undefined
              "
              :label="
                selectedMember.adminDisabledAccess
                  ? $t('adminTools.resumeAccess')
                  : $t('adminTools.pauseAccess')
              "
              :loading="adminDialogs.toggleAccess.loading"
              @click="openToggleAccessDialog"
            />
            <q-btn
              class="q-mr-sm q-mb-sm"
              :color="
                selectedMember.state === 'active' ? 'negative' : 'primary'
              "
              :label="
                selectedMember.state === 'active'
                  ? $t('adminTools.deactivate')
                  : $t('adminTools.activate')
              "
              :loading="adminDialogs.stateChange.loading"
              @click="openStateChangeDialog"
            />
            <q-btn
              v-if="
                selectedMember.subscriptionStatus === 'active' ||
                selectedMember.subscriptionStatus === 'pending' ||
                selectedMember.subscriptionStatus === 'cancelling'
              "
              class="q-mr-sm q-mb-sm"
              color="negative"
              :label="$t('adminTools.cancelMembership')"
              :loading="adminDialogs.cancelMembership.loading"
              @click="openCancelMembershipDialog"
            />

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
                    (val) =>
                      validateEmail(val) || $t('validation.invalidEmail'),
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
                    (val) =>
                      validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
                  ]"
                />

                <q-input
                  v-model="profileForm.lastName"
                  outlined
                  :label="requiredLabel($t('form.lastName'))"
                  lazy-rules
                  :rules="[
                    (val) =>
                      validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
                  ]"
                />

                <q-input
                  v-model="profileForm.phone"
                  outlined
                  type="tel"
                  :label="requiredLabel($t('form.mobile'))"
                  lazy-rules
                  :rules="[
                    (val) =>
                      validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
                  ]"
                />

                <q-input
                  v-model="profileForm.screenName"
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
                            validateNotEmpty(val) ||
                            $t('validation.cannotBeEmpty'),
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
                  :rules="[
                    (val) => validateMax30(val) || $t('validation.max30'),
                  ]"
                />

                <q-banner
                  v-if="success"
                  class="bg-positive text-white q-mt-md"
                >
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
                        $t(
                          `adminTools.memberStatusString.${selectedMember.state}`
                        )
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
                      >{{
                        formatBooleanYesNo(
                          selectedMember.excludeFromEmailExport
                        )
                      }}
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
                            ? formatDate(
                                selectedMember[item as keyof MemberProfile]
                              )
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
        </q-tab-panel>

        <q-tab-panel name="access">
          <div class="column q-gutter-y-sm full-width">
            <h6 class="q-mt-md q-mb-sm">
              {{ $t('adminTools.accessDescription') }}
            </h6>

            <access-list
              :member-id="selectedMemberFiltered.id"
              :inactive-warning="selectedMemberFiltered.state === 'inactive'"
            />
          </div>
        </q-tab-panel>

        <q-tab-panel name="billing">
          <div class="column flex content-start items-start q-gutter-y-lg">
            <div class="column q-gutter-y-sm full-width">
              <div class="text-h6">
                {{ $t('adminTools.subscriptionInfo') }}
              </div>

              <q-markup-table
                v-if="billing?.subscription"
                bordered
                padding
                class="rounded-borders desktop-only"
              >
                <thead>
                  <tr>
                    <th class="text-left">
                      {{ $t(`adminTools.membershipTier`) }}
                    </th>
                    <th class="text-left">
                      {{ $t(`adminTools.billingPlan`) }}
                    </th>
                    <th class="text-left">
                      {{ $t(`adminTools.billingCycleAnchor`) }}
                    </th>
                    <th class="text-left">{{ $t(`adminTools.startDate`) }}</th>
                    <th class="text-left">
                      {{ $t(`adminTools.currentPeriodEnd`) }}
                    </th>
                    <template v-if="billing.subscription.cancelAt">
                      <th class="text-left">
                        {{ $t(`adminTools.cancelAt`) }}
                      </th>
                      <th class="text-left">
                        {{ $t(`adminTools.cancelAtPeriodEnd`) }}
                      </th>
                    </template>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td class="text-left">
                      <router-link
                        :to="{
                          name: 'manageTier',
                          params: {
                            planId: billing.subscription.membershipPlan.id,
                          },
                        }"
                        >{{
                          billing.subscription.membershipTier.name
                        }}</router-link
                      >
                    </td>
                    <td class="text-left">
                      {{
                        $t('paymentPlans.intervalDescription', {
                          currency:
                            billing.subscription.membershipPlan.currency.toUpperCase(),
                          amount: $n(
                            billing.subscription.membershipPlan.cost / 100,
                            'currency',
                            siteLocaleCurrency
                          ),
                          interval: $tc(
                            `paymentPlans.interval.${billing.subscription.membershipPlan.interval.toLowerCase()}`,
                            billing.subscription.membershipPlan.intervalAmount
                          ),
                        })
                      }}
                    </td>
                    <td class="text-left">
                      {{ formatDate(billing.subscription.billingCycleAnchor) }}
                    </td>
                    <td class="text-left">
                      {{ formatDate(billing.subscription.startDate) }}
                    </td>
                    <td class="text-left">
                      {{ formatDate(billing.subscription.currentPeriodEnd) }}
                    </td>
                    <template v-if="billing.subscription.cancelAt">
                      <td class="text-left">
                        {{ formatDate(billing.subscription.cancelAt) }}
                      </td>
                      <td class="text-left">
                        {{
                          formatBooleanYesNo(
                            billing.subscription.cancelAtPeriodEnd
                          )
                        }}
                      </td>
                    </template>
                  </tr>
                </tbody>
              </q-markup-table>

              <q-list
                v-if="billing?.subscription"
                bordered
                padding
                class="rounded-borders desktop-hide"
                style="max-width: 350px"
              >
                <q-item>
                  <q-item-section>
                    <q-item-label
                      lines="1"
                      :class="{
                        inactive: billing.subscription.status === 'inactive',
                        active: billing.subscription.status === 'active',
                        cancelling:
                          billing.subscription.status === 'cancelling',
                      }"
                    >
                      {{
                        $t(
                          `adminTools.subscriptionStatusString.${billing.subscription.status}`
                        )
                      }}
                    </q-item-label>
                    <q-item-label caption>
                      {{ $t(`adminTools.subscriptionStatus`) }}
                    </q-item-label>
                  </q-item-section>
                </q-item>

                <q-item>
                  <q-item-section>
                    <q-item-label lines="1">
                      {{ formatDate(billing.subscription.billingCycleAnchor) }}
                    </q-item-label>
                    <q-item-label caption>
                      {{ $t(`adminTools.billingCycleAnchor`) }}
                    </q-item-label>
                  </q-item-section>
                </q-item>

                <q-item>
                  <q-item-section>
                    <q-item-label lines="1">
                      {{ formatDate(billing.subscription.startDate) }}
                    </q-item-label>
                    <q-item-label caption>
                      {{ $t(`adminTools.startDate`) }}
                    </q-item-label>
                  </q-item-section>
                </q-item>

                <q-item>
                  <q-item-section>
                    <q-item-label lines="1">
                      {{ formatDate(billing.subscription.currentPeriodEnd) }}
                    </q-item-label>
                    <q-item-label caption>
                      {{ $t(`adminTools.currentPeriodEnd`) }}
                    </q-item-label>
                  </q-item-section>
                </q-item>

                <q-item v-if="billing.subscription.cancelAt">
                  <q-item-section>
                    <q-item-label lines="1">
                      {{ formatDate(billing.subscription.cancelAt) }}
                    </q-item-label>
                    <q-item-label caption>
                      {{ $t(`adminTools.cancelAt`) }}
                    </q-item-label>
                  </q-item-section>
                </q-item>

                <q-item v-if="billing.subscription.cancelAtPeriodEnd">
                  <q-item-section>
                    <q-item-label lines="1">
                      {{ billing.subscription.cancelAtPeriodEnd }}
                    </q-item-label>
                    <q-item-label caption>
                      {{ $t(`adminTools.cancelAtPeriodEnd`) }}
                    </q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>

              <div v-else>
                {{ $t(`adminTools.noSubscription`) }}
              </div>
            </div>

            <div class="column q-gutter-y-sm full-width">
              <div class="text-h6">
                {{ $t('adminTools.billingInfo') }}
              </div>

              <q-markup-table
                v-if="billing?.subscription"
                bordered
                padding
                class="rounded-borders desktop-only"
              >
                <thead>
                  <tr>
                    <th class="text-left">
                      {{ $t(`memberbucks.lastPurchase`) }}
                    </th>
                    <th class="text-left">
                      {{ $t(`memberbucks.cardExpiry`) }}
                    </th>
                    <th class="text-left">{{ $t(`memberbucks.last4`) }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td class="text-left">
                      <div v-if="billing?.memberbucks.lastPurchase">
                        {{ this.formatWhen(billing?.memberbucks.lastPurchase) }}
                        <q-tooltip :delay="500">
                          {{
                            this.formatDate(billing?.memberbucks.lastPurchase)
                          }}
                        </q-tooltip>
                      </div>
                      <div v-else>
                        {{ $t('error.noValue') }}
                      </div>
                    </td>
                    <td class="text-left">
                      {{
                        billing?.memberbucks.stripe_card_expiry ||
                        $t('error.noValue')
                      }}
                    </td>
                    <td class="text-left">
                      {{
                        billing?.memberbucks.stripe_card_last_digits ||
                        $t('error.noValue')
                      }}
                    </td>
                  </tr>
                </tbody>
              </q-markup-table>

              <q-list
                bordered
                padding
                class="rounded-borders mobile-only"
                style="max-width: 350px"
              >
                <q-item>
                  <q-item-section>
                    <q-item-label lines="1">
                      <div v-if="billing?.memberbucks.lastPurchase">
                        {{ this.formatWhen(billing?.memberbucks.lastPurchase) }}
                        <q-tooltip :delay="500">
                          {{
                            this.formatDate(billing?.memberbucks.lastPurchase)
                          }}
                        </q-tooltip>
                      </div>
                      <div v-else>
                        {{ $t('error.noValue') }}
                      </div>
                    </q-item-label>
                    <q-item-label caption>
                      {{ $t(`memberbucks.lastPurchase`) }}
                    </q-item-label>
                  </q-item-section>
                </q-item>

                <q-item>
                  <q-item-section>
                    <q-item-label lines="1">
                      {{
                        billing?.memberbucks.stripe_card_expiry ||
                        $t('error.noValue')
                      }}
                    </q-item-label>
                    <q-item-label caption>
                      {{ $t(`memberbucks.cardExpiry`) }}
                    </q-item-label>
                  </q-item-section>
                </q-item>

                <q-item>
                  <q-item-section>
                    <q-item-label lines="1">
                      {{
                        billing?.memberbucks.stripe_card_last_digits ||
                        $t('error.noValue')
                      }}
                    </q-item-label>
                    <q-item-label caption>
                      {{ $t(`memberbucks.last4`) }}
                    </q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </div>

            <div class="column q-gutter-y-sm full-width">
              <div class="text-h6">
                {{ $t('adminTools.memberbucksTransactions') }}
              </div>

              <q-table
                :rows="billing?.memberbucks.transactions"
                :columns="[
                  {
                    name: 'description',
                    label: 'Description',
                    field: 'description',
                    sortable: true,
                  },
                  {
                    name: 'amount',
                    label: 'Amount',
                    field: 'amount',
                    sortable: true,
                  },
                  {
                    name: 'date',
                    label: 'When',
                    field: 'date',
                    sortable: true,
                    format: (val) => formatWhen(val),
                  },
                ]"
                row-key="id"
                :filter="filter"
                v-model:pagination="pagination"
                :loading="loading"
                :grid="$q.screen.xs"
              >
                <template v-slot:top-left>
                  <div class="row">
                    <q-input
                      v-if="$q.screen.xs"
                      v-model="filter"
                      outlined
                      dense
                      debounce="300"
                      placeholder="Search"
                      style="margin-top: -3px"
                    >
                      <template v-slot:append>
                        <q-icon :name="icons.search" />
                      </template>
                    </q-input>
                  </div>
                  <div class="row">
                    {{ $t('memberbucks.currentBalance') }}
                    {{
                      $n(
                        billing?.memberbucks.balance || 0,
                        'currency',
                        siteLocaleCurrency
                      )
                    }}
                  </div>
                </template>

                <template v-if="$q.screen.gt.xs" v-slot:top-right>
                  <q-input
                    v-model="filter"
                    outlined
                    dense
                    debounce="300"
                    placeholder="Search"
                    style="margin-top: -3px"
                  >
                    <template v-slot:append>
                      <q-icon :name="icons.search" />
                    </template>
                  </q-input>
                </template>

                <template v-slot:body-cell-amount="props">
                  <q-td>
                    <div
                      :class="{
                        credit: props.value > 0,
                        debit: props.value < 0,
                      }"
                    >
                      ${{ props.value }}
                    </div>
                  </q-td>
                </template>
              </q-table>
            </div>
          </div>
        </q-tab-panel>

        <q-tab-panel name="log">
          <div class="text-h6 q-pb-sm">
            {{ $t('adminTools.userEvents') }}
          </div>

          <q-table
            :rows="logs.userEventLogs"
            :columns="[
              {
                name: 'logtype',
                label: 'Log Type',
                field: 'logtype',
                sortable: true,
              },
              {
                name: 'description',
                label: 'Description',
                field: 'description',
                sortable: true,
              },
              {
                name: 'date',
                label: 'Date',
                field: 'date',
                sortable: true,
              },
            ]"
            row-key="id"
            :filter="userEventsFilter"
            v-model:pagination="pagination"
            :loading="loading"
            :grid="$q.screen.xs"
          >
            <template v-slot:top-left>
              <div class="row">
                <q-input
                  v-if="$q.screen.xs"
                  v-model="filter"
                  outlined
                  dense
                  debounce="300"
                  placeholder="Search"
                  style="margin-top: -3px"
                >
                  <template v-slot:append>
                    <q-icon :name="icons.search" />
                  </template>
                </q-input>
              </div>
            </template>

            <template v-if="$q.screen.gt.xs" v-slot:top-right>
              <q-input
                v-model="filter"
                outlined
                dense
                debounce="300"
                placeholder="Search"
                style="margin-top: -3px"
              >
                <template v-slot:append>
                  <q-icon :name="icons.search" />
                </template>
              </q-input>
            </template>

            <template v-slot:item="props">
              <div
                class="q-pa-sm col-xs-12 col-sm-6 col-md-4 col-lg-3 grid-style-transition"
              >
                <q-card class="q-py-sm">
                  <q-list dense>
                    <q-item
                      v-for="col in props.cols.filter(
                        (col) => col.name !== 'desc'
                      )"
                      :key="col.name"
                    >
                      <q-item-section>
                        <q-item-label>{{ col.label }}</q-item-label>
                      </q-item-section>
                      <q-item-section side>
                        <q-item-label caption>
                          <template v-if="col.name === 'date'">
                            <div>
                              {{ this.formatWhen(col.value) }}
                              <q-tooltip :delay="500">
                                {{ this.formatDate(col.value) }}
                              </q-tooltip>
                            </div>
                          </template>

                          <template v-else>
                            {{ col.value }}
                          </template>
                        </q-item-label>
                      </q-item-section>
                    </q-item>
                  </q-list>
                </q-card>
              </div>
            </template>

            <template v-slot:body="props">
              <q-tr :props="props">
                <q-td v-for="col in props.cols" :key="col.name" :props="props">
                  <template v-if="col.name === 'date'">
                    <div>
                      {{ this.formatWhen(col.value) }}
                      <q-tooltip :delay="500">
                        {{ this.formatDate(col.value) }}
                      </q-tooltip>
                    </div>
                  </template>

                  <template v-else>
                    {{ col.value }}
                  </template>
                </q-td>
              </q-tr>
            </template>
          </q-table>

          <div class="text-h6 q-pb-sm subheading">
            {{ $t('adminTools.userDoorLogs') }}
          </div>

          <q-table
            :rows="logs.doorLogs"
            :columns="[
              {
                name: 'door',
                label: 'Door Name',
                field: 'door',
                sortable: true,
              },
              {
                name: 'success',
                label: 'Swipe Status',
                field: 'success',
                sortable: true,
              },
              {
                name: 'date',
                label: 'Date',
                field: 'date',
                sortable: true,
              },
            ]"
            row-key="id"
            :filter="doorFilter"
            v-model:pagination="pagination"
            :loading="loading"
            :grid="$q.screen.xs"
          >
            <template v-slot:top-left>
              <div class="row">
                <q-input
                  v-if="$q.screen.xs"
                  v-model="filter"
                  outlined
                  dense
                  debounce="300"
                  placeholder="Search"
                  style="margin-top: -3px"
                >
                  <template v-slot:append>
                    <q-icon :name="icons.search" />
                  </template>
                </q-input>
              </div>
            </template>

            <template v-if="$q.screen.gt.xs" v-slot:top-right>
              <q-input
                v-model="filter"
                outlined
                dense
                debounce="300"
                placeholder="Search"
                style="margin-top: -3px"
              >
                <template v-slot:append>
                  <q-icon :name="icons.search" />
                </template>
              </q-input>
            </template>

            <template v-slot:item="props">
              <div
                class="q-pa-sm col-xs-12 col-sm-6 col-md-4 col-lg-3 grid-style-transition"
              >
                <q-card class="q-py-sm">
                  <q-list dense>
                    <q-item
                      v-for="col in props.cols.filter(
                        (col) => col.name !== 'desc'
                      )"
                      :key="col.name"
                    >
                      <q-item-section>
                        <q-item-label>{{ col.label }}</q-item-label>
                      </q-item-section>
                      <q-item-section side>
                        <q-item-label caption>
                          <template v-if="col.name === 'date'">
                            <div>
                              {{ this.formatWhen(col.value) }}
                              <q-tooltip :delay="500">
                                {{ this.formatDate(col.value) }}
                              </q-tooltip>
                            </div>
                          </template>

                          <template v-else-if="col.name === 'success'">
                            <div
                              :class="
                                col.value ? 'text-positive' : 'text-negative'
                              "
                            >
                              {{ $t(col.value ? 'success' : 'rejected') }}
                            </div>
                          </template>

                          <template v-else>
                            {{ col.value }}
                          </template>
                        </q-item-label>
                      </q-item-section>
                    </q-item>
                  </q-list>
                </q-card>
              </div>
            </template>

            <template v-slot:body="props">
              <q-tr :props="props">
                <q-td v-for="col in props.cols" :key="col.name" :props="props">
                  <template v-if="col.name === 'date'">
                    <div>
                      {{ this.formatWhen(col.value) }}
                      <q-tooltip :delay="500">
                        {{ this.formatDate(col.value) }}
                      </q-tooltip>
                    </div>
                  </template>

                  <template v-else-if="col.name === 'success'">
                    <div :class="col.value ? 'text-positive' : 'text-negative'">
                      {{ $t(col.value ? 'success' : 'rejected') }}
                    </div>
                  </template>

                  <template v-else>
                    {{ col.value }}
                  </template>
                </q-td>
              </q-tr>
            </template>
          </q-table>

          <div class="text-h6 q-pb-sm subheading">
            {{ $t('adminTools.userInterlockLogs') }}
          </div>

          <q-table
            :rows="logs.interlockLogs"
            :columns="[
              {
                name: 'interlock',
                label: 'Interlock',
                field: 'interlockName',
                sortable: true,
              },
              {
                name: 'dateStarted',
                label: 'Date',
                field: 'dateStarted',
                sortable: true,
              },
              {
                name: 'totalTime',
                label: 'Total Time',
                field: 'totalTime',
                sortable: true,
                sort: sortByFloat,
              },
              {
                name: 'totalCost',
                label: 'Total Cost',
                field: 'totalCost',
                sortable: true,
                sort: sortByFloat,
                format: (val) => $n(val || 0, 'currency', siteLocaleCurrency),
              },
              {
                name: 'userEnded',
                label: 'Swiped Off By',
                field: 'userEnded',
                sortable: true,
              },
              {
                name: 'status',
                label: 'Status',
                field: 'status',
                sortable: true,
              },
            ]"
            row-key="id"
            :filter="doorFilter"
            :pagination="{
              ...pagination,
              sortBy: 'dateStarted',
            }"
            :loading="loading"
            :grid="$q.screen.xs"
          >
            <template v-slot:top-left>
              <div class="row">
                <q-input
                  v-if="$q.screen.xs"
                  v-model="filter"
                  outlined
                  dense
                  debounce="300"
                  placeholder="Search"
                  style="margin-top: -3px"
                >
                  <template v-slot:append>
                    <q-icon :name="icons.search" />
                  </template>
                </q-input>
              </div>
            </template>

            <template v-if="$q.screen.gt.xs" v-slot:top-right>
              <q-input
                v-model="filter"
                outlined
                dense
                debounce="300"
                placeholder="Search"
                style="margin-top: -3px"
              >
                <template v-slot:append>
                  <q-icon :name="icons.search" />
                </template>
              </q-input>
            </template>

            <template v-slot:item="props">
              <div
                class="q-pa-sm col-xs-12 col-sm-6 col-md-4 col-lg-3 grid-style-transition"
              >
                <q-card class="q-py-sm">
                  <q-list dense>
                    <q-item
                      v-for="col in props.cols.filter(
                        (col) => col.name !== 'desc'
                      )"
                      :key="col.name"
                    >
                      <q-item-section>
                        <q-item-label>{{ col.label }}</q-item-label>
                      </q-item-section>
                      <q-item-section side>
                        <q-item-label caption>
                          <template v-if="col.name === 'dateStarted'">
                            <div>
                              {{ this.formatWhen(col.value) }}
                              <q-tooltip :delay="500">
                                {{ this.formatDate(col.value) }}
                              </q-tooltip>
                            </div>
                          </template>

                          <template v-else-if="col.name === 'totalTime'">
                            <div v-if="col.value > 1">
                              {{ this.humanizeDurationOfSeconds(col.value) }}
                              <q-tooltip :delay="500">
                                {{
                                  this.humanizeDurationOfSecondsPrecise(
                                    col.value
                                  )
                                }}
                              </q-tooltip>
                            </div>
                            <div v-else></div>
                          </template>

                          <template v-else-if="col.name === 'status'">
                            <div class="text-negative" v-if="col.value === -1">
                              {{ $t('rejected') }}
                            </div>
                            <div
                              class="text-positive"
                              v-else-if="col.value === 1"
                            >
                              {{ $t('interlocks.finished') }}
                            </div>
                            <div class="text-warning" v-else>
                              {{ $t('interlocks.inProgress') }}
                              <q-spinner-dots></q-spinner-dots>
                            </div>
                          </template>

                          <template v-else>
                            {{ col.value }}
                          </template>
                        </q-item-label>
                      </q-item-section>
                    </q-item>
                  </q-list>
                </q-card>
              </div>
            </template>

            <template v-slot:body="props">
              <q-tr :props="props">
                <q-td v-for="col in props.cols" :key="col.name" :props="props">
                  <template v-if="col.name === 'dateStarted'">
                    <div>
                      {{ this.formatWhen(col.value) }}
                      <q-tooltip :delay="500">
                        {{ this.formatDate(col.value) }}
                      </q-tooltip>
                    </div>
                  </template>

                  <template v-else-if="col.name === 'totalTime'">
                    <div v-if="col.value > 1">
                      {{ this.humanizeDurationOfSeconds(col.value) }}
                      <q-tooltip :delay="500">
                        {{ this.humanizeDurationOfSecondsPrecise(col.value) }}
                      </q-tooltip>
                    </div>
                    <div v-else></div>
                  </template>

                  <template v-else-if="col.name === 'status'">
                    <div class="text-negative" v-if="col.value === -1">
                      {{ $t('rejected') }}
                    </div>
                    <div class="text-positive" v-else-if="col.value === 1">
                      {{ $t('interlocks.finished') }}
                    </div>
                    <div class="text-warning" v-else>
                      {{ $t('interlocks.inProgress') }}
                      <q-spinner-dots></q-spinner-dots>
                    </div>
                  </template>

                  <template v-else>
                    {{ col.value }}
                  </template>
                </q-td>
              </q-tr>
            </template>
          </q-table>
        </q-tab-panel>
      </q-tab-panels>
    </q-card>
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
          <q-checkbox
            v-model="adminDialogs.toggleAccess.lock"
            :label="$t('adminTools.lockStateCheckbox')"
          />
          <p class="text-caption text-grey-7 q-mt-sm">
            {{ $t('adminTools.lockStateHelp') }}
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

    <!-- Activate / Deactivate state dialog -->
    <q-dialog v-model="adminDialogs.stateChange.isOpen">
      <q-card style="min-width: 360px">
        <q-card-section>
          <div class="text-h6">
            {{
              selectedMember.state === 'active'
                ? $t('adminTools.deactivateTitle')
                : $t('adminTools.activateTitle')
            }}
          </div>
        </q-card-section>
        <q-banner
          v-if="selectedMember.stateLocked"
          dense
          class="bg-warning text-white q-mx-md"
          :icon="icons.lock"
        >
          <template v-slot:avatar>
            <q-icon :name="icons.lock" />
          </template>
          {{ $t('adminTools.lockedWarning') }}
        </q-banner>
        <q-card-section class="q-pt-none">
          <p>
            {{
              selectedMember.state === 'active'
                ? $t('adminTools.deactivateDescription')
                : $t('adminTools.activateDescription')
            }}
          </p>
          <q-checkbox
            v-model="adminDialogs.stateChange.lock"
            :label="$t('adminTools.lockStateCheckbox')"
          />
          <p class="text-caption text-grey-7 q-mt-sm">
            {{ $t('adminTools.lockStateHelp') }}
          </p>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn
            flat
            :label="$t('button.cancel')"
            :disable="adminDialogs.stateChange.loading"
            v-close-popup
          />
          <q-btn
            color="primary"
            :label="$t('button.confirm')"
            :loading="adminDialogs.stateChange.loading"
            @click="submitStateChange"
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
        <q-banner
          v-if="selectedMember.stateLocked"
          dense
          class="bg-warning text-white q-mx-md"
        >
          <template v-slot:avatar>
            <q-icon :name="icons.lock" />
          </template>
          {{ $t('adminTools.lockedWarning') }}
        </q-banner>
        <q-card-section class="q-pt-none">
          <p>{{ $t('adminTools.cancelMembershipDescription') }}</p>
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
          <q-checkbox
            v-model="adminDialogs.cancelMembership.lock"
            :label="$t('adminTools.lockStateCheckbox')"
            class="q-mt-md"
          />
          <p class="text-caption text-grey-7 q-mt-sm">
            {{ $t('adminTools.lockStateHelp') }}
          </p>
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
import AccessList from '@components/AccessList.vue';
import formMixin from '@mixins/formMixin';
import icons from '../../icons';
import formatMixin from '@mixins/formatMixin';
import { mapGetters } from 'vuex';
import { MemberBillingInfo, MemberProfile } from 'types/member';
import { defineComponent } from 'vue';

export default defineComponent({
  name: 'ManageMember',
  components: { AccessList },
  mixins: [formMixin, formatMixin],
  props: {
    member: {
      type: Object,
      default: () => {
        {
        }
      },
    },
    members: {
      type: Array,
      default: () => {
        [];
      },
    },
  },
  data() {
    return {
      adminDialogs: {
        toggleAccess: { isOpen: false, lock: false, loading: false },
        stateChange: { isOpen: false, lock: false, loading: false },
        cancelMembership: {
          isOpen: false,
          lock: false,
          loading: false,
          timing: 'at_period_end',
        },
      },
      welcomeLoading: false,
      ensureStripeLoading: false,
      tab: 'profile',
      access: {},
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
      billing: null as MemberBillingInfo | null,
      logs: {
        userEventLogs: [],
        doorLogs: [],
        interlockLogs: [],
      },
      filter: '',
      userEventsFilter: '',
      doorFilter: '',
      interlockFiler: '',
      loading: false,
      pagination: {
        sortBy: 'date',
        descending: true,
        rowsPerPage: this.$q.screen.xs ? 3 : 5,
      },
      smsSendLoading: false,
      smsModalIsOpen: false,
      smsBody: '',
    };
  },
  beforeMount() {
    this.loadInitialForm();
    this.getMemberBilling();
    this.getMemberLogs();
  },
  methods: {
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
          excludeFromEmailExport: this.selectedMember.excludeFromEmailExport,
        })
        .then(() => {
          this.success = true;
          this.$emit('memberUpdated');
        })
        .catch((err) => {
          const message = err?.response?.data?.message;
          if (err?.response?.status === 409 && message) {
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
    getMemberBilling() {
      this.$axios
        .get(`/api/admin/members/${this.member.id}/billing/`)
        .catch(() => {
          this.$q.dialog({
            title: this.$t('error.error'),
            message: this.$t('error.requestFailed'),
          });
        })
        .then((res) => {
          if (!res) return;
          this.billing = res.data;
          if (this.billing && !this.billing?.subscription)
            this.billing.subscription = null;
        })
        .finally(() => {
          this.$emit('memberUpdated');
        });
    },
    getMemberLogs() {
      this.$axios
        .get(`/api/admin/members/${this.member.id}/logs/`)
        .catch(() => {
          this.$q.dialog({
            title: this.$t('error.error'),
            message: this.$t('error.requestFailed'),
          });
        })
        .then((res) => {
          if (!res) return;
          this.logs = res.data;
        })
        .finally(() => {
          this.$emit('memberUpdated');
        });
    },
    openToggleAccessDialog() {
      this.adminDialogs.toggleAccess.lock = this.selectedMember.stateLocked;
      this.adminDialogs.toggleAccess.isOpen = true;
    },
    submitToggleAccess() {
      this.adminDialogs.toggleAccess.loading = true;
      const wasLocked = this.selectedMember.stateLocked;
      const newLock = this.adminDialogs.toggleAccess.lock;
      this.$axios
        .post(
          `/api/admin/members/${this.member.id}/admin-disabled-access/`,
          {
            disabled: !this.selectedMember.adminDisabledAccess,
            lock: newLock,
          }
        )
        .then(() => {
          this.adminDialogs.toggleAccess.isOpen = false;
          this.$emit('memberUpdated');
          this.maybePromptReconcile(wasLocked, newLock);
        })
        .catch(() => {
          this.$q.dialog({
            title: this.$t('error.error'),
            message: this.$t('error.requestFailed'),
          });
        })
        .finally(() => {
          setTimeout(() => {
            this.adminDialogs.toggleAccess.loading = false;
          }, 1200);
        });
    },
    openStateChangeDialog() {
      this.adminDialogs.stateChange.lock = this.selectedMember.stateLocked;
      this.adminDialogs.stateChange.isOpen = true;
    },
    submitStateChange() {
      this.adminDialogs.stateChange.loading = true;
      const wasLocked = this.selectedMember.stateLocked;
      const newLock = this.adminDialogs.stateChange.lock;
      const newState =
        this.selectedMember.state === 'active' ? 'inactive' : 'active';
      this.$axios
        .post(`/api/admin/members/${this.member.id}/state/${newState}/`, {
          lock: newLock,
        })
        .then(() => {
          this.adminDialogs.stateChange.isOpen = false;
          this.$emit('memberUpdated');
          this.maybePromptReconcile(wasLocked, newLock);
        })
        .catch(() => {
          this.$q.dialog({
            title: this.$t('error.error'),
            message: this.$t('error.requestFailed'),
          });
        })
        .finally(() => {
          setTimeout(() => {
            this.adminDialogs.stateChange.loading = false;
          }, 1200);
        });
    },
    openCancelMembershipDialog() {
      this.adminDialogs.cancelMembership.lock =
        this.selectedMember.stateLocked;
      this.adminDialogs.cancelMembership.timing = 'at_period_end';
      this.adminDialogs.cancelMembership.isOpen = true;
    },
    submitCancelMembership() {
      this.adminDialogs.cancelMembership.loading = true;
      const wasLocked = this.selectedMember.stateLocked;
      const newLock = this.adminDialogs.cancelMembership.lock;
      this.$axios
        .post(
          `/api/admin/members/${this.member.id}/cancel-membership/`,
          {
            timing: this.adminDialogs.cancelMembership.timing,
            lock: newLock,
          }
        )
        .then(() => {
          this.adminDialogs.cancelMembership.isOpen = false;
          this.$emit('memberUpdated');
          this.maybePromptReconcile(wasLocked, newLock);
        })
        .catch(() => {
          this.$q.dialog({
            title: this.$t('error.error'),
            message: this.$t('error.requestFailed'),
          });
        })
        .finally(() => {
          setTimeout(() => {
            this.adminDialogs.cancelMembership.loading = false;
          }, 1200);
        });
    },
    maybePromptReconcile(wasLocked: boolean, newLock: boolean) {
      // Sketch's "unlock side effect": when admin clears state_locked on a
      // member whose state and subscription_status disagree in a load-
      // bearing way, prompt to reconcile. We only flag the two
      // load-bearing mismatches; pending/cancelling are normal mid-flow
      // states and don't trigger:
      //   - billing active but state isn't → re-run activation
      //   - state active but no billing    → run deactivation
      if (!wasLocked || newLock) return;
      const m = this.selectedMember;
      let target: 'active' | 'inactive' | null = null;
      if (m.subscriptionStatus === 'active' && m.state !== 'active') {
        target = 'active';
      } else if (
        m.subscriptionStatus === 'inactive' &&
        m.state === 'active'
      ) {
        target = 'inactive';
      }
      if (!target) return;
      this.$q
        .dialog({
          title: this.$t('adminTools.reconcileTitle'),
          message: this.$t(
            target === 'active'
              ? 'adminTools.reconcileMessageActivate'
              : 'adminTools.reconcileMessageDeactivate',
            { state: m.state, subscriptionStatus: m.subscriptionStatus }
          ),
          ok: { label: this.$t('button.confirm'), color: 'primary' },
          cancel: { label: this.$t('button.cancel'), flat: true },
        })
        .onOk(() => {
          this.$axios
            .post(
              `/api/admin/members/${this.member.id}/state/${target}/`,
              { lock: false }
            )
            .then(() => this.$emit('memberUpdated'))
            .catch(() => {
              this.$q.dialog({
                title: this.$t('error.error'),
                message: this.$t('error.requestFailed'),
              });
            });
        });
    },
    optOutEmailExport() {
      this.$axios
        .put(`/api/admin/members/${this.member.id}/profile/`, {
          excludeFromEmailExport: !this.selectedMember.excludeFromEmailExport,
          ...this.profileForm,
        })
        .then(() => {
          this.$emit('memberUpdated');
        })
        .catch(() => {
          this.$q.dialog({
            title: this.$t('error.error'),
            message: this.$t('error.requestFailed'),
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
    selectedMember() {
      if (this.members) {
        return (this.members as MemberProfile[]).find(
          (member) => member.id === this.member.id
        ) as MemberProfile;
      }
      return this.member as MemberProfile;
    },
    selectedMemberFiltered() {
      const newMember = { ...this.selectedMember };
      // eslint-disable-next-line
      // @ts-ignore
      delete newMember.access;
      return newMember;
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
    selectedMember() {
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
.q-card {
  max-width: 100%;
}

//a,
//a:visited,
//a:hover,
//a:active {
//  color: inherit;
//  text-decoration: none;
//}

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
