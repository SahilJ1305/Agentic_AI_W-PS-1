import React, { useCallback, useEffect, useState } from 'react';
import { FileText, ShieldAlert, Download, Send, RefreshCw, FileDown, AlertTriangle } from 'lucide-react';
import { cadence } from '../../api/cadence';
import { toast } from '../../hooks/useToastStore';
import { downloadText, primaryButton, secondaryButton, slug, timeAgo } from './helpers';
import { Chip, ErrorNote, LoadingBlock, Panel, Spinner } from './ui';
import Markdown from './Markdown';

const KINDS = {
  digest: { title: 'Daily digest', icon: FileText, blurb: 'What moved, what is blocked, and what is next.' },
  risk: { title: 'Risk report', icon: ShieldAlert, blurb: 'Where the plan is most likely to slip, and what to do about it.' },
};

const ReportCard = ({ pid, kind, reportTick }) => {
  const meta = KINDS[kind];
  const [report, setReport] = useState(undefined); // undefined = loading, null = none yet
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null); // 'generate' | 'post'

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
      toast.success(post
        ? (result.posted ? `${meta.title} posted to Telegram.` : `${meta.title} generated, but it could not be posted to Telegram.`)
        : `${meta.title} generated.`);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Panel
      icon={meta.icon}
      title={meta.title}
      actions={report?.created_at && (
        <span className="text-xs text-slate-400 flex items-center gap-2">
          {report.posted && <Chip tone="green">posted</Chip>}
          {timeAgo(report.created_at)}
        </span>
      )}
    >
      <p className="text-xs text-slate-500 mb-3">{meta.blurb}</p>
      <div className="flex flex-wrap gap-2 mb-4">
        <button type="button" disabled={Boolean(busy)} onClick={() => generate(false)} className={secondaryButton}>
          {busy === 'generate' ? <Spinner className="w-4 h-4" /> : <RefreshCw className="w-4 h-4" />} Generate
        </button>
        <button type="button" disabled={Boolean(busy)} onClick={() => generate(true)} className={primaryButton}>
          {busy === 'post' ? <Spinner className="w-4 h-4 !text-white" /> : <Send className="w-4 h-4" />} Generate and post to Telegram
        </button>
      </div>
      <ErrorNote>{error}</ErrorNote>
      {report === undefined && <LoadingBlock label="Loading latest report…" />}
      {report === null && !error && (
        <p className="text-sm text-slate-400">No {meta.title.toLowerCase()} yet. Generate one to see it here.</p>
      )}
      {report && (
        <div className="border border-slate-100 rounded-xl p-4 bg-slate-50/50 max-h-[28rem] overflow-y-auto">
          <Markdown source={report.content_md} />
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
      title="Living task doc (export.md)"
      actions={(
        <div className="flex gap-2">
          <button type="button" onClick={load} disabled={loading} className={secondaryButton}>
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
          <button
            type="button"
            disabled={!text}
            onClick={() => downloadText(`${slug(projectName)}-status.md`, text)}
            className={primaryButton}
          >
            <Download className="w-4 h-4" /> Download .md
          </button>
        </div>
      )}
    >
      <ErrorNote>{error}</ErrorNote>
      {loading && text === null && <LoadingBlock label="Building export…" />}
      {text !== null && (
        <div className="border border-slate-100 rounded-xl p-4 bg-slate-50/50 max-h-[28rem] overflow-y-auto">
          <Markdown source={text} />
        </div>
      )}
    </Panel>
  );
};

const RiskList = ({ risks, onOpenTaskByKey }) => (
  <Panel icon={AlertTriangle} title={`Current risks (${risks.length})`}>
    {risks.length === 0 ? (
      <p className="text-sm text-slate-400">No risks flagged right now.</p>
    ) : (
      <ul className="divide-y divide-slate-100">
        {risks.map((risk, i) => (
          <li key={`${risk.task_key}-${i}`} className="py-3 flex gap-3">
            <span className={`mt-1.5 w-2.5 h-2.5 rounded-full shrink-0 ${risk.level === 'high' ? 'bg-red-500' : 'bg-amber-400'}`} />
            <div className="min-w-0 text-sm">
              <button type="button" onClick={() => onOpenTaskByKey(risk.task_key)} className="font-semibold text-slate-900 hover:text-blue-600 text-left">
                {risk.task_key} · {risk.task_title}
              </button>
              <span className="text-xs text-slate-400">{risk.owner_name ? ` · ${risk.owner_name}` : ' · unassigned'} · {risk.level}</span>
              <p className="text-slate-600">{risk.why}</p>
              {risk.action && <p className="text-blue-700 text-xs mt-0.5">Suggested: {risk.action}</p>}
            </div>
          </li>
        ))}
      </ul>
    )}
  </Panel>
);

const Reports = ({ pid, projectName, risks, reportTick, onOpenTaskByKey }) => (
  <div className="space-y-4">
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 items-start">
      <ReportCard pid={pid} kind="digest" reportTick={reportTick} />
      <ReportCard pid={pid} kind="risk" reportTick={reportTick} />
    </div>
    <RiskList risks={risks} onOpenTaskByKey={onOpenTaskByKey} />
    <ExportPreview pid={pid} projectName={projectName} />
  </div>
);

export default Reports;
