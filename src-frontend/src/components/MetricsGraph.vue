<template>
  <div class="metrics-graph-wrapper">
    <apexchart
      type="line"
      height="100%"
      :options="options"
      :series="series"
    ></apexchart>
  </div>
</template>

<script>
import formatMixin from 'src/mixins/formatMixin';

export default {
  name: 'MetricsGraph',
  mixins: [formatMixin],
  props: {
    metricsData: {
      type: Array,
      default: () => [],
    },
    id: {
      type: String,
      default: '',
    },
  },
  data() {
    return {};
  },
  mounted() {
    setTimeout(() => {
      const chart = ApexCharts.getChartByID('metrics-graph-' + this.id);
      chart.hideSeries('Inactive Member');
      chart.hideSeries('Account Only');
      chart.hideSeries('New Member');
    }, 0); // triggers on the next dom update
  },
  computed: {
    options() {
      return {
        chart: {
          id: 'metrics-graph-' + this.id,
          height: '100%',
        },
        xaxis: {
          // Keep the raw dates as categories so the axis and the tooltip
          // can format them differently below.
          categories: this.metricsData.map((item) => item.date),
          labels: {
            formatter: (value) => this.formatDay(value),
          },
        },
        tooltip: {
          x: {
            // On a category axis the formatter's first arg is the data
            // point index, not the category value — look the date up by
            // index instead.
            formatter: (_value, opts) => {
              const item = this.metricsData[opts?.dataPointIndex];
              return item ? this.formatDate(item.date) : '';
            },
          },
        },
        theme: {
          mode: this.$q.dark.isActive ? 'dark' : 'light',
        },
        yaxis: {
          min: 0,
          labels: {
            formatter: function (val) {
              return val.toFixed(0);
            },
          },
        },
      };
    },
    series() {
      let states = {};
      this.metricsData.map((item) => {
        if (Array.isArray(item.data)) {
          item.data.forEach((state) => {
            if (!state?.state && !state?.type) return;
            if (states[state?.state ?? state?.type] === undefined) {
              states[state?.state ?? state?.type] = [];
            }
            states[state?.state ?? state?.type].push(state.total);
          });
        } else {
          if (states['value'] === undefined) {
            states['value'] = [];
          }
          states['value'].push(item.data.value);
        }
      });
      return Object.keys(states).map((state) => {
        return {
          name: this.$t('stats.labels.' + state),
          data: states[state],
        };
      });
    },
  },
};
</script>

<style scoped>
/* Lock the chart to a fixed 16:9 aspect ratio so it keeps the same
   proportions across breakpoints instead of falling back to a fixed
   400px height regardless of viewport width. Cap the width so charts
   don't stretch unreadably wide on large screens. */
.metrics-graph-wrapper {
  width: 100%;
  max-width: 600px;
  margin: 0 auto;
  aspect-ratio: 4 / 3;
}
</style>
