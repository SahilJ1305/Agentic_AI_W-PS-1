import React from 'react';
import { FileText, UserPlus, Send, Radio } from 'lucide-react';
import NewProjectCard from './NewProjectCard';

const STEPS = [
  { icon: FileText, title: 'Upload your spec', text: 'A Markdown file describing the project, the team and the deliverables. Cadence stores the original and drafts tasks and dependencies from it.' },
  { icon: UserPlus, title: 'Review the plan', text: 'Open the Plan tab, adjust owners and dependencies, and commit. Teammates named in the spec are added automatically.' },
  { icon: Send, title: 'Invite everyone on Telegram', text: 'Each teammate gets a personal invite link and QR code in the Team tab. They open it and tap Start in Telegram. That connects their chat to their tasks.' },
  { icon: Radio, title: 'Watch it move', text: 'Teammates reply to the bot in plain language ("done with the login page", "blocked on the API key"). The board, graph and activity feed update live.' },
];

const Onboarding = ({ onCreated }) => (
  <div className="w-full px-4 sm:px-6 lg:px-8 xl:px-10 py-8 grid grid-cols-1 lg:grid-cols-[1fr_390px] xl:grid-cols-[1fr_420px] gap-6 items-start">
    <section className="bg-white border border-slate-200/90 rounded-3xl p-6 sm:p-8 shadow-xs">
      <div className="flex items-center gap-2 mb-1">
        <h2 className="text-xl font-bold text-slate-900">How Cadence works</h2>
        <span className="text-[11px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200/60">Overview</span>
      </div>
      <p className="text-sm text-slate-500 mb-6 leading-relaxed">
        Your team talks to a Telegram bot. This dashboard is where you see the real-time project pulse and stay in full control.
      </p>
      <ol className="space-y-4.5">
        {STEPS.map(({ icon: Icon, title, text }, i) => (
          <li key={title} className="flex items-start gap-3.5">
            <span className="flex items-center justify-center w-8 h-8 rounded-xl bg-blue-50 text-blue-600 ring-1 ring-blue-100/80 shrink-0 mt-0.5 shadow-2xs font-bold text-xs">
              {i + 1}
            </span>
            <div>
              <p className="text-sm font-bold text-slate-900 flex items-center gap-1.5">
                <Icon className="w-4 h-4 text-blue-600" /> {title}
              </p>
              <p className="text-sm text-slate-500 mt-0.5 leading-relaxed">{text}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>

    <section className="bg-white border border-slate-200/90 rounded-3xl p-6 sm:p-7 shadow-xs">
      <h2 className="text-xl font-bold text-slate-900 mb-1">Start your first project</h2>
      <p className="text-sm text-slate-500 mb-5 leading-relaxed">
        Upload a spec to create the project. You will get the Telegram invite links right after.
      </p>
      <NewProjectCard onCreated={onCreated} />
    </section>
  </div>
);

export default Onboarding;
