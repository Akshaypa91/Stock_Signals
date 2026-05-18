import { useEffect, useRef } from 'react'
import { useSignalStore } from '../store/signalStore'

const WS_URL = import.meta.env.VITE_WS_URL || 'wss://stock-signals-4fec.onrender.com/ws/signals'
const RECONNECT_DELAY = 3000

export function useWebSocket() {
  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)
  const { addSignals, updateLtp, updateStatus, setWsConnected } = useSignalStore()

  const connect = () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(WS_URL)
    wsRef.current = ws

    ws.onopen = () => {
      setWsConnected(true)
      console.log('[WS] Connected')
      clearTimeout(reconnectTimer.current)
    }

    ws.onmessage = (evt) => {
      try {
        if (evt.data === 'pong') return
        const msg = JSON.parse(evt.data)
        switch (msg.type) {
          case 'new_signals':
          case 'scan_complete':
            addSignals(msg.signals || [])
            break
          case 'ltp':
            updateLtp(msg.instrument_key, msg.ltp)
            break
          case 'status_update':
            updateStatus(msg.signal_id, msg.status, msg.ltp)
            break
          default:
            break
        }
      } catch (e) {
        console.error('[WS] Parse error:', e)
      }
    }

    ws.onclose = () => {
      setWsConnected(false)
      console.log('[WS] Disconnected — reconnecting in', RECONNECT_DELAY, 'ms')
      reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY)
    }

    ws.onerror = (e) => {
      console.error('[WS] Error:', e)
      ws.close()
    }
  }

  useEffect(() => {
    connect()
    const pingInterval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send('ping')
      }
    }, 25000)

    return () => {
      clearInterval(pingInterval)
      clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [])
}
