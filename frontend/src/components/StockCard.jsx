// frontend/src/components/StockCard.jsx
import { useSignalStore } from '../store/signalStore'

const STATUS_COLORS = {
  active:    'bg-blue-500/20 text-blue-300 border-blue-500/40',
  hit_t1:    'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
  hit_t2:    'bg-green-500/20 text-green-300 border-green-500/40',
  stopped:   'bg-red-500/20 text-red-300 border-red-500/40',
  time_stop: 'bg-orange-500/20 text-orange-300 border-orange-500/40',
}

const STATUS_LABELS = {
  active:    'Active',
  hit_t1:    'Hit T1',
  hit_t2:    'Hit T2',
  stopped:   'Stopped',
  time_stop: 'Time Stop',
}

function rrColor(rr) {
  if (rr >= 2) return 'text-emerald-400'
  if (rr >= 1) return 'text-amber-400'
  return 'text-red-400'
}

function slPctColor(pct) {
  if (pct <= 8)  return 'text-emerald-400'
  if (pct <= 12) return 'text-amber-400'
  return 'text-red-400'
}

function ltpColor(ltp, entry, sl) {
  if (!ltp) return 'text-slate-300'
  if (ltp <= sl) return 'text-red-400'
  if (ltp >= entry) return 'text-emerald-400'
  return 'text-amber-400'
}

function pct(a, b) {
  if (!a || !b) return null
  return (((a - b) / b) * 100).toFixed(2)
}

export default function StockCard({ signal }) {
  const getLtp = useSignalStore(s => s.getLtp)
  const ltp = getLtp(signal.upstox_key) ?? signal.ltp ?? null

  const statusCls = STATUS_COLORS[signal.status] || STATUS_COLORS.active

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-2xl p-4 hover:border-slate-500/70 transition-all hover:shadow-lg hover:shadow-black/30 group">

      {/* Header row */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-white font-bold text-lg tracking-wide">{signal.symbol}</span>
            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${
              signal.strategy === 'S1'
                ? 'bg-violet-500/20 text-violet-300 border-violet-500/40'
                : 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40'
            }`}>
              {signal.strategy}
            </span>
          </div>
          <div className="text-slate-400 text-xs mt-0.5">{signal.signal_date}</div>
        </div>

        <span className={`text-xs font-semibold px-2.5 py-1 rounded-full border ${statusCls}`}>
          {STATUS_LABELS[signal.status] || signal.status}
        </span>
      </div>

      {/* Live LTP */}
      <div className="mb-4">
        <div className={`text-2xl font-bold tabular-nums ${ltpColor(ltp, signal.entry, signal.sl)}`}>
          {ltp != null ? `₹${ltp.toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : '—'}
        </div>
        {ltp && signal.entry && (
          <div className="text-xs text-slate-500 mt-0.5">
            {pct(ltp, signal.entry) > 0 ? '+' : ''}{pct(ltp, signal.entry)}% vs entry
          </div>
        )}
      </div>

      {/* Level grid */}
      <div className="grid grid-cols-4 gap-2 mb-4">
        {[
          { label: 'Entry', value: signal.entry, cls: 'text-slate-200' },
          { label: 'SL',    value: signal.sl,    cls: 'text-red-400' },
          { label: 'T1',    value: signal.t1,    cls: 'text-amber-400' },
          { label: 'T2',    value: signal.t2,    cls: 'text-emerald-400' },
        ].map(({ label, value, cls }) => (
          <div key={label} className="bg-slate-900/50 rounded-lg p-2 text-center">
            <div className="text-slate-500 text-xs mb-1">{label}</div>
            <div className={`font-semibold text-sm tabular-nums ${cls}`}>
              ₹{Number(value).toLocaleString('en-IN', { minimumFractionDigits: 1 })}
            </div>
          </div>
        ))}
      </div>

      {/* Stats row */}
      <div className="flex items-center justify-between text-xs border-t border-slate-700/50 pt-3">
        <div className="flex gap-4">
          <div>
            <span className="text-slate-500">SL% </span>
            <span className={`font-semibold ${slPctColor(signal.sl_pct)}`}>
              {signal.sl_pct}%
            </span>
          </div>
          <div>
            <span className="text-slate-500">R:R </span>
            <span className={`font-semibold ${rrColor(signal.rr1)}`}>
              1:{signal.rr1}
            </span>
            <span className="text-slate-600 mx-1">/</span>
            <span className={`font-semibold ${rrColor(signal.rr2)}`}>
              1:{signal.rr2}
            </span>
          </div>
        </div>
        <div className="text-slate-400">
          <span className="text-slate-500">Qty </span>
          <span className="font-semibold">{signal.qty}</span>
          <span className="text-slate-600 mx-1">+</span>
          <span className="font-semibold">{signal.qty_half}</span>
        </div>
      </div>
    </div>
  )
}
