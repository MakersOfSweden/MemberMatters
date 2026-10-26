// import Vue from "vue";
import { i18n } from 'boot/i18n';
import { api } from 'boot/axios';

// The admin members page's list/card choice is a per-device preference, so it
// outlives the session. Storage can be missing or throw (private windows,
// blocked site data); the page then just picks a default again.
const MEMBERS_VIEW_KEY = 'mm.adminMembersView';

function loadMembersView() {
  try {
    const stored = window.localStorage.getItem(MEMBERS_VIEW_KEY);
    return stored === 'list' || stored === 'grid' ? stored : null;
  } catch {
    return null;
  }
}

function saveMembersView(view) {
  try {
    window.localStorage.setItem(MEMBERS_VIEW_KEY, view);
  } catch {
    // Not persisted; the choice still holds for this session.
  }
}

export default {
  namespaced: true,
  state: {
    meetings: [],
    meetingTypes: [],
    kiosks: [],
    doors: [],
    interlocks: [],
    memberbucksDevices: [],
    tiers: [],
    // Kept in the store so the members list survives navigating to a member.
    membersFilter: '',
    membersState: 'all',
    // rowsPerPage default depends on screen size, so MembersList sets it.
    membersPagination: {
      sortBy: 'name',
      descending: false,
      page: 1,
      rowsPerPage: null,
    },
    // 'members' or 'signup'; kept so the back button from a member returns
    // to the tab it was opened from.
    membersTab: 'members',
    // 'list', 'grid', or null until the members page picks a default.
    membersView: loadMembersView(),
    signupState: 'all',
    // { [step]: 'complete' | 'pending' | 'outstanding' }; absent means any.
    signupStepFilters: {},
    signupPagination: {
      sortBy: 'registered',
      descending: false,
      page: 1,
      rowsPerPage: 15,
    },
  },
  getters: {
    meetings: (state) => state.meetings,
    meetingTypes: (state) => state.meetingTypes,
    kiosks: (state) => state.kiosks,
    doors: (state) => state.doors,
    interlocks: (state) => state.interlocks,
    memberbucksDevices: (state) => state.memberbucksDevices,
    tiers: (state) => state.tiers,
    membersFilter: (state) => state.membersFilter,
    membersState: (state) => state.membersState,
    membersPagination: (state) => state.membersPagination,
    membersTab: (state) => state.membersTab,
    membersView: (state) => state.membersView,
    signupState: (state) => state.signupState,
    signupStepFilters: (state) => state.signupStepFilters,
    signupPagination: (state) => state.signupPagination,
  },
  mutations: {
    setMeetings(state, payload) {
      state.meetings = payload;
    },
    setMeetingTypes(state, payload) {
      state.meetingTypes = payload;
    },
    setKiosks(state, payload) {
      state.kiosks = payload;
    },
    setDoors(state, payload) {
      state.doors = payload;
    },
    setInterlocks(state, payload) {
      state.interlocks = payload;
    },
    setMemberbucksDevices(state, payload) {
      state.memberbucksDevices = payload;
    },
    setTiers(state, payload) {
      state.tiers = payload;
    },
    setMembersFilter(state, payload) {
      state.membersFilter = payload;
    },
    setMembersState(state, payload) {
      state.membersState = payload;
    },
    setMembersPagination(state, payload) {
      state.membersPagination = payload;
    },
    setMembersTab(state, payload) {
      state.membersTab = payload;
    },
    setMembersView(state, payload) {
      state.membersView = payload;
      saveMembersView(payload);
    },
    setSignupState(state, payload) {
      state.signupState = payload;
    },
    setSignupStepFilters(state, payload) {
      state.signupStepFilters = payload;
    },
    setSignupPagination(state, payload) {
      state.signupPagination = payload;
    },
  },
  actions: {
    getMeetings({ commit }) {
      return new Promise((resolve, reject) => {
        api
          .get('/api/meetings/')
          .then((result) => {
            commit('setMeetings', result.data);
            resolve();
          })
          .catch((error) => {
            reject();
            throw error;
          });
      });
    },
    getMeetingTypes({ commit }) {
      return new Promise((resolve, reject) => {
        api
          .get('/api/meetings/types/')
          .then((result) => {
            // eslint-disable-next-line no-return-assign
            const results = result.data.map((type) => ({
              label: `${type.label} ${i18n.global.t('meetingForm.meeting')}`,
              value: type.value,
            }));
            commit('setMeetingTypes', results);
            resolve();
          })
          .catch((error) => {
            reject();
            throw error;
          });
      });
    },
    getKiosks({ commit }) {
      return new Promise((resolve, reject) => {
        api
          .get('/api/kiosks/')
          .then((result) => {
            commit('setKiosks', result.data);
            resolve();
          })
          .catch((error) => {
            reject();
            throw error;
          });
      });
    },
    getDoors({ commit }) {
      return new Promise((resolve, reject) => {
        api
          .get('/api/admin/doors/')
          .then((result) => {
            commit('setDoors', result.data);
            resolve();
          })
          .catch((error) => {
            reject();
            throw error;
          });
      });
    },
    getInterlocks({ commit }) {
      return new Promise((resolve, reject) => {
        api
          .get('/api/admin/interlocks/')
          .then((result) => {
            commit('setInterlocks', result.data);
            resolve();
          })
          .catch((error) => {
            reject();
            throw error;
          });
      });
    },
    getMemberbucksDevices({ commit }) {
      return new Promise((resolve, reject) => {
        api
          .get('/api/admin/memberbucks-devices/')
          .then((result) => {
            commit('setMemberbucksDevices', result.data);
            resolve();
          })
          .catch((error) => {
            reject();
            throw error;
          });
      });
    },
    getTiers({ commit }) {
      return new Promise((resolve, reject) => {
        api
          .get('/api/admin/tiers/')
          .then((result) => {
            commit('setTiers', result.data);
            resolve();
          })
          .catch((error) => {
            reject();
            throw error;
          });
      });
    },
  },
};
