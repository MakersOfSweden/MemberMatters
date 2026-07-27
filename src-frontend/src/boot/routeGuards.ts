import { Platform } from 'quasar';
import { boot } from 'quasar/wrappers';
import type { MemberState } from '../pages/pageAndRouteConfig';

// Signup stages FORCE_SIGNUP_COMPLETION redirects out of. 'awaiting_payment' is
// deliberately absent: those members have finished every step they can and are
// only waiting on their first invoice, so they keep the run of the portal.
// 'locked' is absent too — the membership plan screen is a dead end for them.
const FORCED_SIGNUP_STAGES = ['needs_plan', 'needs_requirements'];

// Routes an unfinished member may still reach: 'profile' to correct their
// details, 'billing' to add a payment method, and 'logout' so they aren't
// trapped in the portal.
const FORCED_SIGNUP_ROUTES = ['membershipPlan', 'profile', 'billing', 'logout'];

export default boot(({ router, store }) => {
  router.beforeEach(async (to, from, next) => {
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

    // The admin / allowedStates / forced-signup checks below fail closed
    // against an empty profile. On a hard reload (or the post-login redirect
    // to nextUrl) the user can be logged in before getProfile() has resolved —
    // fetch it here so a valid member isn't bounced to an error page.
    if (
      to.meta.loggedIn === true &&
      store.getters['profile/loggedIn'] === true &&
      !store.getters['profile/profile']?.memberStatus
    ) {
      try {
        await store.dispatch('profile/getProfile');
      } catch {
        // Profile fetch failed (e.g. the session expired) — send to login.
        return next({ name: 'login', query: { nextUrl: to.fullPath } });
      }
    }

    // Same race applies to the feature flags: App.vue fetches them, but a hard
    // reload can reach this guard first, and an empty features object would
    // silently switch the forced-signup redirect off.
    if (
      to.meta.loggedIn === true &&
      store.getters['profile/loggedIn'] === true &&
      !Object.keys(store.getters['config/features']).length
    ) {
      try {
        await store.dispatch('config/getSiteConfig');
      } catch {
        // Config is unreachable — fall through rather than strand the user.
      }
    }

    // Check if the user must be an admin to access the route
    if (to.meta.admin === true) {
      if (store.getters['profile/profile']?.permissions?.staff === true)
        return next();
      else {
        return next({ name: 'Error403' });
      }
    }

    const profile = store.getters['profile/profile'];
    const features = store.getters['config/features'];

    // FORCE_SIGNUP_COMPLETION: hold new members on the membership plan screen
    // until they finish signing up. Runs ahead of the allowedStates check so an
    // unfinished member lands on the screen that unblocks them rather than on a
    // 403. Requires enableMembershipPayments — without it the membership plan
    // screen has nothing to show and the redirect would strand them. Skipped in
    // kiosk mode, where the membership plan screen isn't a kiosk route and the
    // block above would bounce it straight back to the dashboard.
    if (
      features?.forceSignupCompletion &&
      features?.enableMembershipPayments &&
      !Platform.is.electron &&
      to.meta.loggedIn === true &&
      profile?.permissions?.staff !== true &&
      FORCED_SIGNUP_STAGES.includes(profile?.signupStage) &&
      !FORCED_SIGNUP_ROUTES.includes(to.name as string)
    ) {
      return next({ name: 'membershipPlan' });
    }

    // Check the route's allowedStates (member state gating). Staff bypass.
    // Fails closed: a missing profile / memberStatus on a gated route is
    // treated as not-allowed so a not-yet-loaded profile can't slip past.
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
