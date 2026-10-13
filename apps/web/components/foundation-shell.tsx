const items = [
  { label: "Dashboard", icon: "▦", phase: "12" },
  { label: "Prospects", icon: "♙", phase: "04" },
  { label: "Promoters", icon: "♧", phase: "05" },
  { label: "Collections", icon: "▣", phase: "08" },
  { label: "Payouts", icon: "◉", phase: "09" },
  { label: "Reminders", icon: "♧", phase: "11" },
  { label: "Settings", icon: "⚙", phase: "03" },
] as const;

export function FoundationShell() {
  return (
    <div className="shell">
      <aside className="sidebar" aria-label="Application design preview">
        <div className="brand"><span className="brand-symbol" aria-hidden="true">☾</span>
          <div>Sponsor a Salah<span className="brand-subtitle">Emlen Foundation</span></div>
        </div>
        <nav className="nav" aria-label="Planned modules">
          {items.map((item) => (
            <span className="nav-entry pending" key={item.label} title={`Scheduled for phase ${item.phase}`} aria-disabled="true">
              <span className="nav-icon" aria-hidden="true">{item.icon}</span>{item.label}
            </span>
          ))}
        </nav>
        <div className="sidebar-footer">Foundation preview · No accounts or live data</div>
      </aside>
      <main className="main">
        <div className="intro">
          <span className="eyebrow">Phase 01 / Project Foundation</span>
          <h1>Sponsor a Salah</h1>
          <p>The foundation for the Emlen charity operations system is being built. This is a design-system and application scaffold, not the live admin dashboard.</p>
        </div>
        <section className="panel" aria-labelledby="phase-heading">
          <h2 id="phase-heading">Building the foundation</h2>
          <p>Project structure, PostgreSQL migrations, API probes, CI and the approved typography are established first. Each business module will be delivered and tested in a separate phase.</p>
          <div className="phase-list" aria-label="Current foundation work">
            <span className="phase-tag">Next.js + TypeScript</span>
            <span className="phase-tag">FastAPI</span>
            <span className="phase-tag">PostgreSQL</span>
            <span className="phase-tag">Automated checks</span>
          </div>
        </section>
        <p className="notice">Business functions remain unavailable until Admin authentication and the relevant module phases are complete. No financial processing is enabled.</p>
      </main>
    </div>
  );
}
