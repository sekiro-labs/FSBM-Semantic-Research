import { NavLink, Outlet } from 'react-router'
import fsbmLogo from '../assets/fsbm-universite-hassan-ii.png'

const navigation = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/researchers', label: 'Researchers' },
  { to: '/publications', label: 'Publications' },
  { to: '/search', label: 'Semantic Search' },
]

export function Layout() {
  return <div className="site-shell">
    <a className="skip-link" href="#main">Skip to content</a>
    <header className="site-header">
      <div className="header-inner">
        <NavLink to="/" className="brand" aria-label="FSBM Semantic Research home">
          <img className="brand-logo" src={fsbmLogo} width={1672} height={941}
            alt="Logo de la Faculté des Sciences Ben M'Sick - Université Hassan II de Casablanca" />
          <span className="brand-identity"><strong>FSBM Semantic Research</strong>
            <small>Faculté des Sciences Ben M'Sick<br />Université Hassan II de Casablanca</small>
          </span>
        </NavLink>
        <nav className="main-nav" aria-label="Main navigation">
          {navigation.map(item => <NavLink key={item.to} to={item.to} end={item.end}
            className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>{item.label}</NavLink>)}
        </nav>
      </div>
    </header>
    <main id="main" className="main-content"><Outlet /></main>
    <footer className="site-footer"><span>FSBM Semantic Research — NLP &amp; Web Scraping</span><span>Academic research explorer</span></footer>
  </div>
}
