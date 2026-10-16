import { create } from 'zustand';
import { jwtDecode } from 'jwt-decode';
import { API_BASE_URL } from './api/apiConfig';

export const useAuthStore = create((set, get) => ({
  user: null,
  token: null,
  isAuthenticated: false,
  loading: true,

  checkAuth: () => {
    const token = localStorage.getItem('authToken');
    if (!token) {
      set({ loading: false, isAuthenticated: false, user: null });
      return;
    }

    try {
      const decoded = jwtDecode(token);
      const currentTime = Date.now() / 1000;

      if (decoded.exp > currentTime) {
        const storedUser = localStorage.getItem('user');
        const userObj = storedUser 
          ? JSON.parse(storedUser) 
          : { id: decoded.user_id, email: decoded.sub };

        set({
          user: userObj,
          token: token,
          isAuthenticated: true,
          loading: false,
        });
      } else {
        get().logout();
      }
    } catch (error) {
      console.error("Token decode failed:", error);
      get().logout();
    }
  },

  login: async (email, password) => {
    const formData = new FormData();
    formData.append('username', email);
    formData.append('password', password);

    try {
      const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
        method: "POST",
        body: formData,
      });

      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Login failed");

      const { access_token, user: backendUser } = data;
      const decodedToken = jwtDecode(access_token);

      const finalUser = {
        ...backendUser,
        id: decodedToken.user_id || backendUser?.id,
      };

      localStorage.setItem('authToken', access_token);
      localStorage.setItem('user', JSON.stringify(finalUser));

      set({
        user: finalUser,
        token: access_token,
        isAuthenticated: true,
        loading: false,
      });

      return finalUser;
    } catch (err) {
      console.error("Login Error:", err);
      throw err;
    }
  },

  // Accepts token and backend user object from Google OAuth callback
  loginWithToken: (token, userData = null) => {
    try {
      const decoded = jwtDecode(token);
      
      const user = userData || {
        id: decoded.user_id,
        email: decoded.sub,
        full_name: decoded.name || "User", 
      };

      localStorage.setItem('authToken', token);
      localStorage.setItem('user', JSON.stringify(user));

      set({
        token: token,
        user: user,
        isAuthenticated: true,
        loading: false
      });

      return user;
    } catch (error) {
      console.error("Invalid Token", error);
      get().logout();
      return null;
    }
  },

  logout: (shouldRedirect = true) => {
    localStorage.removeItem('authToken');
    localStorage.removeItem('user');
    set({ user: null, token: null, isAuthenticated: false, loading: false });

    if (shouldRedirect) {
      window.location.href = '/login';
    }
  },
}));