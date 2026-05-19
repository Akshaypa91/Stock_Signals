// frontend/src/components/LiveTicker.jsx
import { useSignalStore } from '../store/signalStore'

export default function LiveTicker() {
  const signals = useSignalStore(s => s.signals)
  const getLtp  = useSignalStore(s => s.getLtp)
  const active  = signals.filter(s => s.status === 'active' && s.upstox_key)

  if (active.length === 0) return null

  const items = [...active, ...active]

  return (
    <div className="bg-slate-900/80 border-b border-slate-700/40 overflow-hidden py-1.5">
      <div className="flex gap-6 sm:gap-8 animate-ticker whitespace-nowrap"
        style={{ animationDuration: `${Math.max(15, active.length * 3)}s` }}>
        {items.map((sig, i) => {
          const ltp = getLtp(sig.upstox_key)
          const chg = ltp && sig.entry ? (((ltp - sig.entry) / sig.entry) * 100).toFixed(2) : null
          return (
            <span key={`${sig.id}-${i}`} className="inline-flex items-center gap-1.5 text-xs">
              <span className="text-slate-300 font-semibold">{sig.symbol}</span>
              <span className={`font-bold tabular-nums ${!ltp ? 'text-slate-500' : ltp >= sig.entry ? 'text-emerald-400' : ltp <= sig.sl ? 'text-red-400' : 'text-amber-400'}`}>
                {ltp != null ? `₹${ltp.toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : '—'}
              </span>
              {chg && <span className={chg >= 0 ? 'text-emerald-500' : 'text-red-500'}>{chg >= 0 ? '▲' : '▼'}{Math.abs(chg)}%</span>}
              <span className="text-slate-700">|</span>
            </span>
          )
        })}
      </div>
    </div>
  )
}
