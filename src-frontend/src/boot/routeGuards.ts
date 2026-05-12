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

    // Check if the user must be logged in to access the route. Fall
    // through on the happy path so later checks (admin, allowedStates)
    // still run — every allowedStates route also sets loggedIn:true,
    // so short-circuiting here would skip member-state gating entirely.
    if (
      to.meta.loggedIn === true &&
      store.getters['profile/loggedIn'] !== true
    ) {
      return next({
        name: 'login',
        query: {
          nextUrl: to.fullPath,
        },
      });
    }

    // Check if the user must be an admin to access the route
    if (to.meta.admin === true) {
      if (store.getters['profile/profile']?.permissions?.staff === true)
        return next();
      else {
        return next({ name: 'Error403' });
      }
    }

    // Check the route's allowedStates (member state gating). Staff bypass.
    // Fails closed: a missing profile / memberStatus on a gated route is
    // treated as not-allowed so a not-yet-loaded profile can't slip past.
    const profile = store.getters['profile/profile'];
    const allowedStates = to.meta.allowedStates as MemberState[] | undefined;
    if (allowedStates && profile?.permissions?.staff !== true) {
      if (
        !profile?.memberStatus ||
        !allowedStates.includes(profile.memberStatus)
      ) {
        return next({ name: 'Error403MemberOnly' });
      }
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
