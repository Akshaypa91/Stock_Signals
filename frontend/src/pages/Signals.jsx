// frontend/src/pages/Signals.jsx
import { useEffect, useState } from 'react'
import { fetchSignalHistory } from '../api/client'

const STATUS_BADGE = {
  active:    'bg-blue-500/20 text-blue-300',
  hit_t1:    'bg-emerald-500/20 text-emerald-300',
  hit_t2:    'bg-green-500/20 text-green-300',
  stopped:   'bg-red-500/20 text-red-300',
  time_stop: 'bg-orange-500/20 text-orange-300',
}

function exportCSV(signals) {
  const headers = ['ID','Symbol','Strategy','Date','Entry','SL','T1','T2','SL%','RR1','RR2','Qty','Status']
  const rows = signals.map(s => [s.id,s.symbol,s.strategy,s.signal_date,s.entry,s.sl,s.t1,s.t2,s.sl_pct,s.rr1,s.rr2,s.qty,s.status])
  const csv = [headers,...rows].map(r=>r.join(',')).join('\n')
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([csv],{type:'text/csv'}))
  a.download = `signals-${new Date().toISOString().slice(0,10)}.csv`
  a.click()
}

// Mobile signal card for small screens
function SignalMobileCard({ sig, onClick }) {
  return (
    <div onClick={() => onClick(sig)} className="bg-slate-800/50 border border-slate-700/40 rounded-xl p-3 cursor-pointer active:bg-slate-700/50">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-white font-bold">{sig.symbol}</span>
          <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${sig.strategy === 'S1' ? 'bg-violet-500/20 text-violet-300' : 'bg-cyan-500/20 text-cyan-300'}`}>{sig.strategy}</span>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_BADGE[sig.status] || STATUS_BADGE.active}`}>{sig.status?.replace('_',' ')}</span>
      </div>
      <div className="grid grid-cols-4 gap-1 text-xs">
        <div><div className="text-slate-500">Entry</div><div className="text-slate-200 font-medium">₹{sig.entry}</div></div>
        <div><div className="text-slate-500">SL</div><div className="text-red-400 font-medium">₹{sig.sl}</div></div>
        <div><div className="text-slate-500">T1</div><div className="text-amber-400 font-medium">₹{sig.t1}</div></div>
        <div><div className="text-slate-500">T2</div><div className="text-emerald-400 font-medium">₹{sig.t2}</div></div>
      </div>
      <div className="flex items-center justify-between mt-2 text-xs text-slate-400">
        <span>{sig.signal_date}</span>
        <span className={sig.sl_pct <= 8 ? 'text-emerald-400' : sig.sl_pct <= 12 ? 'text-amber-400' : 'text-red-400'}>SL {sig.sl_pct}%</span>
        <span className={sig.rr1 >= 2 ? 'text-emerald-400' : sig.rr1 >= 1 ? 'text-amber-400' : 'text-red-400'}>R:R 1:{sig.rr1}</span>
      </div>
    </div>
  )
}

export default function Signals() {
  const [signals, setSignals] = useState([])
  const [loading, setLoading] = useState(false)
  const [filters, setFilters] = useState({ strategy: '', status: '', from_date: '', to_date: '' })
  const [selected, setSelected] = useState(null)

  const load = async () => {
    setLoading(true)
    try {
      const params = {}
      if (filters.strategy) params.strategy = filters.strategy
      if (filters.status)   params.status   = filters.status
      if (filters.from_date) params.from_date = filters.from_date
      if (filters.to_date)   params.to_date   = filters.to_date
      const data = await fetchSignalHistory(params)
      setSignals(data.signals || [])
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])
  const setF = (k, v) => setFilters(f => ({ ...f, [k]: v }))

  return (
    <div className="max-w-7xl mx-auto px-3 sm:px-4 py-4 sm:py-6">
      <div className="flex items-center justify-between mb-4 sm:mb-6">
        <div>
          <h1 className="text-white text-xl sm:text-2xl font-bold">Signal History</h1>
          <p className="text-slate-400 text-sm mt-1">{signals.length} signals found</p>
        </div>
        <button onClick={() => exportCSV(signals)}
          className="flex items-center gap-1.5 px-3 py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs sm:text-sm rounded-lg transition-colors">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3M3 17V7a2 2 0 012-2h6l2 2h6a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
          </svg>
          <span className="hidden sm:block">Export CSV</span>
          <span className="sm:hidden">CSV</span>
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 mb-4 sm:mb-6 p-3 sm:p-4 bg-slate-800/50 rounded-xl border border-slate-700/50">
        <select value={filters.strategy} onChange={e => setF('strategy', e.target.value)}
          className="bg-slate-700 text-slate-200 text-sm rounded-lg px-3 py-2 border border-slate-600 focus:outline-none flex-1 min-w-0">
          <option value="">All Strategies</option>
          <option value="S1">S1 — Near High</option>
          <option value="S2">S2 — Breakout</option>
        </select>
        <select value={filters.status} onChange={e => setF('status', e.target.value)}
          className="bg-slate-700 text-slate-200 text-sm rounded-lg px-3 py-2 border border-slate-600 focus:outline-none flex-1 min-w-0">
          <option value="">All Status</option>
          <option value="active">Active</option>
          <option value="hit_t1">Hit T1</option>
          <option value="hit_t2">Hit T2</option>
          <option value="stopped">Stopped</option>
          <option value="time_stop">Time Stop</option>
        </select>
        <input type="date" value={filters.from_date} onChange={e => setF('from_date', e.target.value)}
          className="bg-slate-700 text-slate-200 text-sm rounded-lg px-3 py-2 border border-slate-600 focus:outline-none w-full sm:w-auto" />
        <input type="date" value={filters.to_date} onChange={e => setF('to_date', e.target.value)}
          className="bg-slate-700 text-slate-200 text-sm rounded-lg px-3 py-2 border border-slate-600 focus:outline-none w-full sm:w-auto" />
        <button onClick={load} className="px-4 py-2 bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium rounded-lg transition-colors w-full sm:w-auto">Apply</button>
      </div>

      {/* Mobile cards */}
      <div className="sm:hidden flex flex-col gap-2">
        {loading && <div className="text-center text-slate-500 py-12">Loading…</div>}
        {!loading && signals.length === 0 && <div className="text-center text-slate-500 py-12">No signals found</div>}
        {signals.map(sig => <SignalMobileCard key={sig.id} sig={sig} onClick={setSelected} />)}
      </div>

      {/* Desktop table */}
      <div className="hidden sm:block bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/50 bg-slate-900/40">
                {['Symbol','Strat','Date','Entry','SL','T1','T2','SL%','RR','Qty','Status'].map(h => (
                  <th key={h} className="text-left text-slate-400 font-medium px-4 py-3 whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={11} className="text-center text-slate-500 py-16">Loading…</td></tr>}
              {!loading && signals.length === 0 && <tr><td colSpan={11} className="text-center text-slate-500 py-16">No signals found</td></tr>}
              {signals.map(sig => (
                <tr key={sig.id} onClick={() => setSelected(sig)} className="border-b border-slate-700/30 hover:bg-slate-700/30 cursor-pointer transition-colors">
                  <td className="px-4 py-3 font-semibold text-white">{sig.symbol}</td>
                  <td className="px-4 py-3"><span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${sig.strategy === 'S1' ? 'bg-violet-500/20 text-violet-300' : 'bg-cyan-500/20 text-cyan-300'}`}>{sig.strategy}</span></td>
                  <td className="px-4 py-3 text-slate-400">{sig.signal_date}</td>
                  <td className="px-4 py-3 tabular-nums text-slate-200">₹{sig.entry}</td>
                  <td className="px-4 py-3 tabular-nums text-red-400">₹{sig.sl}</td>
                  <td className="px-4 py-3 tabular-nums text-amber-400">₹{sig.t1}</td>
                  <td className="px-4 py-3 tabular-nums text-emerald-400">₹{sig.t2}</td>
                  <td className={`px-4 py-3 tabular-nums font-medium ${sig.sl_pct <= 8 ? 'text-emerald-400' : sig.sl_pct <= 12 ? 'text-amber-400' : 'text-red-400'}`}>{sig.sl_pct}%</td>
                  <td className={`px-4 py-3 tabular-nums font-medium ${sig.rr1 >= 2 ? 'text-emerald-400' : sig.rr1 >= 1 ? 'text-amber-400' : 'text-red-400'}`}>1:{sig.rr1} / 1:{sig.rr2}</td>
                  <td className="px-4 py-3 text-slate-300">{sig.qty} + {sig.qty_half}</td>
                  <td className="px-4 py-3"><span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_BADGE[sig.status] || STATUS_BADGE.active}`}>{sig.status?.replace('_',' ')}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Detail modal */}
      {selected && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-end sm:items-center justify-center p-0 sm:p-4" onClick={() => setSelected(null)}>
          <div className="bg-slate-800 border border-slate-600 rounded-t-2xl sm:rounded-2xl p-5 w-full sm:max-w-md shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-white text-xl font-bold">{selected.symbol}</h2>
                <p className="text-slate-400 text-sm">{selected.strategy} · {selected.signal_date}</p>
              </div>
              <button onClick={() => setSelected(null)} className="text-slate-500 hover:text-white p-1">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>
            <div className="grid grid-cols-2 gap-2 text-sm">
              {[['Entry',`₹${selected.entry}`,'text-slate-200'],['Stop Loss',`₹${selected.sl}`,'text-red-400'],['Target 1',`₹${selected.t1}`,'text-amber-400'],['Target 2',`₹${selected.t2}`,'text-emerald-400'],['SL %',`${selected.sl_pct}%`,'text-slate-300'],['ATR',`₹${selected.atr}`,'text-slate-300'],['R:R (T1)',`1:${selected.rr1}`,'text-slate-300'],['R:R (T2)',`1:${selected.rr2}`,'text-slate-300'],['Qty (full)',selected.qty,'text-slate-300'],['Qty (half)',selected.qty_half,'text-slate-300']].map(([label,value,cls]) => (
                <div key={label} className="bg-slate-900/50 rounded-xl p-3">
                  <div className="text-slate-500 text-xs mb-1">{label}</div>
                  <div className={`font-semibold ${cls}`}>{value}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
