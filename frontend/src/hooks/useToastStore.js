import { create } from 'zustand';

let nextId = 1;

export const useToastStore = create((set, get) => ({
  toasts: [],
  push: (kind, text, ttl = 4500) => {
    const id = nextId++;
    set((state) => ({ toasts: [...state.toasts.slice(-4), { id, kind, text }] }));
    setTimeout(() => get().dismiss(id), ttl);
    return id;
  },
  dismiss: (id) => set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
}));

export const toast = {
  success: (text) => useToastStore.getState().push('success', text),
  error: (text) => useToastStore.getState().push('error', text, 7000),
  info: (text) => useToastStore.getState().push('info', text),
};
