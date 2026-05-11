import { Platform } from 'quasar';
import { boot } from 'quasar/wrappers';
import type { MemberState } from '../pages/pageAndRouteConfig';

export default boot(({ router, store }) => {
  router.beforeEach((to, from, next) => {
    // if we're in kiosk mode disallow certain pages
    if (Platform.is.electron) {
      if (!to.meta.kiosk) {
        return next({ name: 'dashboard' });
      }
    }

    // Check if the user must be logged in to access the route
    if (to.meta.loggedIn === true) {
      if (store.getters['profile/loggedIn'] === true) return next();
      else {
        return next({
          name: 'login',
          query: {
            nextUrl: to.fullPath,
          },
        });
      }
    }

    // Check if the user must be an admin to access the route
    if (to.meta.admin === true) {
      if (store.getters['profile/profile'].permissions.staff === true)
        return next();
      else {
        return next({ name: 'Error403' });
      }
    }

    // Check the route's allowedStates (member state gating). Staff bypass.
    const profile = store.getters['profile/profile'];
    const allowedStates = to.meta.allowedStates as MemberState[] | undefined;
    if (
      allowedStates &&
      profile?.memberStatus &&
      !profile.permissions?.staff &&
      !allowedStates.includes(profile.memberStatus)
    ) {
      return next({ name: 'Error403MemberOnly' });
    }

    // if we are authenticating via SSO then don't update the route unless we're registering
    if (!from.query.sso || to.name === 'register') {
      return next();
    }
  });

  router.afterEach(() => {
    // eslint-disable-next-line
    // @ts-ignore
    if (typeof ga !== 'undefined') {
      // eslint-disable-next-line
      // @ts-ignore
      ga('send', 'pageview');
    }
  });

  router.onError((error) => {
    if (/loading chunk \d* failed./i.test(error.message)) {
      window.location.reload();
    }
  });
});
