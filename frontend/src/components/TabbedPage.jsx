import { Suspense } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { InTabs, Loading, PageHead } from './ui';

/** Related screens shown as tabs under one heading. Each tab keeps its own URL. */
export default function TabbedPage({ title, subtitle, tabs }) {
  return (
    <>
      <PageHead title={title} subtitle={subtitle} />
      <PageTabs tabs={tabs} />
      <InTabs.Provider value><Suspense fallback={<Loading />}><Outlet /></Suspense></InTabs.Provider>
    </>
  );
}

export function PageTabs({ tabs }) {
  return (
    <nav className="page-tabs" aria-label="Sections">
      {tabs.map(([to, label, end = true]) => <NavLink key={to} to={to} end={end}>{label}</NavLink>)}
    </nav>
  );
}
