import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, ShieldCheck, Zap, Sparkles, LayoutDashboard } from 'lucide-react';

const LandingPage = () => {
  return (
    <div className="min-h-screen flex flex-col bg-white text-slate-800">
      
      {/* --- Blue Core Top Navigation Header --- */}
      <header className="bg-gradient-to-r from-blue-700 via-blue-600 to-indigo-700 text-white shadow-md shadow-blue-900/10 border-b border-blue-500/30 sticky top-0 z-30">
        <nav className="w-full max-w-7xl mx-auto flex items-center justify-between px-4 sm:px-6 py-3.5">
          <div className="flex items-center gap-3">
            <div className="bg-white text-blue-600 p-2 rounded-xl shadow-sm ring-2 ring-white/20">
              <Sparkles className="h-5 w-5" />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xl font-extrabold tracking-tight text-white">Cadence</span>
              <span className="text-[10px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded bg-blue-500/40 text-blue-100 border border-blue-400/30">AI</span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <Link
              to="/login"
              className="px-4 py-2 text-sm font-semibold text-blue-100 hover:text-white hover:bg-white/10 rounded-xl transition-all"
            >
              Log In
            </Link>
            <Link
              to="/signup"
              className="px-4 py-2 text-sm font-bold text-blue-700 bg-white hover:bg-blue-50 rounded-xl transition-all shadow-sm hover:shadow hover:scale-[1.02] active:scale-[0.98]"
            >
              Get Started
            </Link>
          </div>
        </nav>
      </header>

      {/* --- Hero Section (White Theme) --- */}
      <main className="flex-1 flex flex-col items-center justify-center text-center px-4 sm:px-6 pt-16 pb-20 max-w-5xl mx-auto">
        <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200/70 text-xs font-semibold mb-6 shadow-2xs">
          <Sparkles className="w-3.5 h-3.5 text-blue-600" /> AI Group Project Coordinator
        </div>

        <h1 className="text-4xl sm:text-6xl font-extrabold text-slate-900 tracking-tight leading-[1.12] mb-6 max-w-4xl">
          Stop chasing your team <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-600 to-indigo-600">for updates.</span>
        </h1>

        <p className="text-lg sm:text-xl text-slate-600 max-w-2xl mb-10 leading-relaxed font-normal">
          Cadence checks in with each teammate on Telegram, reads their replies, and keeps the task board current.
        </p>

        {/* --- Primary Call To Action --- */}
        <div className="flex flex-col sm:flex-row gap-3.5 w-full sm:w-auto">
          <Link
            to="/login"
            className="px-7 py-3.5 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl shadow-md shadow-blue-500/25 hover:shadow-lg hover:shadow-blue-500/35 transition-all flex items-center justify-center gap-2 group text-base hover:scale-[1.02] active:scale-[0.98]"
          >
            Go to Login Page
            <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
          </Link>

          <Link
            to="/signup"
            className="px-7 py-3.5 bg-white hover:bg-slate-50 text-slate-700 font-bold border border-slate-300 rounded-xl shadow-2xs transition-all flex items-center justify-center text-base hover:border-slate-400"
          >
            Create an Account
          </Link>
        </div>

        {/* --- Feature Grid Preview --- */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 mt-20 w-full text-left">
          <div className="bg-white p-6 sm:p-7 rounded-2xl border border-slate-200/90 shadow-xs transition-all hover:-translate-y-1 hover:shadow-md hover:border-blue-200">
            <div className="bg-blue-50 text-blue-600 ring-1 ring-blue-100 w-11 h-11 rounded-xl flex items-center justify-center mb-4">
              <Zap className="w-5 h-5" />
            </div>
            <h3 className="font-bold text-slate-900 mb-1.5 text-base">Follow-ups on Telegram</h3>
            <p className="text-sm text-slate-500 leading-relaxed">One check-in per teammate covering the tasks they own, without endless meetings.</p>
          </div>

          <div className="bg-white p-6 sm:p-7 rounded-2xl border border-slate-200/90 shadow-xs transition-all hover:-translate-y-1 hover:shadow-md hover:border-blue-200">
            <div className="bg-blue-50 text-blue-600 ring-1 ring-blue-100 w-11 h-11 rounded-xl flex items-center justify-center mb-4">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <h3 className="font-bold text-slate-900 mb-1.5 text-base">Blocked, not “done”</h3>
            <p className="text-sm text-slate-500 leading-relaxed">“Connected, but waiting for credentials” is recorded as a blocker automatically.</p>
          </div>

          <div className="bg-white p-6 sm:p-7 rounded-2xl border border-slate-200/90 shadow-xs transition-all hover:-translate-y-1 hover:shadow-md hover:border-blue-200">
            <div className="bg-blue-50 text-blue-600 ring-1 ring-blue-100 w-11 h-11 rounded-xl flex items-center justify-center mb-4">
              <LayoutDashboard className="w-5 h-5" />
            </div>
            <h3 className="font-bold text-slate-900 mb-1.5 text-base">Live board</h3>
            <p className="text-sm text-slate-500 leading-relaxed">Every change shows up with the reason it happened, with zero manual data entry.</p>
          </div>
        </div>
      </main>

      {/* --- Footer --- */}
      <footer className="border-t border-slate-200/80 bg-slate-50/50 py-8 text-center text-xs text-slate-500">
        <div className="max-w-7xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-2">
          <span>&copy; {new Date().getFullYear()} Cadence. AI Group Project Coordinator.</span>
          <span className="text-slate-400">Pristine light workspace</span>
        </div>
      </footer>
    </div>
  );
};

export default LandingPage;