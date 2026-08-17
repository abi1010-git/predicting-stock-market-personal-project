"use client";

import { useEffect, useState } from "react";

const prices = [603, 598, 612, 609, 626, 638, 632, 647, 655, 649, 668, 675, 688, 681, 701, 716, 708, 729, 742, 735, 751, 764, 757, 776];
const tickers = [
  { symbol: "SPY", label: "S&P 500 ETF", change: "+0.62%" },
  { symbol: "QQQ", label: "Nasdaq 100 ETF", change: "+0.84%" },
  { symbol: "IWM", label: "Russell 2000 ETF", change: "+0.31%" },
  { symbol: "AAPL", label: "Apple", change: "+1.08%" },
  { symbol: "NVDA", label: "NVIDIA", change: "+1.42%" },
];

function PriceChart() {
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  return (
    <div className="price-chart" aria-label="Illustrative SPY price trend">
      <div className="grid-lines" />
      <div className="chart-bars">
        {prices.map((price, index) => (
          <i key={index} style={{ height: `${22 + ((price - min) / (max - min)) * 68}%`, animationDelay: `${index * 45}ms` }} />
        ))}
      </div>
      <div className="chart-label top">$776.34</div>
      <div className="chart-label bottom">JAN 2026</div>
    </div>
  );
}

function Reveal({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`reveal ${className}`}>{children}</div>;
}

export function Dashboard() {
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => entries.forEach((entry) => entry.isIntersecting && entry.target.classList.add("visible")),
      { threshold: 0.16 },
    );
    document.querySelectorAll(".reveal").forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, []);

  return (
    <main>
      <div className="ticker-tape" aria-label="Tracked market universe">
        <div className="ticker-track">{[...tickers, ...tickers].map((ticker, i) => <span key={`${ticker.symbol}-${i}`}><b>{ticker.symbol}</b> {ticker.change}</span>)}</div>
      </div>
      <nav className="nav-shell">
        <a className="brand" href="#top" aria-label="SignalFive home"><span>S5</span> SignalFive</a>
        <button className="menu" onClick={() => setMenuOpen(!menuOpen)} aria-expanded={menuOpen}>Menu</button>
        <div className={menuOpen ? "nav-links open" : "nav-links"}>
          <a href="#system">System</a><a href="#models">Models</a><a href="#method">Method</a><a href="#about">About</a>
          <a className="repo-link" href="https://github.com/abi1010-git/predicting-stock-market-personal-project" target="_blank" rel="noreferrer">View source ↗</a>
        </div>
      </nav>

      <section className="hero" id="top">
        <div className="hero-copy">
          <p className="eyebrow"><span className="pulse" /> RESEARCH SYSTEM · DAILY</p>
          <h1>Can the market’s recent structure inform its next <em>five sessions?</em></h1>
          <p className="lede">A reproducible machine-learning experiment that studies whether SPY will close higher five trading sessions ahead—without pretending uncertainty is certainty.</p>
          <div className="hero-actions"><a className="primary" href="#system">Explore the system</a><a className="secondary" href="#method">Read methodology ↓</a></div>
          <div className="stat-row"><div><strong>5</strong><span>tracked assets</span></div><div><strong>12</strong><span>lag-safe features</span></div><div><strong>5×</strong><span>walk-forward folds</span></div></div>
        </div>
        <div className="terminal-card">
          <div className="card-head"><span>SPY / DAILY</span><span className="healthy">● PIPELINE HEALTHY</span></div>
          <div className="quote"><div><small>LAST OBSERVED CLOSE</small><strong>$776.34</strong></div><span>14 AUG 2026</span></div>
          <PriceChart />
          <div className="terminal-foot"><span>Research history</span><b>4,179 sessions · since 2010</b></div>
        </div>
      </section>

      <section className="universe-strip">{tickers.map(t => <div key={t.symbol}><span className="asset-icon">{t.symbol.slice(0, 1)}</span><p><b>{t.symbol}</b><small>{t.label}</small></p><strong>{t.change}</strong></div>)}</section>

      <section className="section system" id="system">
        <Reveal className="section-heading"><p className="eyebrow">01 / SYSTEM</p><h2>From raw prices to an auditable experiment.</h2><p>Each stage is separate, testable, and visible. Data lineage and leakage prevention are part of the product—not footnotes.</p></Reveal>
        <div className="pipeline-flow">
          {[['01','INGEST','Yahoo Finance historical + daily OHLCV'],['02','VALIDATE','Schema, duplicates, nulls, price consistency'],['03','ENGINEER','Momentum, trend, volatility, volume signals'],['04','EVALUATE','Gap-aware walk-forward classification'],['05','REPORT','Metrics, benchmark and limitations']].map((item, i) => (
            <Reveal className="flow-node" key={item[0]}><span>{item[0]}</span><div className="node-dot" /><h3>{item[1]}</h3><p>{item[2]}</p>{i < 4 && <i className="connector" />}</Reveal>
          ))}
        </div>
      </section>

      <section className="section model-section" id="models">
        <Reveal className="section-heading"><p className="eyebrow">02 / MODELS</p><h2>Four perspectives. One honest baseline.</h2><p>The question is not which model sounds most sophisticated. It is whether any model improves on a simple majority-class prediction out of sample.</p></Reveal>
        <div className="model-grid">
          {[['BASELINE','Majority class','The minimum bar','01','0.487'],['LINEAR','Logistic regression','Interpretable probability','02','0.497'],['ENSEMBLE','Random forest','Nonlinear interactions','03','0.493'],['BOOSTING','CatBoost','Sequential error correction','04','0.513']].map((m, i) => <Reveal className={`model-card ${i===3?'accent':''}`} key={m[1]}><span>{m[0]}</span><b>{m[3]}</b><h3>{m[1]}</h3><p>{m[2]}</p><div className="metric-value"><strong>{m[4]}</strong><span>OUT-OF-SAMPLE ROC AUC</span></div><div className="metric-placeholder"><i style={{width:`${Number(m[4])*100}%`}} /></div><small>5-fold evaluation · through 07 Aug 2026</small></Reveal>)}
        </div>
      </section>

      <section className="section method" id="method">
        <Reveal className="method-copy"><p className="eyebrow">03 / METHOD</p><h2>Time is the constraint.</h2><p>Random train/test splits would let future market regimes leak backward. The evaluation moves forward through time and leaves a five-session gap between training and testing.</p><ul><li><b>No look-ahead</b><span>Features use only information available on prediction day.</span></li><li><b>Five-session gap</b><span>The split gap matches the forecast horizon.</span></li><li><b>Trading costs</b><span>Backtests deduct five basis points when positions change.</span></li></ul></Reveal>
        <Reveal className="timeline-card">
          <div className="timeline-head"><span>WALK-FORWARD VALIDATION</span><b>TIME →</b></div>
          {[1,2,3,4,5].map((fold) => <div className="fold" key={fold}><small>FOLD {fold}</small><div className="train" style={{width:`${24+fold*8}%`}}>TRAIN</div><div className="gap">GAP</div><div className="test">TEST</div></div>)}
          <p>Every test window remains chronologically unseen.</p>
        </Reveal>
      </section>

      <section className="section data-section">
        <Reveal className="data-card"><p className="eyebrow">DATA QUALITY · 20,895 ROWS</p><strong>HEALTHY</strong><div className="quality-ring"><span>100<small>%</small></span></div><ul><li><span>Duplicate dates</span><b>0</b></li><li><span>Null prices</span><b>0</b></li><li><span>Assets monitored</span><b>5</b></li></ul></Reveal>
        <Reveal className="data-copy"><p className="eyebrow">04 / TRANSPARENCY</p><h2>Built to be questioned.</h2><p>Every result should be reproducible from committed data and code. Historical and daily rows retain source provenance, recent observations are refreshed to capture corrections, and model performance is withheld until minimum sample requirements are met.</p><div className="source-tags"><span>YAHOO FINANCE · OHLCV</span><span>7-DAY · REFRESH</span><span>GITHUB ACTIONS · AUTOMATION</span></div></Reveal>
      </section>

      <section className="section final-section" id="about"><Reveal><p className="eyebrow">RESEARCH, NOT RECOMMENDATION</p><h2>A market model should communicate its limits as clearly as its signal.</h2><a className="primary" href="https://github.com/abi1010-git/predicting-stock-market-personal-project" target="_blank" rel="noreferrer">Inspect the repository ↗</a></Reveal></section>
      <footer><a className="brand" href="#top"><span>S5</span> SignalFive</a><p>Educational research only. Not financial advice, a security recommendation, or a guarantee of future results.</p><span>Built as an auditable ML study · 2026</span></footer>
    </main>
  );
}
