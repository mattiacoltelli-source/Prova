if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('./sw.js').catch(err => console.log('SW registration failed:', err));
  });
}

let currentAsset = 'SPY';
let appData = null;

async function loadData() {
  try {
    const res = await fetch('./data.json?t=' + Date.now());
    if (res.ok) {
      appData = await res.json();
      renderApp();
    }
  } catch (e) {
    console.error('Error loading data.json:', e);
  }
}

function renderApp() {
  if (!appData) return;

  document.getElementById('globalAccuracy').textContent = `${appData.global_accuracy_pct.toFixed(1)}%`;
  document.getElementById('totalEvaluated').textContent = appData.total_evaluated;
  document.getElementById('totalPending').textContent = appData.total_pending;

  const assetData = appData.assets[currentAsset] || { accuracy_pct: 0, evaluated: [], predictions: [], chart_points: [] };

  document.getElementById('assetAccuracy').textContent = `Accuratezza: ${assetData.accuracy_pct.toFixed(1)}%`;

  renderChart(assetData.chart_points || []);
  renderEvaluatedTable(assetData.evaluated || []);
  renderPredictionsTable(assetData.predictions || []);
}

function renderChart(points) {
  const svg = document.getElementById('chartSvg');
  if (!points || points.length === 0) {
    svg.innerHTML = `<text x="150" y="75" fill="#94a3b8" font-size="12" text-anchor="middle">Nessun dato grafico disponibile</text>`;
    return;
  }

  const padding = 20;
  const width = 300;
  const height = 150;

  const prices = points.map(p => p.price);
  const minP = Math.min(...prices) * 0.995;
  const maxP = Math.max(...prices) * 1.005;

  const getX = (i) => padding + (i / Math.max(1, points.length - 1)) * (width - 2 * padding);
  const getY = (p) => height - padding - ((p - minP) / Math.max(0.01, maxP - minP)) * (height - 2 * padding);

  let pathD = '';
  points.forEach((pt, i) => {
    const x = getX(i);
    const y = getY(pt.price);
    pathD += (i === 0 ? `M ${x} ${y}` : ` L ${x} ${y}`);
  });

  let dotsSvg = '';
  points.forEach((pt, i) => {
    const x = getX(i);
    const y = getY(pt.price);
    const color = pt.type === 'target' ? '#10b981' : '#38bdf8';
    dotsSvg += `<circle cx="${x}" cy="${y}" r="4" fill="${color}" />`;
  });

  svg.innerHTML = `
    <path d="${pathD}" fill="none" stroke="#2563eb" stroke-width="2" />
    ${dotsSvg}
  `;
}

function renderEvaluatedTable(items) {
  const tbody = document.getElementById('evaluatedTableBody');
  if (!items || items.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-msg">Nessuna valutazione ancora.</td></tr>`;
    return;
  }

  tbody.innerHTML = items.slice(0, 5).map(item => `
    <tr>
      <td>${item.date || '-'}</td>
      <td>${item.horizon || '-'}</td>
      <td><span class="badge ${item.predicted?.toLowerCase()}">${item.predicted || '-'}</span></td>
      <td><span class="badge ${item.actual?.toLowerCase()}">${item.actual || '-'}</span></td>
      <td>${item.correct ? '✅ Pass' : '❌ Fail'}</td>
    </tr>
  `).join('');
}

function renderPredictionsTable(items) {
  const tbody = document.getElementById('predictionsTableBody');
  if (!items || items.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4" class="empty-msg">Nessuna predizione registrata.</td></tr>`;
    return;
  }

  tbody.innerHTML = items.slice(0, 5).map(item => `
    <tr>
      <td>${item.date || '-'}</td>
      <td>${item.horizon || '-'}</td>
      <td><span class="badge ${item.predicted_class?.toLowerCase()}">${item.predicted_class || '-'}</span></td>
      <td>${item.confidence ? item.confidence + '%' : '-'}</td>
    </tr>
  `).join('');
}

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', (e) => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    e.target.classList.add('active');
    currentAsset = e.target.dataset.asset;
    renderApp();
  });
});

document.getElementById('refreshBtn').addEventListener('click', () => {
  loadData();
});

document.getElementById('newPredBtn').addEventListener('click', () => {
  alert('I workflow predittivi girano automaticamente su GitHub Actions o via CLI con python -m src.predict_run');
});

document.getElementById('evaluateBtn').addEventListener('click', () => {
  alert('I workflow di valutazione girano automaticamente su GitHub Actions o via CLI con python -m src.evaluate_run');
});

loadData();
