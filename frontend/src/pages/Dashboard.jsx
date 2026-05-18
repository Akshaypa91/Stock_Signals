// frontend/src/pages/Dashboard.jsx
import { useEffect, useState } from 'react'
import { useSignalStore } from '../store/signalStore'
import { fetchTodaySignals } from '../api/client'
import StockCard from '../components/StockCard'
import LiveTicker from '../components/LiveTicker'

const FILTERS = ['ALL', 'S1', 'S2']

const MARKET_OPEN_H = 9, MARKET_OPEN_M = 15
const MARKET_CLOSE_H = 15, MARKET_CLOSE_M = 30

function marketStatus() {
  const now = new Date()
  // Indian IST offset
  const ist = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
  const h = ist.getHours(), m = ist.getMinutes()
  const mins = h * 60 + m
  const open = MARKET_OPEN_H * 60 + MARKET_OPEN_M
  const close = MARKET_CLOSE_H * 60 + MARKET_CLOSE_M
  const day = ist.getDay()
  if (day === 0 || day === 6) return 'Closed (Weekend)'
  if (mins < open) return 'Pre-Market'
  if (mins <= close) return 'Open'
  return 'Closed'
}

function todayIST() {
  return new Date().toLocaleDateString('en-IN', {
    timeZone: 'Asia/Kolkata',
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
  })
}

export default function Dashboard() {
  const { signals, setSignals, filter, setFilter, filteredSignals } = useSignalStore()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [mktStatus, setMktStatus] = useState(marketStatus())

  // Load today's signals on mount
  useEffect(() => {
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await fetchTodaySignals()
        setSignals(data.signals || [])
      } catch (e) {
        setError('Failed to load signals')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  // Update market status every minute
  useEffect(() => {
    const t = setInterval(() => setMktStatus(marketStatus()), 60_000)
    return () => clearInterval(t)
  }, [])

  const displayed = filteredSignals()
  const isOpen = mktStatus === 'Open'

  return (
    <div>
      <LiveTicker />

      <div className="max-w-7xl mx-auto px-4 py-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
          <div>
            <h1 className="text-white text-2xl font-bold">Today's Signals</h1>
            <p className="text-slate-400 text-sm mt-1">{todayIST()}</p>
          </div>
          <div className="flex items-center gap-3">
            <span className={`inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-full ${
              isOpen
                ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                : 'bg-slate-700/50 text-slate-400 border border-slate-600/40'
            }`}>
              <span className={`w-1.5 h-1.5 rounded-full ${isOpen ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'}`} />
              NSE {mktStatus}
            </span>
            <span className="text-slate-500 text-sm">{displayed.length} signals</span>
          </div>
        </div>

        {/* Strategy filter tabs */}
        <div className="flex gap-1 mb-6 bg-slate-800/50 p-1 rounded-xl w-fit">
          {FILTERS.map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${
                filter === f
                  ? 'bg-slate-600 text-white shadow'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              {f}
              {f !== 'ALL' && (
                <span className="ml-1.5 text-xs text-slate-500">
                  ({signals.filter(s => s.strategy === f).length})
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Content */}
        {loading && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="bg-slate-800/40 rounded-2xl h-52 animate-pulse" />
            ))}
          </div>
        )}

        {error && (
          <div className="flex items-center gap-3 bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-400 text-sm">
            <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M12 3a9 9 0 100 18A9 9 0 0012 3z" />
            </svg>
            {error}
          </div>
        )}

        {!loading && !error && displayed.length === 0 && (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <div className="w-16 h-16 rounded-2xl bg-slate-800 flex items-center justify-center mb-4">
              <svg className="w-8 h-8 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
            </div>
            <p className="text-slate-400 font-medium">No signals yet for today</p>
            <p className="text-slate-600 text-sm mt-1">Waiting for Chartink alerts or click Scan Now</p>
          </div>
        )}

        {!loading && displayed.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {displayed.map(sig => (
              <StockCard key={sig.id} signal={sig} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
