document.addEventListener('DOMContentLoaded', () => {
  // Inject Dynamic Math Floating Symbols Background CSS
  const style = document.createElement('style');
  style.textContent = `
    body { 
      background: radial-gradient(circle at top right, #1a1e2e, #0a0c10) !important; 
    }
    .math-bg { 
      position: fixed; 
      top: 0; left: 0; 
      width: 100vw; height: 100vh; 
      z-index: -100; 
      overflow: hidden; 
      pointer-events: none; 
    }
    .math-sym { 
      position: absolute; 
      bottom: -15vh; 
      font-family: 'Times New Roman', Times, serif; 
      color: var(--accent, #ff8c42); 
      font-weight: bold; 
      animation: floatUp linear infinite; 
      filter: drop-shadow(0 0 8px rgba(255,140,66,0.6)); 
    }
    @keyframes floatUp {
      0%   { transform: translateY(0) rotate(0deg); opacity: 0; }
      15%  { opacity: var(--max-op); }
      85%  { opacity: var(--max-op); }
      100% { transform: translateY(-120vh) rotate(360deg); opacity: 0; }
    }
  `;
  document.head.appendChild(style);

  // Inject Math Symbols
  const symbols = ['∑', '∫', 'π', '∞', '√', '∆', 'µ', 'θ', '±', '≠', '≈', '÷', 'α', 'β', 'Ω'];
  const bg = document.createElement('div');
  bg.className = 'math-bg';
  document.body.appendChild(bg);
  
  // Create 35 floating symbols with random parameters
  for (let i = 0; i < 35; i++) {
    const sym = document.createElement('div');
    sym.className = 'math-sym';
    sym.textContent = symbols[Math.floor(Math.random() * symbols.length)];
    sym.style.left = Math.random() * 100 + 'vw';
    sym.style.animationDuration = (Math.random() * 20 + 15) + 's';
    sym.style.animationDelay = (Math.random() * -20) + 's';
    sym.style.fontSize = (Math.random() * 2.5 + 1.2) + 'rem';
    sym.style.setProperty('--max-op', (Math.random() * 0.15 + 0.1).toString());
    bg.appendChild(sym);
  }
});
