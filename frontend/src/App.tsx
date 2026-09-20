import { BrowserRouter, Link, Route, Routes } from 'react-router'
import { Layout } from './components/Layout'
import { Dashboard } from './pages/Dashboard'
import { PublicationDetail } from './pages/PublicationDetail'
import { Publications } from './pages/Publications'
import { ResearcherDetail } from './pages/ResearcherDetail'
import { Researchers } from './pages/Researchers'
import { Search } from './pages/Search'

export default function App() {
  return <BrowserRouter><Routes><Route element={<Layout />}>
    <Route path="/" element={<Dashboard />} />
    <Route path="/search" element={<Search />} />
    <Route path="/researchers" element={<Researchers />} />
    <Route path="/researchers/:id" element={<ResearcherDetail />} />
    <Route path="/publications" element={<Publications />} />
    <Route path="/publications/:id" element={<PublicationDetail />} />
    <Route path="*" element={<div className="page-narrow not-found"><h1>Page not found</h1><p>This page does not exist.</p><Link to="/" className="button primary">Back to dashboard</Link></div>} />
  </Route></Routes></BrowserRouter>
}
