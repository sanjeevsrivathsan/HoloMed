import { useState, useMemo } from 'react';
import { Search, Sparkles, FileText, Link2, MessageSquare } from 'lucide-react';
import { Card, CardHeader } from '@/components/Card';
import { FilterBar, SelectFilter } from '@/components/FilterBar';
import { StatusBadge } from '@/components/StatusBadge';
import { NoResultsState } from '@/components/States';
import { SourceReferenceList } from '@/components/SourceReference';
import { api } from '@/lib/api';
import { errorMessage, flagLabels, flagVariant, reportStatusLabels } from '@/lib/reports';
import type { Report, MedicalMeasurement, SourceReference } from '@/lib/types';

interface SearchInterpretation {
  tests: string[];
  since: string | null;
  until: string | null;
  flags: string[];
  report_types: string[];
}

interface SearchResponse {
  report_ids: number[];
  measurement_ids: number[];
  interpretation?: SearchInterpretation;
}

interface HealthSearchProps {
  reports: Report[];
  measurements: MedicalMeasurement[];
  sourceReferences: SourceReference[];
  onSelectReport: (id: string) => void;
}

const exampleQueries = [
  'Show HbA1c results from the last two years',
  'Show flagged cholesterol results',
  'Blood pressure since 2025',
  'Find radiology reports',
];

export function HealthSearch({ reports, measurements, sourceReferences, onSelectReport }: HealthSearchProps) {
  const [search, setSearch] = useState('');
  const [nlQuery, setNlQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('All');
  const [statusFilter, setStatusFilter] = useState('All');
  const [hospitalFilter, setHospitalFilter] = useState('All');
  const [testNameFilter, setTestNameFilter] = useState('All');
  const [flagFilter, setFlagFilter] = useState('All');
  const [hasSearched, setHasSearched] = useState(false);
  const [searchResult, setSearchResult] = useState<{ reportIds: string[], measurementIds: string[], interpretation?: SearchInterpretation } | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  const hospitals = useMemo(() => {
    const set = new Set<string>();
    reports.forEach((r) => { if (r.hospital) set.add(r.hospital); if (r.laboratory) set.add(r.laboratory); });
    return ['All', ...Array.from(set)];
  }, [reports]);

  const testNames = useMemo(() => {
    const set = new Set<string>();
    measurements.forEach((m) => set.add(m.testName));
    return ['All', ...Array.from(set)];
  }, [measurements]);

  const reportTypes = ['All', 'Blood Test', 'Imaging Report', 'Discharge Summary', 'Clinical Note', 'Prescription', 'Other'];
  const reportTitles = useMemo(() => new Map(reports.map((r) => [r.id, r.title])), [reports]);

  const matchingReports = useMemo(() => {
    return reports.filter((r) => {
      if (searchResult && !searchResult.reportIds.includes(r.id)) return false;
      if (search && !r.title.toLowerCase().includes(search.toLowerCase())) return false;
      if (typeFilter !== 'All' && r.type !== typeFilter) return false;
      if (statusFilter !== 'All' && (r.status === 'ready' ? 'completed' : r.status) !== statusFilter) return false;
      if (hospitalFilter !== 'All' && r.hospital !== hospitalFilter && r.laboratory !== hospitalFilter) return false;
      return true;
    });
  }, [reports, search, typeFilter, statusFilter, hospitalFilter, searchResult]);

  const matchingMeasurements = useMemo(() => {
    return measurements.filter((m) => {
      if (searchResult && !searchResult.measurementIds.includes(m.id)) return false;
      if (testNameFilter !== 'All' && m.testName !== testNameFilter) return false;
      if (flagFilter !== 'All' && m.flag !== flagFilter) return false;
      if (hospitalFilter !== 'All' && m.hospital !== hospitalFilter && m.laboratory !== hospitalFilter) return false;
      return true;
    }).sort((a, b) => a.reportDate.localeCompare(b.reportDate));
  }, [measurements, testNameFilter, flagFilter, hospitalFilter, searchResult]);

  const matchingRefs = useMemo(() => {
    const reportIds = new Set(matchingReports.map((r) => r.id));
    return sourceReferences.filter((r) => reportIds.has(r.reportId));
  }, [sourceReferences, matchingReports]);

  const handleNlSearch = async () => {
    if (!nlQuery.trim()) {
      setSearchResult(null);
      return;
    }
    setHasSearched(true);
    setIsSearching(true);
    
    setSearchError(null);
    try {
      const res = await api.post<SearchResponse>('/api/v1/search', { query: nlQuery });
      setSearchResult({
        reportIds: res.report_ids.map(String),
        measurementIds: res.measurement_ids.map(String),
        interpretation: res.interpretation,
      });
    } catch (err) {
      setSearchError(errorMessage(err, 'Search failed. Please try again.'));
    } finally {
      setIsSearching(false);
    }
  };

  const formatDate = (d: string) => {
    const date = new Date(d.length === 10 ? `${d}T00:00:00` : d);
    return Number.isNaN(date.getTime()) ? d : date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };
  const interp = searchResult?.interpretation;
  const interpText = interp && [
    interp.tests.length ? `tests: ${interp.tests.join(', ')}` : '',
    interp.since ? `from ${formatDate(interp.since)}` : '',
    interp.until ? `until ${formatDate(interp.until)}` : '',
    interp.flags.length ? `printed flags: ${interp.flags.join(', ')}` : '',
    interp.report_types.length ? `document types: ${interp.report_types.join(', ')}` : '',
  ].filter(Boolean).join(' · ');

  return (
    <div className="space-y-6">
      {/* NL Search Bar */}
      <Card>
        <CardHeader title="Health Search" subtitle="Search your medical records with structured filters or natural language" icon={<Search className="h-4.5 w-4.5" />} />
        <div className="px-5 pb-5">
          <div className="relative">
            <Sparkles className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-teal-500" />
            <input
              type="text"
              value={nlQuery}
              onChange={(e) => setNlQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleNlSearch()}
              data-testid="health-search-input"
              placeholder='Try: "Show HbA1c results from the last two years"'
              className="input pl-9"
            />
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {exampleQueries.map((q) => (
              <button
                key={q}
                onClick={() => { setNlQuery(q); }}
                disabled={isSearching}
                className="rounded-full border border-neutral-200 px-2.5 py-1 text-xs text-neutral-500 hover:border-teal-400 hover:text-teal-600 dark:border-neutral-700 dark:text-neutral-400 dark:hover:border-teal-700 disabled:opacity-50"
              >
                {q}
              </button>
            ))}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button onClick={handleNlSearch} disabled={isSearching} className="btn btn-secondary px-3 py-1.5 text-xs" data-testid="health-search-submit">
              {isSearching ? 'Searching…' : 'Search'}
            </button>
            {searchResult && (
              <button onClick={() => { setSearchResult(null); setNlQuery(''); }} className="text-xs text-neutral-500 hover:underline">Clear search</button>
            )}
          </div>
          {searchResult && (
            <p className="mt-2 text-xs text-neutral-500" data-testid="health-search-interpretation">
              {interpText ? `Searched your confirmed records for ${interpText}.` : 'Searched report titles, laboratories and test names.'}
            </p>
          )}
          {searchError && <p className="mt-2 text-xs text-error-600" role="alert">{searchError}</p>}
          <p className="mt-2 text-xs text-neutral-400">
            Search runs on this server over your own confirmed records only. Results are existing records with their source report — nothing is generated.
          </p>
        </div>
      </Card>

      {/* Structured Filters */}
      <Card>
        <div className="p-4">
          <FilterBar searchValue={search} onSearchChange={setSearch} searchPlaceholder="Search by report title...">
            <SelectFilter label="Type" value={typeFilter} options={reportTypes.map(t => ({ value: t, label: t }))} onChange={setTypeFilter} />
            <SelectFilter label="Source" value={hospitalFilter} options={hospitals.map(h => ({ value: h, label: h }))} onChange={setHospitalFilter} />
            <SelectFilter label="Test" value={testNameFilter} options={testNames.map(t => ({ value: t, label: t }))} onChange={setTestNameFilter} />
            <SelectFilter label="Flag" value={flagFilter} options={(['All', 'high', 'low', 'abnormal', 'normal', 'unknown'] as const).map(f => ({ value: f, label: f === 'All' ? 'All' : flagLabels[f] }))} onChange={setFlagFilter} />
            <SelectFilter label="Status" value={statusFilter} options={(['All', 'processing', 'needs_review', 'confirmed', 'completed', 'failed'] as const).map(s => ({ value: s, label: s === 'All' ? 'All' : reportStatusLabels[s] }))} onChange={setStatusFilter} />
          </FilterBar>
        </div>
      </Card>

      {/* Results */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Matching Reports */}
        <Card>
          <CardHeader title="Matching Reports" subtitle={`${matchingReports.length} found`} icon={<FileText className="h-4.5 w-4.5" />} />
          <div className="divide-y divide-neutral-100 dark:divide-neutral-800">
            {matchingReports.length === 0 ? (
              <NoResultsState message="No reports match your filters." />
            ) : (
              matchingReports.map((report) => (
                <button
                  key={report.id}
                  onClick={() => onSelectReport(report.id)}
                  className="flex w-full flex-col gap-1 px-5 py-3 text-left hover:bg-neutral-50 dark:hover:bg-neutral-800/50"
                >
                  <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{report.title}</p>
                  <p className="text-xs text-neutral-500 dark:text-neutral-400">{report.type} · {report.source} · {formatDate(report.date)} · {reportStatusLabels[report.status]}</p>
                </button>
              ))
            )}
          </div>
        </Card>

        {/* Matching Measurements */}
        <Card>
          <CardHeader title="Measurement Results" subtitle={`${matchingMeasurements.length} found`} icon={<Link2 className="h-4.5 w-4.5" />} />
          <div className="overflow-x-auto">
            {matchingMeasurements.length === 0 ? (
              <NoResultsState message="No measurements match your filters." />
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-neutral-200 dark:border-neutral-800">
                    <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Test</th>
                    <th className="px-3 py-2 text-right text-xs font-medium text-neutral-500">Value</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Range</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Flag</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Date</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Source report</th>
                  </tr>
                </thead>
                <tbody>
                  {matchingMeasurements.map((m) => (
                    <tr key={m.id} className="border-b border-neutral-100 dark:border-neutral-800/50" data-testid="search-measurement-row">
                      <td className="px-3 py-2 text-xs text-neutral-700 dark:text-neutral-300">{m.testName}</td>
                      <td className="px-3 py-2 text-right text-xs font-medium text-neutral-900 dark:text-neutral-100">{m.value} {m.unit}</td>
                      <td className="px-3 py-2 text-xs text-neutral-400">{m.referenceRange || 'Not printed'}</td>
                      <td className="px-3 py-2"><StatusBadge variant={flagVariant(m.flag)}>{flagLabels[m.flag] ?? m.flag}</StatusBadge></td>
                      <td className="px-3 py-2 text-xs text-neutral-400">{formatDate(m.reportDate)}</td>
                      <td className="px-3 py-2 text-xs">
                        {m.reportId && reportTitles.has(m.reportId) ? (
                          <button onClick={() => onSelectReport(m.reportId)} className="text-teal-600 hover:underline dark:text-teal-400">
                            {reportTitles.get(m.reportId)}{m.sourceLocation ? ` · ${m.sourceLocation}` : ''}
                          </button>
                        ) : <span className="text-neutral-400">Entered manually</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Card>
      </div>

      {/* Source References */}
      <Card>
        <CardHeader title="Source References" subtitle={`${matchingRefs.length} references`} icon={<MessageSquare className="h-4.5 w-4.5" />} />
        <div className="p-5">
          {matchingRefs.length === 0 ? (
            <NoResultsState message="No source references for the current results." />
          ) : (
            <SourceReferenceList references={matchingRefs} />
          )}
        </div>
      </Card>
    </div>
  );
}
