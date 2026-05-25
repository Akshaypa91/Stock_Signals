// frontend/src/pages/Trades.jsx
import { useEffect, useState } from 'react'
import { fetchTrades, createTrade, closeTrade, deleteTrade } from '../api/client'
import PnLChart from '../components/PnLChart'

function SummaryCard({ label, value, color = 'text-white' }) {
  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-3 sm:p-4">
      <div className="text-slate-400 text-xs mb-1">{label}</div>
      <div className={`text-lg sm:text-xl font-bold tabular-nums ${color}`}>{value ?? '—'}</div>
    </div>
  )
}

const EXIT_REASONS = ['T1', 'T2', 'SL', 'trail', 'time_stop', 'manual']

function today() { return new Date().toISOString().slice(0, 10) }

function Modal({ title, children, onClose }) {
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-end sm:items-center justify-center" onClick={onClose}>
      <div className="bg-slate-800 border border-slate-600 rounded-t-2xl sm:rounded-2xl p-5 w-full sm:max-w-md shadow-2xl flex flex-col gap-4" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 className="text-white font-bold text-lg">{title}</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-white p-1">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

// Live P&L preview inside close modal
function PnLPreview({ sellPrice, buyPrice, qty, exitQty }) {
  if (!sellPrice || !buyPrice || !exitQty) return null
  const sell = parseFloat(sellPrice)
  const buy  = parseFloat(buyPrice)
  const q    = parseInt(exitQty)
  if (isNaN(sell) || isNaN(buy) || isNaN(q) || q <= 0) return null
  const pnl    = (sell - buy) * q
  const pnlPct = ((sell - buy) / buy * 100).toFixed(2)
  const pos    = pnl >= 0
  return (
    <div className={`rounded-xl p-3 text-sm ${pos ? 'bg-emerald-500/15 border border-emerald-500/30' : 'bg-red-500/15 border border-red-500/30'}`}>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div className="text-slate-400 text-xs mb-0.5">Exit Qty</div>
          <div className="text-white font-semibold">{q}</div>
        </div>
        <div>
          <div className="text-slate-400 text-xs mb-0.5">P&L / share</div>
          <div className={`font-semibold ${pos ? 'text-emerald-400' : 'text-red-400'}`}>
            {pos ? '+' : ''}₹{(sell - buy).toFixed(2)}
          </div>
        </div>
        <div>
          <div className="text-slate-400 text-xs mb-0.5">Total P&L</div>
          <div className={`font-bold ${pos ? 'text-emerald-400' : 'text-red-400'}`}>
            {pos ? '+' : ''}₹{pnl.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
          </div>
        </div>
      </div>
      <div className={`text-center text-xs mt-2 ${pos ? 'text-emerald-400' : 'text-red-400'}`}>
        {pos ? '▲' : '▼'} {Math.abs(pnlPct)}% return on this exit
      </div>
    </div>
  )
}

export default function Trades() {
  const [data, setData]         = useState({ trades: [], summary: {} })
  const [loading, setLoading]   = useState(false)
  const [showAdd, setShowAdd]   = useState(false)
  const [showClose, setShowClose] = useState(null)
  const [addForm, setAddForm]   = useState({ symbol: '', buy_price: '', qty: '', entry_date: today() })
  const [closeForm, setCloseForm] = useState({ sell_price: '', exit_reason: 'T1', exit_date: today(), exit_qty: '' })
  const [saving, setSaving]     = useState(false)

  const load = async () => {
    setLoading(true)
    try { const d = await fetchTrades(); setData(d) }
    catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const handleAdd = async () => {
    if (!addForm.symbol || !addForm.buy_price || !addForm.qty) return
    setSaving(true)
    try {
      await createTrade({
        symbol:     addForm.symbol.toUpperCase(),
        buy_price:  parseFloat(addForm.buy_price),
        qty:        parseInt(addForm.qty),
        entry_date: addForm.entry_date,
      })
      setShowAdd(false)
      setAddForm({ symbol: '', buy_price: '', qty: '', entry_date: today() })
      await load()
    } catch (e) { console.error(e) } finally { setSaving(false) }
  }

  const openClose = (trade) => {
    setShowClose(trade)
    setCloseForm({
      sell_price:  '',
      exit_reason: 'T1',
      exit_date:   today(),
      exit_qty:    String(trade.qty),  // default to full qty
    })
  }

  const handleClose = async () => {
    if (!closeForm.sell_price || !closeForm.exit_qty) return
    setSaving(true)
    try {
      await closeTrade(showClose.id, {
        sell_price:  parseFloat(closeForm.sell_price),
        exit_reason: closeForm.exit_reason,
        exit_date:   closeForm.exit_date,
        exit_qty:    parseInt(closeForm.exit_qty),
      })
      setShowClose(null)
      await load()
    } catch (e) { console.error(e) } finally { setSaving(false) }
  }

  const handleDelete = async (id) => {
    if (!confirm('Delete this trade?')) return
    try { await deleteTrade(id); await load() } catch (e) { console.error(e) }
  }

  const s = data.summary || {}

  return (
    <div className="max-w-7xl mx-auto px-3 sm:px-4 py-4 sm:py-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 sm:mb-6">
        <div>
          <h1 className="text-white text-xl sm:text-2xl font-bold">Trade Journal</h1>
          <p className="text-slate-400 text-sm mt-1">{s.total_trades || 0} trades · {s.closed_trades || 0} closed</p>
        </div>
        <button onClick={() => setShowAdd(true)}
          className="flex items-center gap-1.5 px-3 sm:px-4 py-2 bg-violet-600 hover:bg-violet-500 text-white text-sm font-semibold rounded-lg transition-colors">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" /></svg>
          <span className="hidden sm:block">Add Trade</span>
          <span className="sm:hidden">Add</span>
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 lg:grid-cols-6 gap-2 sm:gap-3 mb-4 sm:mb-6">
        <SummaryCard label="Trades"   value={s.total_trades} />
        <SummaryCard label="Win Rate" value={s.win_rate != null ? `${s.win_rate}%` : null}
          color={s.win_rate >= 50 ? 'text-emerald-400' : 'text-amber-400'} />
        <SummaryCard label="Total P&L" value={s.total_pnl != null ? `₹${s.total_pnl?.toLocaleString('en-IN')}` : null}
          color={s.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'} />
        <SummaryCard label="Best"  value={s.best_trade  != null ? `₹${s.best_trade?.toLocaleString('en-IN')}` : null} color="text-emerald-400" />
        <SummaryCard label="Worst" value={s.worst_trade != null ? `₹${s.worst_trade?.toLocaleString('en-IN')}` : null} color="text-red-400" />
        <SummaryCard label="Avg Hold" value={s.avg_hold_days != null ? `${s.avg_hold_days}d` : null} />
      </div>

      {/* Equity curve */}
      <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-3 sm:p-4 mb-4 sm:mb-6">
        <h2 className="text-slate-300 text-sm font-semibold mb-3">Equity Curve</h2>
        <PnLChart trades={data.trades} />
      </div>

      {/* Mobile cards */}
      <div className="sm:hidden flex flex-col gap-2">
        {loading && <div className="text-center text-slate-500 py-8">Loading…</div>}
        {!loading && data.trades.length === 0 && <div className="text-center text-slate-500 py-8">No trades yet</div>}
        {data.trades.map(t => {
          const isOpen = t.sell_price == null
          const pnlPos = (t.pnl || 0) >= 0
          return (
            <div key={t.id} className="bg-slate-800/50 border border-slate-700/40 rounded-xl p-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-white font-bold">{t.symbol}</span>
                <div className="flex items-center gap-2">
                  {isOpen ? (
                    <button onClick={() => openClose(t)}
                      className="text-xs px-2 py-0.5 bg-violet-500/20 text-violet-300 rounded-full">Close</button>
                  ) : (
                    <span className={`text-xs font-semibold ${pnlPos ? 'text-emerald-400' : 'text-red-400'}`}>
                      {pnlPos ? '+' : ''}₹{t.pnl?.toLocaleString('en-IN')}
                    </span>
                  )}
                  <button onClick={() => handleDelete(t.id)} className="text-slate-600 hover:text-red-400 p-0.5">
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-1 text-xs text-slate-400">
                <div><span className="text-slate-500">Buy </span>₹{t.buy_price}</div>
                <div><span className="text-slate-500">Qty </span>{t.qty}</div>
                <div><span className="text-slate-500">Date </span>{t.entry_date}</div>
              </div>
              {!isOpen && (
                <div className="mt-1 text-xs text-slate-500">
                  Exit: {t.exit_reason} · ₹{t.sell_price} · {t.hold_days}d
                  {t.pnl_pct != null && <span className={pnlPos ? 'text-emerald-400' : 'text-red-400'}> · {t.pnl_pct > 0 ? '+' : ''}{t.pnl_pct}%</span>}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Desktop table */}
      <div className="hidden sm:block bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/50 bg-slate-900/40">
                {['Symbol','Buy','Qty','Sell','Exit Qty','P&L','P&L%','Reason','Entry','Exit','Days',''].map(h => (
                  <th key={h} className="text-left text-slate-400 font-medium px-4 py-3 whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={12} className="text-center text-slate-500 py-12">Loading…</td></tr>}
              {!loading && data.trades.length === 0 && (
                <tr><td colSpan={12} className="text-center text-slate-500 py-12">No trades yet — click Add Trade</td></tr>
              )}
              {data.trades.map(t => {
                const isOpen = t.sell_price == null
                const pnlPos = (t.pnl || 0) >= 0
                return (
                  <tr key={t.id} className="border-b border-slate-700/30 hover:bg-slate-700/20 transition-colors">
                    <td className="px-4 py-3 font-semibold text-white">{t.symbol}</td>
                    <td className="px-4 py-3 tabular-nums text-slate-200">₹{t.buy_price}</td>
                    <td className="px-4 py-3 text-slate-300">{t.qty}</td>
                    <td className="px-4 py-3 tabular-nums text-slate-400">
                      {t.sell_price ? `₹${t.sell_price}` : (
                        <button onClick={() => openClose(t)}
                          className="text-xs px-2 py-0.5 bg-violet-500/20 text-violet-300 rounded-full hover:bg-violet-500/30">Close</button>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-400">{t.exit_qty ?? '—'}</td>
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
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
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
              <input type={f.type} value={addForm[f.key]}
                onChange={e => setAddForm(v => ({ ...v, [f.key]: e.target.value }))}
                placeholder={f.placeholder}
                className="w-full bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-violet-500" />
            </div>
          ))}
          <button onClick={handleAdd} disabled={saving}
            className="w-full py-2.5 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white font-semibold rounded-lg">
            {saving ? 'Saving…' : 'Add Trade'}
          </button>
        </Modal>
      )}

      {/* Close Trade Modal */}
      {showClose && (
        <Modal title={`Close ${showClose.symbol}`} onClose={() => setShowClose(null)}>

          {/* Sell Price */}
          <div>
            <label className="text-slate-400 text-xs block mb-1">Sell Price (₹)</label>
            <input type="number" value={closeForm.sell_price}
              onChange={e => setCloseForm(v => ({ ...v, sell_price: e.target.value }))}
              placeholder="2500.00"
              className="w-full bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-violet-500" />
          </div>

          {/* Exit Quantity — with T1/T2 quick buttons */}
          <div>
            <label className="text-slate-400 text-xs block mb-1">
              Exit Quantity
              <span className="text-slate-500 ml-1">(total: {showClose.qty})</span>
            </label>
            <div className="flex gap-2 mb-2">
              {/* Quick select buttons */}
              <button onClick={() => setCloseForm(v => ({ ...v, exit_qty: String(Math.floor(showClose.qty / 2)), exit_reason: 'T1' }))}
                className="flex-1 text-xs py-1.5 bg-amber-500/20 text-amber-300 rounded-lg hover:bg-amber-500/30 font-medium">
                50% ({Math.floor(showClose.qty / 2)}) T1
              </button>
              <button onClick={() => setCloseForm(v => ({ ...v, exit_qty: String(showClose.qty - Math.floor(showClose.qty / 2)), exit_reason: 'T2' }))}
                className="flex-1 text-xs py-1.5 bg-emerald-500/20 text-emerald-300 rounded-lg hover:bg-emerald-500/30 font-medium">
                50% ({showClose.qty - Math.floor(showClose.qty / 2)}) T2
              </button>
              <button onClick={() => setCloseForm(v => ({ ...v, exit_qty: String(showClose.qty), exit_reason: 'manual' }))}
                className="flex-1 text-xs py-1.5 bg-slate-600 text-slate-300 rounded-lg hover:bg-slate-500 font-medium">
                All ({showClose.qty})
              </button>
            </div>
            <input type="number" value={closeForm.exit_qty}
              onChange={e => setCloseForm(v => ({ ...v, exit_qty: e.target.value }))}
              min={1} max={showClose.qty} placeholder={String(showClose.qty)}
              className="w-full bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-violet-500" />
          </div>

          {/* Exit Reason */}
          <div>
            <label className="text-slate-400 text-xs block mb-1">Exit Reason</label>
            <select value={closeForm.exit_reason}
              onChange={e => setCloseForm(v => ({ ...v, exit_reason: e.target.value }))}
              className="w-full bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-violet-500">
              {EXIT_REASONS.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>

          {/* Exit Date */}
          <div>
            <label className="text-slate-400 text-xs block mb-1">Exit Date</label>
            <input type="date" value={closeForm.exit_date}
              onChange={e => setCloseForm(v => ({ ...v, exit_date: e.target.value }))}
              className="w-full bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-violet-500" />
          </div>

          {/* Live P&L Preview */}
          <PnLPreview
            sellPrice={closeForm.sell_price}
            buyPrice={showClose.buy_price}
            qty={showClose.qty}
            exitQty={closeForm.exit_qty}
          />

          <button onClick={handleClose} disabled={saving || !closeForm.sell_price || !closeForm.exit_qty}
            className="w-full py-2.5 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white font-semibold rounded-lg">
            {saving ? 'Saving…' : `Close ${closeForm.exit_qty || ''} shares`}
          </button>
        </Modal>
      )}
    </div>
  )
}
