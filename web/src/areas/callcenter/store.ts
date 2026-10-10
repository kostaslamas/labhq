import { defineStore } from 'pinia'
import { ref } from 'vue'

export type PinKind = 'report' | 'approval'
export type PinOption = 'approve' | 'reject' | 'show'

// What a card hands the widget: the proposal itself, never text the owner would retype.
export interface Pin {
  kind: PinKind
  id: number
  projectId: number | null
  options: PinOption[]
}

export type Panel = 'chat' | 'room'

export const useCallCenter = defineStore('callcenter', () => {
  const open = ref(false)
  const pin = ref<Pin | null>(null)
  const panel = ref<Panel>('chat')

  function discuss(next: Pin): void {
    pin.value = next
    panel.value = 'chat'
    open.value = true
  }

  function toggle(): void {
    open.value = !open.value
  }

  function close(): void {
    open.value = false
  }

  function unpin(): void {
    pin.value = null
  }

  return { open, pin, panel, discuss, toggle, close, unpin }
})
