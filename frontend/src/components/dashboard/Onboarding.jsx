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
  <div className="max-w-5xl mx-auto px-4 sm:px-6 py-8 grid grid-cols-1 lg:grid-cols-[1fr_380px] gap-6 items-start">
    <section className="bg-white border border-slate-200 rounded-2xl p-6 sm:p-8">
      <h2 className="text-lg font-bold text-slate-900">How Cadence works</h2>
      <p className="text-sm text-slate-500 mt-1 mb-5">
        Your team talks to a Telegram bot. This dashboard is where you see the result and stay in control.
      </p>
      <ol className="space-y-4">
        {STEPS.map(({ icon: Icon, title, text }, i) => (
          <li key={title} className="flex gap-3">
            <span className="flex items-center justify-center w-8 h-8 rounded-full bg-blue-50 text-blue-600 shrink-0">
              <Icon className="w-4 h-4" />
            </span>
            <div>
              <p className="text-sm font-semibold text-slate-900">{i + 1}. {title}</p>
              <p className="text-sm text-slate-500">{text}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>

    <section className="bg-white border border-slate-200 rounded-2xl p-6">
      <h2 className="text-lg font-bold text-slate-900">Start your first project</h2>
      <p className="text-sm text-slate-500 mt-1 mb-4">
        Upload a spec to create the project. You will get the Telegram invite links right after.
      </p>
      <NewProjectCard onCreated={onCreated} />
    </section>
  </div>
);

export default Onboarding;
