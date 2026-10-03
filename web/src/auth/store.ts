import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { authClient } from './client'
import { signInWithPasskey } from './ceremonies'

export type AuthState = 'unknown' | 'signed_in' | 'signed_out'

export const useAuthStore = defineStore('auth', () => {
  const state = ref<AuthState>('unknown')
  // Whether any passkey can sign in; false tells the login page to explain enrollment.
  const enrolled = ref(true)
  const signedIn = computed(() => state.value === 'signed_in')

  async function refresh(): Promise<void> {
    try {
      const { data } = await authClient().GET('/api/auth/status')
      state.value = data?.authenticated ? 'signed_in' : 'signed_out'
      enrolled.value = data?.enrolled ?? true
    } catch {
      // The server is unreachable: treat it as signed out rather than showing a half page.
      state.value = 'signed_out'
    }
  }

  async function ensureLoaded(): Promise<void> {
    if (state.value === 'unknown') await refresh()
  }

  async function signIn(): Promise<void> {
    await signInWithPasskey()
    state.value = 'signed_in'
    enrolled.value = true
  }

  async function signOut(): Promise<void> {
    try {
      await authClient().POST('/api/auth/logout')
    } finally {
      state.value = 'signed_out'
    }
  }

  function markSignedOut(): void {
    state.value = 'signed_out'
  }

  return { state, enrolled, signedIn, refresh, ensureLoaded, signIn, signOut, markSignedOut }
})
