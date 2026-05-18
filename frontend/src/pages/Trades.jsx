// frontend/src/pages/Trades.jsx
import { useEffect, useState } from 'react'
import { fetchTrades, createTrade, closeTrade, deleteTrade } from '../api/client'
import PnLChart from '../components/PnLChart'

function SummaryCard({ label, value, sub, color = 'text-white' }) {
  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4">
      <div className="text-slate-400 text-xs mb-1">{label}</div>
      <div className={`text-xl font-bold tabular-nums ${color}`}>{value ?? '—'}</div>
      {sub && <div className="text-slate-500 text-xs mt-0.5">{sub}</div>}
    </div>
  )
}

const EXIT_REASONS = ['T1', 'T2', 'SL', 'trail', 'time_stop', 'manual']

export default function Trades() {
  const [data, setData] = useState({ trades: [], summary: {} })
  const [loading, setLoading] = useState(false)
  const [showAdd, setShowAdd] = useState(false)
  const [showClose, setShowClose] = useState(null)   // trade object
  const [addForm, setAddForm] = useState({ symbol: '', buy_price: '', qty: '', entry_date: today() })
  const [closeForm, setCloseForm] = useState({ sell_price: '', exit_reason: 'T1', exit_date: today() })
  const [saving, setSaving] = useState(false)

  function today() {
    return new Date().toISOString().slice(0, 10)
  }

  const load = async () => {
    setLoading(true)
    try {
      const d = await fetchTrades()
      setData(d)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleAdd = async () => {
    setSaving(true)
    try {
      await createTrade({
        symbol: addForm.symbol.toUpperCase(),
        buy_price: parseFloat(addForm.buy_price),
        qty: parseInt(addForm.qty),
        entry_date: addForm.entry_date,
      })
      setShowAdd(false)
      setAddForm({ symbol: '', buy_price: '', qty: '', entry_date: today() })
      await load()
    } catch (e) { console.error(e) }
    finally { setSaving(false) }
  }

  const handleClose = async () => {
    setSaving(true)
    try {
      await closeTrade(showClose.id, {
        sell_price: parseFloat(closeForm.sell_price),
        exit_reason: closeForm.exit_reason,
        exit_date: closeForm.exit_date,
      })
      setShowClose(null)
      await load()
    } catch (e) { console.error(e) }
    finally { setSaving(false) }
  }

  const handleDelete = async (id) => {
    if (!confirm('Delete this trade record?')) return
    try { await deleteTrade(id); await load() }
    catch (e) { console.error(e) }
  }

  const s = data.summary || {}

  return (
    <div className="max-w-7xl mx-auto px-4 py-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-white text-2xl font-bold">Trade Journal</h1>
          <p className="text-slate-400 text-sm mt-1">{s.total_trades || 0} trades · {s.closed_trades || 0} closed</p>
        </div>
        <button
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-500 text-white text-sm font-semibold rounded-lg transition-colors"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          Add Trade
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
        <SummaryCard label="Total Trades" value={s.total_trades} />
        <SummaryCard label="Win Rate"
          value={s.win_rate != null ? `${s.win_rate}%` : null}
          color={s.win_rate >= 50 ? 'text-emerald-400' : 'text-amber-400'} />
        <SummaryCard label="Total P&L"
          value={s.total_pnl != null ? `₹${s.total_pnl?.toLocaleString('en-IN')}` : null}
          color={s.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'} />
        <SummaryCard label="Best Trade"
          value={s.best_trade != null ? `₹${s.best_trade?.toLocaleString('en-IN')}` : null}
          color="text-emerald-400" />
        <SummaryCard label="Worst Trade"
          value={s.worst_trade != null ? `₹${s.worst_trade?.toLocaleString('en-IN')}` : null}
          color="text-red-400" />
        <SummaryCard label="Avg Hold" value={s.avg_hold_days != null ? `${s.avg_hold_days}d` : null} />
      </div>

      {/* Equity curve */}
      <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4 mb-6">
        <h2 className="text-slate-300 text-sm font-semibold mb-3">Equity Curve</h2>
        <PnLChart trades={data.trades} />
      </div>

      {/* Trade log */}
      <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/50 bg-slate-900/40">
                {['Symbol','Buy','Sell','Qty','P&L','P&L%','Reason','Entry','Exit','Days',''].map(h => (
                  <th key={h} className="text-left text-slate-400 font-medium px-4 py-3 whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={11} className="text-center text-slate-500 py-12">Loading…</td></tr>
              )}
              {!loading && data.trades.length === 0 && (
                <tr><td colSpan={11} className="text-center text-slate-500 py-12">No trades yet — click Add Trade</td></tr>
              )}
              {data.trades.map(t => {
                const isOpen = t.sell_price == null
                const pnlPos = (t.pnl || 0) >= 0
                return (
                  <tr key={t.id} className="border-b border-slate-700/30 hover:bg-slate-700/20 transition-colors">
                    <td className="px-4 py-3 font-semibold text-white">{t.symbol}</td>
                    <td className="px-4 py-3 tabular-nums text-slate-200">₹{t.buy_price}</td>
                    <td className="px-4 py-3 tabular-nums text-slate-400">
                      {t.sell_price ? `₹${t.sell_price}` : (
                        <button
                          onClick={() => { setShowClose(t); setCloseForm({ sell_price: '', exit_reason: 'T1', exit_date: today() }) }}
                          className="text-xs px-2 py-0.5 bg-violet-500/20 text-violet-300 rounded-full hover:bg-violet-500/30 transition-colors"
                        >
                          Close
                        </button>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-300">{t.qty}</td>
                    <td className={`px-4 py-3 tabular-nums font-semibold ${!isOpen ? (pnlPos ? 'text-emerald-400' : 'text-red-400') : 'text-slate-500'}`}>
                      {!isOpen ? `${pnlPos ? '+' : ''}₹${t.pnl?.toLocaleString('en-IN')}` : 'Open'}
                    </td>
                    <td className={`px-4 py-3 tabular-nums ${!isOpen ? (pnlPos ? 'text-emerald-400' : 'text-red-400') : 'text-slate-500'}`}>
                      {!isOpen && t.pnl_pct != null ? `${t.pnl_pct > 0 ? '+' : ''}${t.pnl_pct}%` : '—'}
                    </td>
                    <td className="px-4 py-3 text-slate-400">{t.exit_reason || '—'}</td>
                    <td className="px-4 py-3 text-slate-400">{t.entry_date}</td>
                    <td className="px-4 py-3 text-slate-400">{t.exit_date || '—'}</td>
                    <td className="px-4 py-3 text-slate-500">{t.hold_days != null ? `${t.hold_days}d` : '—'}</td>
                    <td className="px-4 py-3">
                      <button onClick={() => handleDelete(t.id)} className="text-slate-600 hover:text-red-400 transition-colors">
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add Trade Modal */}
      {showAdd && (
        <Modal title="Add Trade" onClose={() => setShowAdd(false)}>
          {[
            { label: 'Symbol', key: 'symbol', type: 'text', placeholder: 'RELIANCE' },
            { label: 'Buy Price (₹)', key: 'buy_price', type: 'number', placeholder: '2450.00' },
            { label: 'Quantity', key: 'qty', type: 'number', placeholder: '10' },
            { label: 'Entry Date', key: 'entry_date', type: 'date' },
          ].map(f => (
            <div key={f.key}>
              <label className="text-slate-400 text-xs block mb-1">{f.label}</label>
              <input
                type={f.type}
                value={addForm[f.key]}
                onChange={e => setAddForm(v => ({ ...v, [f.key]: e.target.value }))}
                placeholder={f.placeholder}
                className="w-full bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-violet-500"
              />
            </div>
          ))}
          <button onClick={handleAdd} disabled={saving}
            className="w-full py-2.5 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white font-semibold rounded-lg transition-colors">
            {saving ? 'Saving…' : 'Add Trade'}
          </button>
        </Modal>
      )}

      {/* Close Trade Modal */}
      {showClose && (
        <Modal title={`Close ${showClose.symbol}`} onClose={() => setShowClose(null)}>
          <div>
            <label className="text-slate-400 text-xs block mb-1">Sell Price (₹)</label>
            <input type="number" value={closeForm.sell_price}
              onChange={e => setCloseForm(v => ({ ...v, sell_price: e.target.value }))}
              placeholder="2500.00"
              className="w-full bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-violet-500" />
          </div>
          <div>
            <label className="text-slate-400 text-xs block mb-1">Exit Reason</label>
            <select value={closeForm.exit_reason}
              onChange={e => setCloseForm(v => ({ ...v, exit_reason: e.target.value }))}
              className="w-full bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-violet-500">
              {EXIT_REASONS.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <div>
            <label className="text-slate-400 text-xs block mb-1">Exit Date</label>
            <input type="date" value={closeForm.exit_date}
              onChange={e => setCloseForm(v => ({ ...v, exit_date: e.target.value }))}
              className="w-full bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-violet-500" />
          </div>
          {closeForm.sell_price && showClose.buy_price && (
            <div className={`rounded-lg p-3 text-sm font-semibold text-center ${
              parseFloat(closeForm.sell_price) >= showClose.buy_price
                ? 'bg-emerald-500/15 text-emerald-400'
                : 'bg-red-500/15 text-red-400'
            }`}>
              Est. P&L: ₹{((parseFloat(closeForm.sell_price) - showClose.buy_price) * showClose.qty).toLocaleString('en-IN')}
            </div>
          )}
          <button onClick={handleClose} disabled={saving}
            className="w-full py-2.5 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white font-semibold rounded-lg transition-colors">
            {saving ? 'Saving…' : 'Close Trade'}
          </button>
        </Modal>
      )}
    </div>
  )
}

function Modal({ title, children, onClose }) {
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-slate-800 border border-slate-600 rounded-2xl p-6 w-full max-w-sm shadow-2xl flex flex-col gap-4" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 className="text-white font-bold text-lg">{title}</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-white transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
