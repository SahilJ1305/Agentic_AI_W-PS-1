import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, ShieldCheck, Zap, Sparkles, LayoutDashboard } from 'lucide-react';

const LandingPage = () => {
  return (
    <div className="min-h-screen flex flex-col bg-slate-50 text-slate-800">
      
      {/* --- Navigation Header --- */}
      <nav className="w-full max-w-7xl mx-auto flex items-center justify-between px-6 py-5">
        <div className="flex items-center gap-2">
          <div className="bg-blue-600 text-white p-2 rounded-xl shadow-md shadow-blue-500/20">
            <Sparkles className="h-5 w-5" />
          </div>
          <span className="text-xl font-bold tracking-tight text-slate-900">AppPortal</span>
        </div>

        <div className="flex items-center gap-4">
          <Link
            to="/login"
            className="px-5 py-2.5 text-sm font-semibold text-slate-700 hover:text-blue-600 transition-colors"
          >
            Log In
          </Link>
          <Link
            to="/signup"
            className="px-5 py-2.5 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-xl transition-all shadow-md shadow-blue-500/20 hover:shadow-lg"
          >
            Get Started
          </Link>
        </div>
      </nav>

      {/* --- Hero Section --- */}
      <main className="flex-1 flex flex-col items-center justify-center text-center px-6 pt-12 pb-20 max-w-5xl mx-auto">
        <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-blue-50 text-blue-600 border border-blue-100 text-xs font-semibold mb-6">
          <Sparkles className="w-3.5 h-3.5" /> Fast & Secure Authentication Platform
        </div>

        <h1 className="text-4xl sm:text-6xl font-extrabold text-slate-900 tracking-tight leading-tight mb-6">
          Streamline your workflow with <span className="text-blue-600">modern tools.</span>
        </h1>

        <p className="text-lg text-slate-600 max-w-2xl mb-10 leading-relaxed">
          Access your personal workspace, manage account configurations, and review analytics with real-time speed.
        </p>

        {/* --- Primary Call To Action --- */}
        <div className="flex flex-col sm:flex-row gap-4 w-full sm:w-auto">
          <Link
            to="/login"
            className="px-8 py-4 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl shadow-lg shadow-blue-500/30 transition-all flex items-center justify-center gap-2 group text-base"
          >
            Go to Login Page
            <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
          </Link>

          <Link
            to="/signup"
            className="px-8 py-4 bg-white hover:bg-slate-100 text-slate-700 font-bold border border-slate-200 rounded-xl transition-colors flex items-center justify-center text-base"
          >
            Create an Account
          </Link>
        </div>

        {/* --- Feature Grid Preview --- */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 mt-20 w-full text-left">
          <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-xs">
            <div className="bg-blue-50 text-blue-600 w-10 h-10 rounded-xl flex items-center justify-center mb-4">
              <Zap className="w-5 h-5" />
            </div>
            <h3 className="font-bold text-slate-900 mb-1">Instant Access</h3>
            <p className="text-sm text-slate-500">Sign in securely using token-based authentication session storage.</p>
          </div>

          <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-xs">
            <div className="bg-blue-50 text-blue-600 w-10 h-10 rounded-xl flex items-center justify-center mb-4">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <h3 className="font-bold text-slate-900 mb-1">Password Recovery</h3>
            <p className="text-sm text-slate-500">Built-in 6-digit OTP verification flow for resetting lost credentials.</p>
          </div>

          <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-xs">
            <div className="bg-blue-50 text-blue-600 w-10 h-10 rounded-xl flex items-center justify-center mb-4">
              <LayoutDashboard className="w-5 h-5" />
            </div>
            <h3 className="font-bold text-slate-900 mb-1">Unified Dashboard</h3>
            <p className="text-sm text-slate-500">View performance metrics and platform activities in real-time.</p>
          </div>
        </div>
      </main>

      {/* --- Simple Footer --- */}
      <footer className="border-t border-slate-200 py-6 text-center text-xs text-slate-400">
        &copy; {new Date().getFullYear()} AppPortal. All rights reserved.
      </footer>
    </div>
  );
};

export default LandingPage;