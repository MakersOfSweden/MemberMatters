import { defineBoot } from '#q-app';
import { createI18n } from 'vue-i18n';

import messages from '../i18n';
import numberFormats from '../i18n/numberFormats';

export const i18n = createI18n({
  locale: navigator.language,
  fallbackLocale: 'en-AU',
  numberFormats,
  messages,
  legacy: false,
  fallbackWarn: false,
  missingWarn: false,
});

export default defineBoot(({ app }) => {
  // Set i18n instance on app
  app.use(i18n);
});
