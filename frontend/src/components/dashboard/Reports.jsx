import React, { useCallback, useEffect, useState } from 'react';
import {
  FileText, ShieldAlert, Download, Send, RefreshCw, FileDown, AlertTriangle,
  Copy, Check, Eye, Code, MessageSquare, ArrowRight, CheckCircle2,
} from 'lucide-react';
import { cadence } from '../../api/cadence';
import { toast } from '../../hooks/useToastStore';
import { copyText, downloadText, primaryButton, secondaryButton, slug, timeAgo, shortDate } from './helpers';
import { Chip, ErrorNote, LoadingBlock, Panel, Spinner } from './ui';
import Markdown from './Markdown';

const KINDS = {
  digest: {
    title: 'Daily Digest Report',
    icon: FileText,
    blurb: 'Executive progress overview, tasks completed, active work in progress, and open blockers.',
  },
  risk: {
    title: 'Risk & Vulnerability Assessment',
    icon: ShieldAlert,
    blurb: 'Automated audit of critical path dependencies, upcoming deadlines, and proactive mitigation steps.',
  },
};

const ReportCard = ({ pid, projectName, kind, reportTick }) => {
  const meta = KINDS[kind];
  const [report, setReport] = useState(undefined); // undefined = loading, null = none yet
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null); // 'generate' | 'post'
  const [viewMode, setViewMode] = useState('doc'); // 'doc' | 'raw' | 'tg'
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    try {
      setReport(await cadence.latestReport(pid, kind));
      setError(null);
    } catch (err) {
      setError(err.message);
      setReport((prev) => (prev === undefined ? null : prev));
    }
  }, [pid, kind]);

  useEffect(() => {
    load();
  }, [load, reportTick]);

  const generate = async (post) => {
    setBusy(post ? 'post' : 'generate');
    try {
      const result = await cadence.generateReport(pid, kind, post);
      setReport(result);
      setError(null);
      toast.success(
        post
          ? (result.posted ? `${meta.title} posted to Telegram.` : `${meta.title} generated, but it could not be posted to Telegram.`)
          : `${meta.title} generated.`,
      );
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(null);
    }
  };

  const handleCopy = async () => {
    const textToCopy = viewMode === 'tg' ? (report?.telegram_html || report?.content_md) : report?.content_md;
    if (!textToCopy) return;
    const ok = await copyText(textToCopy);
    if (ok) {
      setCopied(true);
      toast.success('Report copied to clipboard.');
      setTimeout(() => setCopied(false), 2000);
    } else {
      toast.error('Could not copy to clipboard.');
    }
  };

  const downloadReport = () => {
    if (!report?.content_md) return;
    downloadText(`${slug(projectName)}-${kind}-report.md`, report.content_md);
    toast.success('Report downloaded.');
  };

  return (
    <Panel
      icon={meta.icon}
      title={meta.title}
      className="border-slate-200/90 shadow-xs"
      actions={report?.created_at && (
        <div className="flex items-center gap-2">
          {report.posted && <Chip tone="green">Telegram posted</Chip>}
          <span className="text-xs font-semibold text-slate-400">{timeAgo(report.created_at)}</span>
        </div>
      )}
    >
      <p className="text-xs text-slate-500 mb-4 leading-relaxed">{meta.blurb}</p>

      {/* Action Buttons */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <button
          type="button"
          disabled={Boolean(busy)}
          onClick={() => generate(false)}
          className={`${primaryButton} !py-2 !px-3.5 text-xs`}
        >
          {busy === 'generate' ? <Spinner className="w-3.5 h-3.5 !text-white" /> : <RefreshCw className="w-3.5 h-3.5" />}
          Generate Structured Report
        </button>

        <button
          type="button"
          disabled={Boolean(busy)}
          onClick={() => generate(true)}
          className={`${secondaryButton} !py-2 !px-3.5 text-xs`}
        >
          {busy === 'post' ? <Spinner className="w-3.5 h-3.5" /> : <Send className="w-3.5 h-3.5 text-blue-600" />}
          Generate & Post to Telegram
        </button>

        {report?.content_md && (
          <div className="flex items-center gap-1.5 ml-auto">
            <button
              type="button"
              onClick={handleCopy}
              className={`${secondaryButton} !py-2 !px-3 text-xs`}
              title="Copy to clipboard"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5 text-slate-500" />}
              <span>{copied ? 'Copied' : 'Copy'}</span>
            </button>
            <button
              type="button"
              onClick={downloadReport}
              className={`${secondaryButton} !py-2 !px-3 text-xs`}
              title="Download Markdown"
            >
              <Download className="w-3.5 h-3.5 text-slate-500" />
              <span>Download</span>
            </button>
          </div>
        )}
      </div>

      <ErrorNote>{error}</ErrorNote>
      {report === undefined && <LoadingBlock label="Loading latest structured report…" />}
      {report === null && !error && (
        <div className="bg-slate-50/70 border border-dashed border-slate-200 rounded-2xl p-8 text-center my-2">
          <meta.icon className="w-8 h-8 text-slate-300 mx-auto mb-2.5" />
          <p className="text-sm font-bold text-slate-700">No {meta.title.toLowerCase()} generated yet</p>
          <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">
            Click "Generate Structured Report" above to compile project tasks, blockers, and timelines into an executive briefing.
          </p>
        </div>
      )}

      {report && (
        <div className="space-y-2 mt-3">
          {/* View mode toggle */}
          <div className="flex items-center justify-between border-b border-slate-200/80 pb-2">
            <div className="inline-flex gap-1 bg-slate-100 p-1 rounded-xl text-xs font-semibold">
              <button
                type="button"
                onClick={() => setViewMode('doc')}
                className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-lg transition-all ${
                  viewMode === 'doc' ? 'bg-white text-blue-700 shadow-xs font-bold' : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                <Eye className="w-3.5 h-3.5" /> Structured Document
              </button>
              <button
                type="button"
                onClick={() => setViewMode('raw')}
                className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-lg transition-all ${
                  viewMode === 'raw' ? 'bg-white text-blue-700 shadow-xs font-bold' : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                <Code className="w-3.5 h-3.5" /> Raw Markdown
              </button>
              {report.telegram_html && (
                <button
                  type="button"
                  onClick={() => setViewMode('tg')}
                  className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-lg transition-all ${
                    viewMode === 'tg' ? 'bg-white text-blue-700 shadow-xs font-bold' : 'text-slate-500 hover:text-slate-800'
                  }`}
                >
                  <MessageSquare className="w-3.5 h-3.5" /> Telegram Preview
                </button>
              )}
            </div>
            <span className="text-[11px] font-semibold text-slate-400">
              {shortDate(report.created_at)}
            </span>
          </div>

          {/* Content container */}
          <div className="border border-slate-200/90 rounded-2xl p-5 bg-white shadow-2xs max-h-[30rem] overflow-y-auto">
            {viewMode === 'doc' && <Markdown source={report.content_md} />}
            {viewMode === 'raw' && (
              <pre className="text-xs font-mono text-slate-800 whitespace-pre-wrap leading-relaxed select-all bg-slate-50/70 p-4 rounded-xl border border-slate-200/70">
                {report.content_md}
              </pre>
            )}
            {viewMode === 'tg' && (
              <div className="bg-sky-50/30 border border-sky-100 rounded-xl p-4 text-xs font-sans text-slate-800 space-y-2">
                <div className="flex items-center gap-1.5 text-sky-700 font-bold mb-2">
                  <Send className="w-3.5 h-3.5" /> Dispatched Telegram Message Format
                </div>
                <div
                  className="whitespace-pre-wrap font-sans text-slate-700 leading-relaxed"
                  dangerouslySetInnerHTML={{ __html: report.telegram_html }}
                />
              </div>
            )}
          </div>
        </div>
      )}
    </Panel>
  );
};

const ExportPreview = ({ pid, projectName }) => {
  const [text, setText] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setText(await cadence.exportMarkdown(pid));
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [pid]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <Panel
      icon={FileDown}
      title="Living Task Document (export.md)"
      className="border-slate-200/90 shadow-xs"
      actions={(
        <div className="flex gap-2">
          <button type="button" onClick={load} disabled={loading} className={`${secondaryButton} !py-1.5 !px-3 text-xs`}>
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </button>
          <button
            type="button"
            disabled={!text}
            onClick={() => downloadText(`${slug(projectName)}-status.md`, text)}
            className={`${primaryButton} !py-1.5 !px-3 text-xs`}
          >
            <Download className="w-3.5 h-3.5" /> Download .md
          </button>
        </div>
      )}
    >
      <p className="text-xs text-slate-500 mb-3.5">
        Complete operational snapshot including all tasks, owners, critical path, open blockers, and recent event logs.
      </p>
      <ErrorNote>{error}</ErrorNote>
      {loading && text === null && <LoadingBlock label="Building export document…" />}
      {text !== null && (
        <div className="border border-slate-200/90 rounded-2xl p-5 bg-white shadow-2xs max-h-[30rem] overflow-y-auto">
          <Markdown source={text} />
        </div>
      )}
    </Panel>
  );
};

const RiskList = ({ risks, onOpenTaskByKey }) => (
  <Panel icon={AlertTriangle} title={`Current Risk Register (${risks.length})`} className="border-slate-200/90 shadow-xs">
    {risks.length === 0 ? (
      <div className="p-4 bg-emerald-50/60 border border-emerald-100 rounded-xl flex items-center gap-2.5 text-emerald-800 text-sm font-medium">
        <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
        <span>No project risks flagged at this time. All critical path items and deadlines are healthy.</span>
      </div>
    ) : (
      <ul className="divide-y divide-slate-100">
        {risks.map((risk, i) => (
          <li key={`${risk.task_key}-${i}`} className="py-3.5 flex items-start gap-3.5 hover:bg-slate-50/60 p-2 rounded-xl transition-colors">
            <span className={`mt-1.5 w-2.5 h-2.5 rounded-full shrink-0 ${risk.level === 'high' ? 'bg-red-500 ring-2 ring-red-200' : 'bg-amber-400 ring-2 ring-amber-200'}`} />
            <div className="min-w-0 text-sm flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => onOpenTaskByKey(risk.task_key)}
                  className="font-bold text-slate-900 hover:text-blue-600 text-left font-mono text-xs bg-slate-100 px-1.5 py-0.5 rounded border border-slate-200/60"
                >
                  {risk.task_key}
                </button>
                <span className="font-semibold text-slate-800">{risk.task_title}</span>
                <span className="text-xs text-slate-400">
                  {risk.owner_name ? ` · ${risk.owner_name}` : ' · unassigned'}
                </span>
                <Chip tone={risk.level === 'high' ? 'red' : 'amber'}>{risk.level} priority</Chip>
              </div>
              <p className="text-slate-600 text-xs mt-1.5 leading-relaxed">{risk.why}</p>
              {risk.action && (
                <div className="mt-2 bg-blue-50/70 border border-blue-100 rounded-lg p-2 text-blue-800 text-xs flex items-center gap-1.5 font-medium">
                  <ArrowRight className="w-3.5 h-3.5 text-blue-600 shrink-0" />
                  <span><strong>Recommended Mitigation:</strong> {risk.action}</span>
                </div>
              )}
            </div>
          </li>
        ))}
      </ul>
    )}
  </Panel>
);

const Reports = ({ pid, projectName, risks = [], reportTick, onOpenTaskByKey }) => (
  <div className="space-y-5">
    {/* Executive Station Header Banner */}
    <div className="bg-gradient-to-r from-blue-50/80 via-white to-slate-50/80 border border-blue-100/80 rounded-3xl p-5 sm:p-6 shadow-xs flex flex-wrap items-center justify-between gap-4">
      <div className="flex items-center gap-3.5">
        <div className="w-11 h-11 rounded-2xl bg-blue-600 text-white flex items-center justify-center shadow-md shadow-blue-500/20 font-bold">
          <FileText className="w-5 h-5" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-slate-900 leading-tight">Executive Report Station</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Compile structured operational briefings, audit project health, and export deliverables.
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <span className={`inline-flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-xl border shadow-2xs ${
          risks.length > 0 ? 'bg-amber-50 text-amber-800 border-amber-200' : 'bg-emerald-50 text-emerald-800 border-emerald-200'
        }`}>
          {risks.length > 0 ? <AlertTriangle className="w-3.5 h-3.5 text-amber-600" /> : <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />}
          {risks.length} Risk{risks.length === 1 ? '' : 's'} Identified
        </span>
      </div>
    </div>

    <div className="grid grid-cols-1 xl:grid-cols-2 gap-5 items-start">
      <ReportCard pid={pid} projectName={projectName} kind="digest" reportTick={reportTick} />
      <ReportCard pid={pid} projectName={projectName} kind="risk" reportTick={reportTick} />
    </div>

    <RiskList risks={risks} onOpenTaskByKey={onOpenTaskByKey} />
    <ExportPreview pid={pid} projectName={projectName} />
  </div>
);

export default Reports;
