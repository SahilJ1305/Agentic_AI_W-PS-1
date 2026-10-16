import React, { useState } from "react";
import { Mail, Lock, ArrowLeft, Loader2, AlertCircle } from "lucide-react";
import { useNavigate, Link } from "react-router-dom";
import axios from 'axios';
import { API_BASE_URL } from "../../api/apiConfig";

const ForgotPasswordPage = () => {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSendOtp = async (e) => {
    e.preventDefault();
    
    if (!email || !/\S+@\S+\.\S+/.test(email)) {
      return setError("Please enter a valid email address");
    }

    setLoading(true);
    setError("");

    try {
      await axios.post(`${API_BASE_URL}/api/auth/forgot-password`, { email });
      // Only navigate if the email was found and OTP was sent
      navigate("/verify-otp", { state: { email } });
    } catch (err) {
      console.error(err);
      // Capture 404 or other backend errors
      setError(
        err.response?.data?.detail || "Failed to send OTP. Please try again."
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-slate-900">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-xl p-8 border border-slate-100">
        
        <div className="text-center mb-8">
          <div className="mx-auto bg-blue-50 p-3 rounded-2xl w-fit mb-4">
            <Lock className="h-8 w-8 text-blue-600" />
          </div>
          <h2 className="text-3xl font-extrabold text-slate-900">Reset Password</h2>
          <p className="text-slate-500 mt-2 text-sm">
            Enter your registered email to receive a verification code.
          </p>
        </div>

        <form onSubmit={handleSendOtp} className="space-y-6">
          <div>
            <label className="block text-sm font-medium text-slate-700">Email Address</label>
            <div className="relative mt-1">
              <Mail className="absolute left-3 top-3.5 h-5 w-5 text-slate-400" />
              <input
                type="email"
                className={`w-full pl-10 pr-3 py-3 border rounded-xl shadow-xs outline-none focus:ring-2 focus:ring-blue-500 transition-all ${
                  error ? "border-red-500 bg-red-50/20" : "border-slate-300"
                }`}
                placeholder="you@example.com"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  setError("");
                }}
                required
              />
            </div>
          </div>

          {/* --- Error Alert Box --- */}
          {error && (
            <div className="p-3.5 bg-red-50 border border-red-200 rounded-xl flex items-center gap-2.5 text-red-600 text-sm">
              <AlertCircle className="w-5 h-5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 text-white font-bold py-3 rounded-xl hover:bg-blue-700 transition-all shadow-md shadow-blue-500/20 flex items-center justify-center gap-2 disabled:opacity-70"
          >
            {loading ? <Loader2 className="animate-spin w-5 h-5" /> : "Send OTP Code"}
          </button>
        </form>

        <div className="text-center mt-6">
          <Link to="/login" className="text-sm font-semibold text-blue-600 hover:underline inline-flex items-center gap-1.5">
            <ArrowLeft className="w-4 h-4" /> Back to Login
          </Link>
        </div>

      </div>
    </div>
  );
};

export default ForgotPasswordPage;