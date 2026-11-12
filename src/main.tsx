import { StrictMode, lazy, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import './index.css'
import Landing from './pages/Landing'
import { keepFlushing } from './lib/orders'

// Orders saved locally while the bot was unreachable are re-sent on every page load until accepted.
keepFlushing()

const Checkout = lazy(() => import('./pages/Checkout'))
const Admin = lazy(() => import('./pages/admin/AdminApp'))

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route
          path="/commande"
          element={
            <Suspense fallback={null}>
              <Checkout />
            </Suspense>
          }
        />
        <Route
          path="/admin/*"
          element={
            <Suspense fallback={null}>
              <Admin />
            </Suspense>
          }
        />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
