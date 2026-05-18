// frontend/src/components/Navbar.jsx
import { Link, useLocation } from 'react-router-dom'
import { useSignalStore } from '../store/signalStore'
import { triggerScan, api } from '../api/client'
import { useState, useEffect } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function Navbar() {
  const location = useLocation()
  const wsConnected = useSignalStore(s => s.wsConnected)
  const [scanning, setScanning] = useState(false)
  const [upstoxAuth, setUpstoxAuth] = useState(null) // null=loading, true=ok, false=not auth

  useEffect(() => {
    checkUpstoxStatus()
    const interval = setInterval(checkUpstoxStatus, 60_000)
    return () => clearInterval(interval)
  }, [])

  const checkUpstoxStatus = async () => {
    try {
      const res = await api.get('/upstox/status')
      setUpstoxAuth(res.data.authenticated)
    } catch {
      setUpstoxAuth(false)
    }
  }

  const handleUpstoxConnect = () => {
    // Open Upstox login in a popup window
    const popup = window.open(
      `${API_URL}/upstox/login`,
      'upstox-auth',
      'width=520,height=620,scrollbars=yes,resizable=yes'
    )
    // Poll for popup close then recheck auth status
    const timer = setInterval(() => {
      if (popup?.closed) {
        clearInterval(timer)
        setTimeout(checkUpstoxStatus, 1000)
      }
    }, 500)
  }

  const handleScan = async () => {
    if (!upstoxAuth) {
      handleUpstoxConnect()
      return
    }
    setScanning(true)
    try {
      await triggerScan('both')
    } catch (e) {
      console.error('Scan failed:', e)
    } finally {
      setTimeout(() => setScanning(false), 3000)
    }
  }

  const links = [
    { to: '/',        label: 'Dashboard' },
    { to: '/signals', label: 'Signals' },
    { to: '/trades',  label: 'Trades' },
  ]

  return (
    <nav className="bg-slate-900/95 backdrop-blur border-b border-slate-700/50 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between">

        {/* Brand */}
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-violet-500 to-cyan-500 flex items-center justify-center">
            <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
          </div>
          <span className="text-white font-bold text-base tracking-tight">Stock Signals</span>
          {/* <span className="text-slate-600 text-xs hidden sm:block">NSE Signals</span> */}
        </div>

        {/* Nav links */}
        <div className="flex items-center gap-1">
          {links.map(({ to, label }) => (
            <Link
              key={to}
              to={to}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                location.pathname === to
                  ? 'bg-slate-700 text-white'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}
            >
              {label}
            </Link>
          ))}
        </div>

        {/* Right side */}
        <div className="flex items-center gap-2">

          {/* Upstox connect button */}
          {upstoxAuth === false && (
            <button
              onClick={handleUpstoxConnect}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/40 text-amber-400 text-xs font-semibold rounded-lg transition-colors"
              title="Connect Upstox to fetch live data"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
              Connect Upstox
            </button>
          )}

          {upstoxAuth === true && (
            <div className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 bg-emerald-500/10 border border-emerald-500/30 rounded-lg">
              <svg className="w-3.5 h-3.5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
              <span className="text-emerald-400 font-medium">Upstox</span>
            </div>
          )}

          {/* WS indicator */}
          <div className="flex items-center gap-1.5 text-xs">
            <span className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
            <span className={wsConnected ? 'text-emerald-400' : 'text-red-400'}>
              {wsConnected ? 'Live' : 'Offline'}
            </span>
          </div>

          {/* Scan button */}
          <button
            onClick={handleScan}
            disabled={scanning}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs font-semibold rounded-lg transition-colors"
          >
            {scanning ? (
              <>
                <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                </svg>
                Scanning…
              </>
            ) : (
              <>
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M17 11A6 6 0 105 11a6 6 0 0012 0z" />
                </svg>
                Scan Now
              </>
            )}
          </button>
        </div>
      </div>
    </nav>
  )
}
