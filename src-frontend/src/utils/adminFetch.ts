import { Dialog } from 'quasar';
import { api } from 'boot/axios';
import { i18n } from 'boot/i18n';

// GET an admin list, showing the usual "request failed" dialog and returning
// an empty list if it can't be loaded.
export async function fetchAdminList<T>(url: string): Promise<T[]> {
  try {
    const response = await api.get(url);
    return response.data;
  } catch {
    Dialog.create({
      title: i18n.global.t('error.error'),
      message: i18n.global.t('error.requestFailed'),
    });
    return [];
  }
}
