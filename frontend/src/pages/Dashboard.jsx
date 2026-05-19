// frontend/src/pages/Dashboard.jsx
import { useEffect, useState } from 'react'
import { useSignalStore } from '../store/signalStore'
import { fetchTodaySignals } from '../api/client'
import StockCard from '../components/StockCard'
import LiveTicker from '../components/LiveTicker'

const FILTERS = ['ALL', 'S1', 'S2']

function marketStatus() {
  const ist = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
  const mins = ist.getHours() * 60 + ist.getMinutes()
  const day = ist.getDay()
  if (day === 0 || day === 6) return 'Closed'
  if (mins < 555) return 'Pre-Market'
  if (mins <= 930) return 'Open'
  return 'Closed'
}

function todayIST() {
  return new Date().toLocaleDateString('en-IN', {
    timeZone: 'Asia/Kolkata', weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
  })
}

export default function Dashboard() {
  const { signals, setSignals, filter, setFilter, filteredSignals } = useSignalStore()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [mktStatus, setMktStatus] = useState(marketStatus())

  useEffect(() => {
    const load = async () => {
      setLoading(true); setError(null)
      try { const data = await fetchTodaySignals(); setSignals(data.signals || []) }
      catch { setError('Failed to load signals') }
      finally { setLoading(false) }
    }
    load()
  }, [])

  useEffect(() => {
    const t = setInterval(() => setMktStatus(marketStatus()), 60_000)
    return () => clearInterval(t)
  }, [])

  const displayed = filteredSignals()
  const isOpen = mktStatus === 'Open'

  return (
    <div>
      <LiveTicker />
      <div className="max-w-7xl mx-auto px-3 sm:px-4 py-4 sm:py-6">

        {/* Header */}
        <div className="flex items-start justify-between gap-3 mb-4 sm:mb-6">
          <div>
            <h1 className="text-white text-xl sm:text-2xl font-bold">Today's Signals</h1>
            <p className="text-slate-400 text-xs sm:text-sm mt-0.5">{todayIST()}</p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <span className={`inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full ${isOpen ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30' : 'bg-slate-700/50 text-slate-400 border border-slate-600/40'}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${isOpen ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'}`} />
              NSE {mktStatus}
            </span>
          </div>
        </div>

        {/* Filter tabs */}
        <div className="flex gap-1 mb-4 sm:mb-6 bg-slate-800/50 p-1 rounded-xl w-fit">
          {FILTERS.map(f => (
            <button key={f} onClick={() => setFilter(f)}
              className={`px-3 sm:px-4 py-1.5 rounded-lg text-xs sm:text-sm font-medium transition-all ${filter === f ? 'bg-slate-600 text-white shadow' : 'text-slate-400 hover:text-white'}`}>
              {f}
              {f !== 'ALL' && <span className="ml-1 text-xs text-slate-500">({signals.filter(s => s.strategy === f).length})</span>}
            </button>
          ))}
          <span className="ml-1 px-2 py-1.5 text-xs text-slate-500 self-center">{displayed.length}</span>
        </div>

        {/* Loading skeletons */}
        {loading && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 sm:gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="bg-slate-800/40 rounded-2xl h-48 animate-pulse" />
            ))}
          </div>
        )}

        {error && (
          <div className="flex items-center gap-3 bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-400 text-sm">
            <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M12 3a9 9 0 100 18A9 9 0 0012 3z" /></svg>
            {error}
          </div>
        )}

        {!loading && !error && displayed.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 sm:py-24 text-center">
            <div className="w-14 h-14 sm:w-16 sm:h-16 rounded-2xl bg-slate-800 flex items-center justify-center mb-4">
              <svg className="w-7 h-7 sm:w-8 sm:h-8 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
            </div>
            <p className="text-slate-400 font-medium">No signals yet for today</p>
            <p className="text-slate-600 text-sm mt-1">Waiting for Chartink alerts or click Scan Now</p>
          </div>
        )}

        {!loading && displayed.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 sm:gap-4">
            {displayed.map(sig => <StockCard key={sig.id} signal={sig} />)}
          </div>
        )}
      </div>
    </div>
  )
}
