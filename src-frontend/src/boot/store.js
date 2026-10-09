import { defineBoot } from '#q-app';
import store from 'src/store';

// @quasar/app-vite 3 only installs Pinia stores by itself, so the Vuex store
// is installed here, as version 1 did it.
export default defineBoot(({ app, router }) => {
  // Store modules navigate with this.$router, such as the kiosk's idle logout.
  store.$router = router;
  app.use(store);
});
