import axios, { AxiosInstance } from 'axios';
import { defineBoot } from '#q-app';

declare module 'vue' {
  interface ComponentCustomProperties {
    $axios: AxiosInstance;
  }
}

const api = axios.create({
  baseURL: import.meta.env.apiBaseUrl || '',
  withCredentials: true,
  xsrfCookieName: 'csrftoken',
  xsrfHeaderName: 'X-CSRFTOKEN',
});

export default defineBoot(({ app }) => {
  app.config.globalProperties.$axios = api;
});

export { api };
