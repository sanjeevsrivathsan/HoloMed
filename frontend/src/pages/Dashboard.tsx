import { FileText, ScanLine, Sparkles, TrendingUp, Clock, ArrowRight, AlertCircle } from 'lucide-react';
import { Card, CardHeader } from '@/components/Card';
import { StatusBadge } from '@/components/StatusBadge';
import { SectionHeader } from '@/components/SectionHeader';
import { reportStatusLabels } from '@/lib/demo-data';
import type { Report, ImagingStudy, AuditEvent, MedicalMeasurement } from '@/lib/types';
import type { PageKey } from '@/components/Sidebar';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';

interface DashboardProps {
  reports: Report[];
  studies: ImagingStudy[];
  measurements: MedicalMeasurement[];
  auditEvents: AuditEvent[];
  patientName: string;
  onNavigate: (page: PageKey) => void;
  onOpenReport: (reportId: string) => void;
}

export function Dashboard({ reports, studies, measurements, auditEvents, patientName, onNavigate, onOpenReport }: DashboardProps) {
  const recentReports = [...reports].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 4);
  const recentStudies = [...studies].sort((a, b) => b.studyDate.localeCompare(a.studyDate)).slice(0, 3);
  const recentAudit = [...auditEvents].sort((a, b) => b.timestamp.localeCompare(a.timestamp)).slice(0, 5);

  const hba1cData = measurements
    .filter((m) => m.testName === 'HbA1c')
    .sort((a, b) => a.reportDate.localeCompare(b.reportDate))
    .map((m) => ({ date: m.reportDate, value: m.value }));

  const processingReports = reports.filter((r) => r.status !== 'ready');
  const aiInsights = reports.filter((r) => r.summary).length;

  const formatDate = (d: string) => new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

  return (
    <div className="space-y-6">
      {/* Greeting */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-bold text-neutral-900 dark:text-white">Welcome back, {patientName.split(' ')[0]}</h2>
          </div>
          <p className="mt-0.5 text-sm text-neutral-500 dark:text-neutral-400">Here's your health overview for today</p>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card hover onClick={() => onNavigate('reports')}>
          <div className="p-5">
            <div className="flex items-center justify-between">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-teal-50 text-teal-600 dark:bg-teal-950 dark:text-teal-400">
                <FileText className="h-5 w-5" />
              </div>
              <ArrowRight className="h-4 w-4 text-neutral-300 dark:text-neutral-600" />
            </div>
            <p className="mt-3 text-2xl font-bold text-neutral-900 dark:text-white">{reports.length}</p>
            <p className="text-xs text-neutral-500 dark:text-neutral-400">Medical Reports</p>
          </div>
        </Card>
        <Card hover onClick={() => onNavigate('imaging')}>
          <div className="p-5">
            <div className="flex items-center justify-between">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-600 dark:bg-blue-950 dark:text-blue-400">
                <ScanLine className="h-5 w-5" />
              </div>
              <ArrowRight className="h-4 w-4 text-neutral-300 dark:text-neutral-600" />
            </div>
            <p className="mt-3 text-2xl font-bold text-neutral-900 dark:text-white">{studies.length}</p>
            <p className="text-xs text-neutral-500 dark:text-neutral-400">Imaging Studies</p>
          </div>
        </Card>
        <Card hover onClick={() => onNavigate('reports')}>
          <div className="p-5">
            <div className="flex items-center justify-between">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber-50 text-amber-600 dark:bg-amber-950 dark:text-amber-400">
                <Sparkles className="h-5 w-5" />
              </div>
              <ArrowRight className="h-4 w-4 text-neutral-300 dark:text-neutral-600" />
            </div>
            <p className="mt-3 text-2xl font-bold text-neutral-900 dark:text-white">{aiInsights}</p>
            <p className="text-xs text-neutral-500 dark:text-neutral-400">AI Insights Generated</p>
          </div>
        </Card>
      </div>

      {/* Attention items */}
      {processingReports.length > 0 && (
        <Card className="border-amber-200 bg-amber-50/50 dark:border-amber-700/30 dark:bg-amber-900/5">
          <div className="flex items-center gap-3 p-4">
            <AlertCircle className="h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
            <div className="flex-1">
              <p className="text-sm font-medium text-amber-800 dark:text-amber-300">
                {processingReports.length} report{processingReports.length > 1 ? 's' : ''} still processing
              </p>
              <p className="text-xs text-amber-600 dark:text-amber-400/80">
                {processingReports.map((r) => r.title).join(', ')}
              </p>
            </div>
            <button onClick={() => onNavigate('reports')} className="btn btn-secondary px-3 py-1.5 text-xs">
              View
            </button>
          </div>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Recent Reports */}
        <Card>
          <CardHeader
            title="Recent Reports"
            icon={<FileText className="h-4.5 w-4.5" />}
            action={<button onClick={() => onNavigate('reports')} className="text-xs font-medium text-teal-600 hover:underline dark:text-teal-400">View all</button>}
          />
          <div className="divide-y divide-neutral-100 dark:divide-neutral-800">
            {recentReports.map((report) => (
              <button
                key={report.id}
                onClick={() => onOpenReport(report.id)}
                className="flex w-full items-center gap-3 px-5 py-3 text-left hover:bg-neutral-50 dark:hover:bg-neutral-800/50"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-neutral-900 dark:text-neutral-100">{report.title}</p>
                  <p className="text-xs text-neutral-500 dark:text-neutral-400">{report.source} · {formatDate(report.date)}</p>
                </div>
                <StatusBadge
                  variant={report.status === 'ready' ? 'success' : 'processing'}
                  pulse={report.status !== 'ready'}
                >
                  {reportStatusLabels[report.status]}
                </StatusBadge>
              </button>
            ))}
          </div>
        </Card>

        {/* Recent Imaging */}
        <Card>
          <CardHeader
            title="Recent Imaging"
            icon={<ScanLine className="h-4.5 w-4.5" />}
            action={<button onClick={() => onNavigate('imaging')} className="text-xs font-medium text-teal-600 hover:underline dark:text-teal-400">View all</button>}
          />
          <div className="divide-y divide-neutral-100 dark:divide-neutral-800">
            {recentStudies.map((study) => (
              <div key={study.id} className="flex items-center gap-3 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-neutral-900 dark:text-neutral-100">{study.description}</p>
                  <p className="text-xs text-neutral-500 dark:text-neutral-400">{study.modality} · {formatDate(study.studyDate)}</p>
                </div>
                <button onClick={() => onNavigate('imaging')} className="btn btn-secondary px-3 py-1.5 text-xs whitespace-nowrap">
                  Open imaging workspace
                </button>
              </div>
            ))}
            {recentStudies.length === 0 && (
              <p className="px-5 py-8 text-center text-sm text-neutral-400">No imaging studies available</p>
            )}
          </div>
        </Card>
      </div>

      {/* Health Trends Preview */}
      <Card>
        <CardHeader
          title="Health Trends"
          subtitle="HbA1c over time"
          icon={<TrendingUp className="h-4.5 w-4.5" />}
          action={<button onClick={() => onNavigate('timeline')} className="text-xs font-medium text-teal-600 hover:underline dark:text-teal-400">Full timeline</button>}
        />
        <div className="px-5 pb-5" style={{ height: 220 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={hba1cData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-neutral-200 dark:text-neutral-800" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="currentColor" className="text-neutral-400" tickFormatter={(v) => new Date(v).toLocaleDateString('en-US', { month: 'short', year: '2-digit' })} />
              <YAxis tick={{ fontSize: 11 }} stroke="currentColor" className="text-neutral-400" domain={[5, 6.5]} />
              <Tooltip
                contentStyle={{ borderRadius: 8, border: '1px solid', fontSize: 12, background: 'var(--tooltip-bg, #fff)' }}
                formatter={(value: any, name: any, ...rest: any[]) => [`${value ?? '-'}%`, 'HbA1c']}
              />
              <ReferenceLine y={5.7} stroke="#f59e0b" strokeDasharray="4 4" label={{ value: 'Upper normal', fontSize: 10, fill: '#f59e0b' }} />
              <Line type="monotone" dataKey="value" stroke="#14b8a6" strokeWidth={2} dot={{ r: 4 }} activeDot={{ r: 6 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {/* Recent Activity */}
      <Card>
        <CardHeader title="Recent Activity" icon={<Clock className="h-4.5 w-4.5" />} />
        <div className="px-5 pb-5">
          <div className="space-y-3">
            {recentAudit.map((event) => (
              <div key={event.id} className="flex items-start gap-3">
                <div className="mt-1 h-2 w-2 shrink-0 rounded-full bg-teal-500" />
                <div className="flex-1">
                  <p className="text-sm text-neutral-700 dark:text-neutral-300">{event.description}</p>
                  <p className="text-xs text-neutral-400">
                    {event.eventType} · {new Date(event.timestamp).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </Card>
    </div>
  );
}
