import React from 'react';
import { useAuthStore } from '../authStore';
import { 
  TrendingUp, 
  Users, 
  Activity, 
  ArrowUpRight, 
  ArrowDownRight,
  MoreHorizontal,
  Clock,
  LogOut
} from 'lucide-react';

/**
 * --- Stat Card Component ---
 */
const StatCard = ({ title, value, change, isPositive, icon: Icon, color }) => (
  <div className="bg-white p-6 rounded-2xl border border-gray-100 shadow-sm hover:shadow-md transition-shadow">
    <div className="flex justify-between items-start">
      <div>
        <p className="text-sm font-medium text-gray-500">{title}</p>
        <h3 className="text-2xl font-bold text-gray-900 mt-1">{value}</h3>
      </div>
      <div className={`p-3 rounded-xl ${color}`}>
        <Icon className="w-5 h-5 text-white" />
      </div>
    </div>
    <div className="flex items-center mt-4">
      <span className={`flex items-center text-sm font-medium ${isPositive ? 'text-green-600' : 'text-red-600'}`}>
        {isPositive ? <ArrowUpRight className="w-4 h-4 mr-1" /> : <ArrowDownRight className="w-4 h-4 mr-1" />}
        {change}
      </span>
      <span className="text-sm text-gray-400 ml-2">vs last month</span>
    </div>
  </div>
);

/**
 * --- Main Dashboard Page Component ---
 */
const DashboardPage = () => {
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);

  const userName = user?.full_name?.split(' ')[0] || user?.email?.split('@')[0] || 'User';

  // Sample data for the activity chart
  const chartData = [40, 70, 45, 90, 65, 85, 100, 75, 50, 80, 60, 95];

  return (
    <div className="min-h-screen bg-gray-50/50 p-6 sm:p-10 space-y-8">
      
      {/* --- Top Navigation / Header --- */}
      <header className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-white p-6 rounded-2xl border border-gray-100 shadow-sm">
        <div>
          <h1 className="text-2xl font-extrabold text-gray-900">
            Welcome back, {userName} 👋
          </h1>
          <p className="text-gray-500 text-sm mt-1">
            Here is an overview of your platform statistics today.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button 
            onClick={() => logout(true)}
            className="flex items-center gap-2 px-4 py-2.5 text-sm font-semibold text-red-600 bg-red-50 hover:bg-red-100 rounded-xl transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Sign Out
          </button>
        </div>
      </header>

      {/* --- Metrics Grid --- */}
      <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <StatCard 
          title="Active Users" 
          value="2,453" 
          change="+12.5%" 
          isPositive={true} 
          icon={Users} 
          color="bg-blue-600"
        />
        <StatCard 
          title="System Activity" 
          value="98.2%" 
          change="+2.1%" 
          isPositive={true} 
          icon={Activity} 
          color="bg-purple-600"
        />
        <StatCard 
          title="Growth Rate" 
          value="+22.4%" 
          change="-1.5%" 
          isPositive={false} 
          icon={TrendingUp} 
          color="bg-emerald-600"
        />
      </section>

      {/* --- Content Area --- */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Left Column: Visual Chart Bar */}
        <div className="lg:col-span-2 bg-white p-6 rounded-2xl border border-gray-100 shadow-sm">
          <div className="flex justify-between items-center mb-6">
            <h3 className="text-lg font-bold text-gray-900">Performance Metrics</h3>
            <button className="p-2 hover:bg-gray-50 rounded-lg text-gray-400">
              <MoreHorizontal size={20} />
            </button>
          </div>
          
          <div className="h-64 flex items-end justify-between gap-2 sm:gap-4 pt-6">
             {chartData.map((height, index) => (
                 <div key={index} className="w-full relative group h-full flex items-end">
                     <div className="absolute -top-8 left-1/2 -translate-x-1/2 bg-gray-900 text-white text-xs py-1 px-2 rounded opacity-0 group-hover:opacity-100 transition-opacity">
                         {height}%
                     </div>
                     <div 
                        style={{ height: `${height}%` }} 
                        className={`w-full rounded-t-lg transition-all duration-300 ${
                            index === chartData.length - 1 
                            ? 'bg-blue-600' 
                            : 'bg-blue-100 hover:bg-blue-200'
                        }`}
                     ></div>
                 </div>
             ))}
          </div>
          <div className="flex justify-between mt-4 text-xs text-gray-400 font-semibold uppercase tracking-wide">
             <span>Jan</span><span>Feb</span><span>Mar</span><span>Apr</span>
             <span>May</span><span>Jun</span><span>Jul</span><span>Aug</span>
             <span>Sep</span><span>Oct</span><span>Nov</span><span>Dec</span>
          </div>
        </div>

        {/* Right Column: Recent Activity Feed */}
        <div className="bg-white p-6 rounded-2xl border border-gray-100 shadow-sm flex flex-col">
          <h3 className="text-lg font-bold text-gray-900 mb-4">Recent Activity</h3>
          
          <div className="flex-1 space-y-6 overflow-y-auto pr-1">
            {[1, 2, 3, 4].map((item, index) => (
              <div key={index} className="flex items-start gap-4">
                <div className="w-9 h-9 rounded-full bg-blue-50 text-blue-600 font-bold text-sm flex items-center justify-center shrink-0 border border-blue-100">
                  U{item}
                </div>
                <div>
                  <p className="text-sm text-gray-800 font-medium leading-snug">
                    <span className="font-bold text-gray-900">User {item}</span> completed authentication step.
                  </p>
                  <div className="flex items-center text-xs text-gray-400 mt-1">
                    <Clock size={12} className="mr-1" />
                    {index * 12 + 5} minutes ago
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

      </section>
    </div>
  );
};

export default DashboardPage;