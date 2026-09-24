import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';
import relativeTime from 'dayjs/plugin/relativeTime';
import duration from 'dayjs/plugin/duration';

dayjs.extend(duration);
dayjs.extend(utc);
dayjs.extend(timezone);
dayjs.extend(relativeTime);
dayjs.tz.guess();

export function formatCsvList(list: Array<string>) {
  return list.map((x, i) => {
    if (list.length === i + 1) return x;
    return `${x}, `;
  });
}

// The API sends every date/time as an ISO 8601 UTC string
// (e.g. "2026-09-24T08:15:00.000Z"); these render it in the viewer's timezone.
export type ApiDate = string | Date;

export function formatDate(date: ApiDate, time = true) {
  if (time) return dayjs(date).local().format('D MMM YYYY, h:mm a');
  return dayjs(date).local().format('D MMM YYYY');
}

export function formatDay(date: ApiDate) {
  return dayjs(date).local().format('D MMM YYYY');
}

export function formatDateSimple(date: ApiDate, time = true) {
  if (time) return dayjs(date).local().format('DD/MM/YYYY, h:mm a');
  return dayjs(date).local().format('D/MMM/YYYY');
}

export function formatWhen(date: ApiDate) {
  return dayjs(date).local().fromNow();
}

export function humanizeDurationOfSeconds(secondsToHumanize: number) {
  return dayjs.duration(secondsToHumanize, 'seconds').humanize();
}

export function humanizeDurationOfSecondsPrecise(secondsToHumanize: number) {
  const duration = dayjs.duration(secondsToHumanize, 'seconds');
  const days = duration.days();
  const hours = duration.hours();
  const minutes = duration.minutes();
  const seconds = duration.seconds();

  let formatted = '';
  if (days > 0) {
    formatted += `${days}d `;
  }
  if (hours > 0) {
    formatted += `${hours}h `;
  }
  if (minutes > 0) {
    formatted += `${minutes}m `;
  }
  if (seconds > 0) {
    formatted += `${seconds}s`;
  }

  return formatted;
}

export function formatBooleanYesNo(value: boolean) {
  // TODO: update to use vue-i18n translations
  return value ? 'Yes' : 'No';
}

export function capitaliseFirst(value: string) {
  return (
    String(value) && String(value)[0].toUpperCase() + String(value).slice(1)
  );
}

export function sortByFloat(a: string, b: string) {
  if (parseFloat(a) < parseFloat(b)) return -1;
  if (parseFloat(a) > parseFloat(b)) return 1;
  return 0;
}

export default {
  methods: {
    formatCsvList,
    formatDate,
    formatDay,
    formatDateSimple,
    formatWhen,
    formatBooleanYesNo,
    capitaliseFirst,
    humanizeDurationOfSeconds,
    humanizeDurationOfSecondsPrecise,
    sortByFloat,
  },
};
