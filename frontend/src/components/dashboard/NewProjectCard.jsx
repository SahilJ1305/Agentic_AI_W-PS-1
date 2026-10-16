import React, { useState } from 'react';
import { Upload } from 'lucide-react';
import { cadence } from '../../api/cadence';
import { toast } from '../../hooks/useToastStore';
import { inputClass, primaryButton } from './helpers';
import { Spinner } from './ui';

const NewProjectCard = ({ onCreated }) => {
  const [name, setName] = useState('');
  const [spec, setSpec] = useState(null);
  const [taskDoc, setTaskDoc] = useState(null);
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState('');

  const submit = async (e) => {
    e.preventDefault();
    if (!spec) {
      toast.error('Choose a Markdown spec file first.');
      return;
    }
    const form = e.target;
    setBusy(true);
    try {
      setStep('Creating project…');
      const project = await cadence.createProject(name.trim() || spec.name.replace(/\.[^.]+$/, ''));
      setStep('Uploading spec…');
      const result = await cadence.uploadDocument(project.id, 'spec', spec);
      let imported = result.imported?.tasks;
      if (taskDoc) {
        setStep('Uploading task doc…');
        const second = await cadence.uploadDocument(project.id, 'task_doc', taskDoc);
        imported = second.imported?.tasks ?? imported;
      }
      toast.success(
        imported
          ? `Created ${project.name} with ${imported} tasks.`
          : `Created ${project.name}. The planner is drafting tasks. Review them in the Plan tab.`,
      );
      setName('');
      setSpec(null);
      setTaskDoc(null);
      form.reset();
      await onCreated(project.id);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
      setStep('');
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <label className="block text-xs font-medium text-slate-600">
        Project name
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Defaults to the file name" className={`${inputClass} mt-1`} />
      </label>
      <label className="block text-xs font-medium text-slate-600">
        Project spec (Markdown)
        <input
          type="file"
          accept=".md,.markdown,.txt"
          required
          onChange={(e) => setSpec(e.target.files?.[0] || null)}
          className="mt-1 block w-full text-sm text-slate-600 file:mr-3 file:rounded-lg file:border-0 file:bg-blue-50 file:px-3 file:py-1.5 file:text-sm file:font-semibold file:text-blue-700"
        />
      </label>
      <label className="block text-xs font-medium text-slate-600">
        Task doc (optional, a table of tasks to import as-is)
        <input
          type="file"
          accept=".md,.markdown,.txt"
          onChange={(e) => setTaskDoc(e.target.files?.[0] || null)}
          className="mt-1 block w-full text-sm text-slate-600 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-sm file:font-semibold file:text-slate-700"
        />
      </label>
      <button type="submit" disabled={busy} className={`${primaryButton} w-full`}>
        {busy ? <Spinner className="w-4 h-4 !text-white" /> : <Upload className="w-4 h-4" />}
        {busy ? step || 'Working…' : 'Create project'}
      </button>
    </form>
  );
};

export default NewProjectCard;
