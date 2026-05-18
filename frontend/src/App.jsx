// frontend/src/App.jsx
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Navbar from './components/Navbar'
import Dashboard from './pages/Dashboard'
import Signals from './pages/Signals'
import Trades from './pages/Trades'
import AuthCallback from './pages/AuthCallback'
import { useWebSocket } from './hooks/useWebSocket'

function AppInner() {
  useWebSocket()
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Routes>
        {/* Auth callback runs in popup — no navbar */}
        <Route path="/auth/callback" element={<AuthCallback />} />
        {/* Main app */}
        <Route path="*" element={
          <>
            <Navbar />
            <Routes>
              <Route path="/"        element={<Dashboard />} />
              <Route path="/signals" element={<Signals />} />
              <Route path="/trades"  element={<Trades />} />
            </Routes>
          </>
        } />
      </Routes>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AppInner />
    </BrowserRouter>
  )
}
