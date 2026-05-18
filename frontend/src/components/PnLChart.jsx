// frontend/src/components/PnLChart.jsx
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceLine, ResponsiveContainer
} from 'recharts'

function buildEquityCurve(trades) {
  // Build cumulative P&L series from closed trades sorted by exit_date
  const closed = trades
    .filter(t => t.sell_price != null && t.exit_date)
    .sort((a, b) => new Date(a.exit_date) - new Date(b.exit_date))

  let cumulative = 0
  return closed.map(t => {
    cumulative += t.pnl || 0
    return {
      date: t.exit_date,
      pnl: Math.round(t.pnl || 0),
      cumulative: Math.round(cumulative),
      symbol: t.symbol,
      exit_reason: t.exit_reason,
    }
  })
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div className="bg-slate-800 border border-slate-600 rounded-xl p-3 text-xs shadow-xl">
      <div className="text-slate-400 mb-1">{d.date}</div>
      <div className="text-white font-semibold">{d.symbol} · {d.exit_reason}</div>
      <div className={`font-bold mt-1 ${d.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
        Trade: {d.pnl >= 0 ? '+' : ''}₹{d.pnl.toLocaleString('en-IN')}
      </div>
      <div className={`${d.cumulative >= 0 ? 'text-emerald-300' : 'text-red-300'}`}>
        Total: {d.cumulative >= 0 ? '+' : ''}₹{d.cumulative.toLocaleString('en-IN')}
      </div>
    </div>
  )
}

export default function PnLChart({ trades }) {
  const data = buildEquityCurve(trades)

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-slate-500 text-sm">
        No closed trades yet
      </div>
    )
  }

  const isPositive = data[data.length - 1]?.cumulative >= 0
  const strokeColor = isPositive ? '#34d399' : '#f87171'

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 10, right: 20, left: 10, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" strokeOpacity={0.5} />
        <XAxis
          dataKey="date"
          tick={{ fill: '#94a3b8', fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: '#334155' }}
          interval="preserveStartEnd"
        />
        <YAxis
          tick={{ fill: '#94a3b8', fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          tickFormatter={v => `₹${(v / 1000).toFixed(0)}k`}
          width={55}
        />
        <Tooltip content={<CustomTooltip />} />
        <ReferenceLine y={0} stroke="#475569" strokeDasharray="4 4" />
        <Line
          type="monotone"
          dataKey="cumulative"
          stroke={strokeColor}
          strokeWidth={2}
          dot={{ fill: strokeColor, r: 3, strokeWidth: 0 }}
          activeDot={{ r: 5, fill: strokeColor }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
