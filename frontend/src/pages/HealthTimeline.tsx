import { useState, useMemo } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Legend,
} from 'recharts';
import { Activity, Calendar, TrendingUp, Info, ExternalLink } from 'lucide-react';
import { Card, CardHeader } from '@/components/Card';
import { StatusBadge } from '@/components/StatusBadge';
import { EmptyState } from '@/components/States';
import { flagLabels, flagVariant } from '@/lib/reports';
import { printedBounds } from '@/lib/ranges';
import type { MedicalMeasurement, Report } from '@/lib/types';

interface HealthTimelineProps {
  measurements: MedicalMeasurement[];
  reports: Report[];
  onOpenReport: (reportId: string) => void;
}

const availableMetrics = ['HbA1c', 'LDL', 'HDL', 'Hemoglobin', 'WBC', 'Glucose (fasting)', 'Creatinine', 'Blood Pressure (systolic)', 'Blood Pressure (diastolic)'];

export function HealthTimeline({ measurements, reports, onOpenReport }: HealthTimelineProps) {
  const [selectedMetric, setSelectedMetric] = useState('HbA1c');
  const [compareMetric, setCompareMetric] = useState('none');

  const metricData = useMemo(() => {
    return measurements
      .filter((m) => m.testName === selectedMetric)
      .sort((a, b) => a.reportDate.localeCompare(b.reportDate));
  }, [measurements, selectedMetric]);

  const compareData = useMemo(() => {
    if (compareMetric === 'none') return [];
    return measurements
      .filter((m) => m.testName === compareMetric)
      .sort((a, b) => a.reportDate.localeCompare(b.reportDate));
  }, [measurements, compareMetric]);

  const chartData = useMemo(() => {
    const allDates = new Set<string>([...metricData.map((m) => m.reportDate), ...compareData.map((m) => m.reportDate)]);
    return Array.from(allDates).sort().map((date) => {
      const primary = metricData.find((m) => m.reportDate === date);
      const secondary = compareData.find((m) => m.reportDate === date);
      return {
        date,
        [selectedMetric]: primary?.value ?? null,
        ...(compareMetric !== 'none' ? { [compareMetric]: secondary?.value ?? null } : {}),
      };
    });
  }, [metricData, compareData, selectedMetric, compareMetric]);

  const currentMetric = metricData[metricData.length - 1];
  const previousMetric = metricData[metricData.length - 2];
  const change = currentMetric && previousMetric ? currentMetric.value - previousMetric.value : null;

  const refRange = currentMetric?.referenceRange;
  const hasSourceRange = !!refRange;
  const bounds = printedBounds(refRange);
  const units = new Set(metricData.map((m) => m.unit));
  const mixedUnits = units.size > 1;

  const formatDate = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

  const reportMap = useMemo(() => {
    const map = new Map<string, Report>();
    reports.forEach((r) => map.set(r.id, r));
    return map;
  }, [reports]);

  return (
    <div className="space-y-6">
      {/* Metric Selector */}
      <Card>
        <CardHeader title="Health Timeline" subtitle="Track your measurements over time" icon={<Activity className="h-4.5 w-4.5" />} />
        <div className="px-5 pb-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div className="flex flex-wrap gap-1.5">
              {availableMetrics.map((metric) => (
                <button
                  key={metric}
                  onClick={() => setSelectedMetric(metric)}
                  className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                    selectedMetric === metric
                      ? 'bg-teal-600 text-white'
                      : 'bg-neutral-100 text-neutral-600 hover:bg-neutral-200 dark:bg-neutral-800 dark:text-neutral-400 dark:hover:bg-neutral-700'
                  }`}
                >
                  {metric}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs font-medium text-neutral-500 dark:text-neutral-400">Compare:</label>
              <select
                value={compareMetric}
                onChange={(e) => setCompareMetric(e.target.value)}
                className="rounded-lg border border-neutral-300 bg-white px-2 py-1 text-xs text-neutral-700 focus:border-teal-500 focus:ring-1 focus:ring-teal-500 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300"
              >
                <option value="none">None</option>
                {availableMetrics.filter((m) => m !== selectedMetric).map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
          </div>
        </div>
      </Card>

      {/* Chart */}
      <Card>
        <CardHeader
          title={selectedMetric}
          subtitle={currentMetric ? `Latest: ${currentMetric.value} ${currentMetric.unit}` : undefined}
          icon={<TrendingUp className="h-4.5 w-4.5" />}
        />
        <div className="px-5 pb-5" style={{ height: 320 }}>
          {chartData.length === 0 ? (
            <EmptyState title="No data available" description={`No measurements found for ${selectedMetric}.`} />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-neutral-200 dark:text-neutral-800" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="currentColor" className="text-neutral-400" tickFormatter={(v) => new Date(`${v}T00:00:00`).toLocaleDateString('en-US', { month: 'short', year: '2-digit' })} />
                <YAxis tick={{ fontSize: 11 }} stroke="currentColor" className="text-neutral-400" />
                <Tooltip
                  contentStyle={{ borderRadius: 8, border: '1px solid', fontSize: 12 }}
                  labelFormatter={(v) => formatDate(v as string)}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                {bounds.upper !== undefined && (
                  <ReferenceLine y={bounds.upper} stroke="#f59e0b" strokeDasharray="4 4"
                    label={{ value: 'Printed upper limit (latest report)', fontSize: 10, fill: '#f59e0b' }} />
                )}
                {bounds.lower !== undefined && (
                  <ReferenceLine y={bounds.lower} stroke="#f59e0b" strokeDasharray="4 4"
                    label={{ value: 'Printed lower limit (latest report)', fontSize: 10, fill: '#f59e0b' }} />
                )}
                <Line type="monotone" dataKey={selectedMetric} stroke="#14b8a6" strokeWidth={2} dot={{ r: 4 }} activeDot={{ r: 6 }} />
                {compareMetric !== 'none' && (
                  <Line type="monotone" dataKey={compareMetric} stroke="#f97316" strokeWidth={2} dot={{ r: 4 }} activeDot={{ r: 6 }} />
                )}
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
        {mixedUnits && (
          <div className="flex items-center gap-2 px-5 pb-2 text-xs text-warning-700 dark:text-warning-400">
            <Info className="h-3.5 w-3.5" />
            These results use different units ({Array.from(units).join(', ')}). Values are shown as reported and are not converted.
          </div>
        )}
        {!hasSourceRange && metricData.length > 0 && (
          <div className="flex items-center gap-2 px-5 pb-4 text-xs text-neutral-400">
            <Info className="h-3.5 w-3.5" />
            The latest report does not print a reference range for this test. Values are shown without reference context.
          </div>
        )}
      </Card>

      {/* Current vs Previous */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card>
          <div className="p-5">
            <p className="text-xs text-neutral-500 dark:text-neutral-400">Current Value</p>
            {currentMetric ? (
              <>
                <p className="mt-1 text-2xl font-bold text-neutral-900 dark:text-white">{currentMetric.value} <span className="text-sm font-normal text-neutral-400">{currentMetric.unit}</span></p>
                <StatusBadge variant={flagVariant(currentMetric.flag)}>{flagLabels[currentMetric.flag] ?? currentMetric.flag}</StatusBadge>
              </>
            ) : <p className="mt-1 text-sm text-neutral-400">No data</p>}
          </div>
        </Card>
        <Card>
          <div className="p-5">
            <p className="text-xs text-neutral-500 dark:text-neutral-400">Previous Value</p>
            {previousMetric ? (
              <>
                <p className="mt-1 text-2xl font-bold text-neutral-900 dark:text-white">{previousMetric.value} <span className="text-sm font-normal text-neutral-400">{previousMetric.unit}</span></p>
                <StatusBadge variant={flagVariant(previousMetric.flag)}>{flagLabels[previousMetric.flag] ?? previousMetric.flag}</StatusBadge>
              </>
            ) : <p className="mt-1 text-sm text-neutral-400">No previous data</p>}
          </div>
        </Card>
        <Card>
          <div className="p-5">
            <p className="text-xs text-neutral-500 dark:text-neutral-400">Change</p>
            {change !== null ? (
              <>
                <p className="mt-1 text-2xl font-bold text-neutral-900 dark:text-white">
                  {change > 0 ? '+' : ''}{Number(change.toFixed(2))} <span className="text-sm font-normal text-neutral-400">{currentMetric?.unit}</span>
                </p>
                <p className="text-xs text-neutral-400">{mixedUnits ? 'Units differ — compare with care' : 'Difference between the two latest results'}</p>
              </>
            ) : <p className="mt-1 text-sm text-neutral-400">No comparison available</p>}
          </div>
        </Card>
      </div>

      {/* Source Records Table */}
      <Card>
        <CardHeader title="Source Records" subtitle={`${metricData.length} measurements`} icon={<Calendar className="h-4.5 w-4.5" />} />
        <div className="overflow-x-auto">
          {metricData.length === 0 ? (
            <EmptyState title="No records" description={`No source records for ${selectedMetric}.`} />
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-200 dark:border-neutral-800">
                  <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Date</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-neutral-500">Value</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Unit</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Reference Range</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Flag</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Source</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Report</th>
                </tr>
              </thead>
              <tbody>
                {[...metricData].reverse().map((m) => {
                  const report = reportMap.get(m.reportId);
                  return (
                    <tr key={m.id} className="border-b border-neutral-100 dark:border-neutral-800/50">
                      <td className="px-3 py-2 text-xs text-neutral-700 dark:text-neutral-300">{formatDate(m.reportDate)}</td>
                      <td className="px-3 py-2 text-right text-xs font-medium text-neutral-900 dark:text-neutral-100">{m.value}</td>
                      <td className="px-3 py-2 text-xs text-neutral-400">{m.unit}</td>
                      <td className="px-3 py-2 text-xs text-neutral-400">{m.referenceRange || 'Not printed'}</td>
                      <td className="px-3 py-2"><StatusBadge variant={flagVariant(m.flag)}>{flagLabels[m.flag] ?? m.flag}</StatusBadge></td>
                      <td className="px-3 py-2 text-xs text-neutral-400">{[m.laboratory || m.hospital, m.sourceLocation].filter(Boolean).join(' · ') || '—'}</td>
                      <td className="px-3 py-2 text-xs">
                        {report ? (
                          <button onClick={() => onOpenReport(report.id)} data-testid="timeline-source-link"
                            className="inline-flex items-center gap-1 text-teal-600 hover:underline dark:text-teal-400">
                            {report.title}<ExternalLink className="h-3 w-3" />
                          </button>
                        ) : <span className="text-neutral-400">Entered manually</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </Card>
    </div>
  );
}
