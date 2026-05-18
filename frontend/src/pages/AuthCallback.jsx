// frontend/src/pages/AuthCallback.jsx
// This page is loaded inside the popup window after Upstox OAuth redirect.
// It shows success/failure and closes the popup automatically.
import { useEffect, useState } from 'react'

export default function AuthCallback() {
  const [status, setStatus] = useState('checking') // checking | success | error
  const [message, setMessage] = useState('')

  useEffect(() => {
    // The backend already handled the token exchange via /upstox/callback
    // This page is just the landing page shown in the popup
    // Check if we have an error param in URL (backend redirects here on error)
    const params = new URLSearchParams(window.location.search)
    const error = params.get('error')

    if (error) {
      setStatus('error')
      setMessage(error)
    } else {
      setStatus('success')
      setMessage('Upstox connected successfully!')
      // Auto-close popup after 2 seconds
      setTimeout(() => {
        window.close()
      }, 2000)
    }
  }, [])

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center p-4">
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-8 w-full max-w-sm text-center">

        {status === 'checking' && (
          <>
            <div className="w-12 h-12 rounded-full bg-slate-700 flex items-center justify-center mx-auto mb-4">
              <svg className="w-6 h-6 text-slate-400 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
            </div>
            <p className="text-slate-300 font-medium">Connecting to Upstox…</p>
          </>
        )}

        {status === 'success' && (
          <>
            <div className="w-14 h-14 rounded-full bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center mx-auto mb-4">
              <svg className="w-7 h-7 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h2 className="text-white text-lg font-bold mb-2">Connected!</h2>
            <p className="text-emerald-400 text-sm mb-4">{message}</p>
            <p className="text-slate-500 text-xs">This window will close automatically…</p>
            <button
              onClick={() => window.close()}
              className="mt-4 w-full py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-semibold rounded-lg transition-colors"
            >
              Close Window
            </button>
          </>
        )}

        {status === 'error' && (
          <>
            <div className="w-14 h-14 rounded-full bg-red-500/20 border border-red-500/40 flex items-center justify-center mx-auto mb-4">
              <svg className="w-7 h-7 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
            <h2 className="text-white text-lg font-bold mb-2">Connection Failed</h2>
            <p className="text-red-400 text-sm mb-4">{message || 'Upstox authentication failed'}</p>
            <button
              onClick={() => window.close()}
              className="w-full py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm font-semibold rounded-lg transition-colors"
            >
              Close Window
            </button>
          </>
        )}

      </div>
    </div>
  )
}
