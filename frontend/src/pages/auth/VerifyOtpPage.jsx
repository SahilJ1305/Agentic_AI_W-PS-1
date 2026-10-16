import React, { useState, useRef, useEffect } from 'react';
import { ArrowLeft, Loader2, ShieldCheck } from 'lucide-react';
import { useNavigate, useLocation } from 'react-router-dom';
import axios from 'axios';
import { API_BASE_URL } from '../../api/apiConfig';

const VerifyOtpPage = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const email = location.state?.email;

  const OTP_LENGTH = 6;
  const otpRefs = useRef([]);
  const [otp, setOtp] = useState(Array(OTP_LENGTH).fill(''));
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!email) navigate('/forgot-password');
  }, [email, navigate]);

  const handleVerify = async () => {
    const otpString = otp.join('');
    if (otpString.length !== OTP_LENGTH) {
      return setError('Please enter the complete 6-digit code.');
    }

    setLoading(true);
    setError('');

    try {
      await axios.post(`${API_BASE_URL}/api/auth/verify-otp`, {
        email,
        otp: otpString,
      });
      navigate('/reset-password', { state: { email, otp: otpString } });
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid or expired OTP.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-gray-50">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-lg p-8 border border-gray-100">
        <button
          onClick={() => navigate('/forgot-password')}
          className="text-sm text-gray-500 hover:text-gray-700 flex items-center gap-2 mb-6"
        >
          <ArrowLeft className="h-4 w-4" /> Change Email
        </button>

        <div className="text-center mb-8">
          <div className="mx-auto bg-blue-100 p-3 rounded-xl w-fit mb-4">
            <ShieldCheck className="h-8 w-8 text-blue-600" />
          </div>
          <h2 className="text-3xl font-bold text-gray-900">Verify Code</h2>
          <p className="text-gray-500 mt-2 text-sm">
            Sent to <span className="font-semibold text-gray-900">{email}</span>
          </p>
        </div>

        <div className="flex justify-center gap-2 my-8">
          {otp.map((val, idx) => (
            <input
              key={idx}
              ref={(el) => (otpRefs.current[idx] = el)}
              maxLength={1}
              className={`w-12 h-14 text-center text-2xl font-bold bg-white border rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 text-gray-900 shadow-sm ${
                error ? 'border-red-500' : 'border-gray-300'
              }`}
              value={val}
              onChange={(e) => {
                const v = e.target.value.replace(/[^0-9]/g, '');
                const arr = [...otp];
                arr[idx] = v;
                setOtp(arr);
                if (v && idx < OTP_LENGTH - 1) otpRefs.current[idx + 1].focus();
                setError('');
              }}
              onKeyDown={(e) => {
                if (e.key === 'Backspace' && !otp[idx] && idx > 0) {
                  otpRefs.current[idx - 1].focus();
                }
              }}
            />
          ))}
        </div>

        {error && <p className="text-red-600 text-sm text-center mb-6 font-medium">{error}</p>}

        <button
          onClick={handleVerify}
          disabled={loading}
          className="w-full bg-blue-600 text-white font-bold py-3 rounded-lg hover:bg-blue-700 transition-all flex items-center justify-center gap-2 disabled:opacity-70"
        >
          {loading ? <Loader2 className="animate-spin w-5 h-5" /> : 'Verify Code'}
        </button>
      </div>
    </div>
  );
};

export default VerifyOtpPage;