import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL || 'https://stock-signals-4fec.onrender.com'

export const api = axios.create({
  baseURL: BASE,
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.response.use(
  r => r,
  err => {
    console.error('[API]', err.response?.status, err.config?.url, err.response?.data)
    return Promise.reject(err)
  }
)

export const fetchTodaySignals = (strategy) =>
  api.get('/signals', { params: { strategy } }).then(r => r.data)

export const fetchSignalHistory = (params) =>
  api.get('/signals/history', { params }).then(r => r.data)

export const fetchSignal = (id) =>
  api.get(`/signals/${id}`).then(r => r.data)

export const updateSignalStatus = (id, status) =>
  api.patch(`/signals/${id}/status`, null, { params: { status } }).then(r => r.data)

export const fetchTrades = (params) =>
  api.get('/trades', { params }).then(r => r.data)

export const createTrade = (body) =>
  api.post('/trades', body).then(r => r.data)

export const closeTrade = (id, body) =>
  api.put(`/trades/${id}`, body).then(r => r.data)

export const deleteTrade = (id) =>
  api.delete(`/trades/${id}`).then(r => r.data)

export const triggerScan = (universe = 'both') =>
  api.post('/scanner/run', null, { params: { universe } }).then(r => r.data)

export const fetchScannerStatus = () =>
  api.get('/scanner/status').then(r => r.data)
