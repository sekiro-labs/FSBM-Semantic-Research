import { NavLink, Outlet } from 'react-router'

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
          <span className="brand-mark" aria-hidden="true">FS</span>
          <span><strong>FSBM Semantic Research</strong><small>Cartographie Sémantique des Publications Scientifiques</small></span>
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
