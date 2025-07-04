// Универсальная отправка события во все пиксели и аналитику
function sendUserEvent(eventName, params = {}) {
  if (window.gtag) gtag('event', eventName, params);
  // if (window.ym) ym(ВАШ_ID, 'reachGoal', eventName);
  if (window.fbq) fbq('trackCustom', eventName, params);
  if (window.ttq) ttq.track(eventName, params);
}

// Blink (моргание)
let lastBlur = 0;
window.addEventListener('blur', () => { lastBlur = Date.now(); });
window.addEventListener('focus', () => {
  if (lastBlur && Date.now() - lastBlur > 100) {
    sendUserEvent('blink');
  }
});

// Scroll depth (25%, 50%, 75%, 100%)
let scrollTracked = {25: false, 50: false, 75: false, 100: false};
window.addEventListener('scroll', () => {
  const scrollTop = window.scrollY;
  const docHeight = document.documentElement.scrollHeight - window.innerHeight;
  if (docHeight <= 0) return;
  const percent = Math.round((scrollTop / docHeight) * 100);
  [25, 50, 75, 100].forEach(p => {
    if (!scrollTracked[p] && percent >= p) {
      sendUserEvent('scroll_' + p);
      scrollTracked[p] = true;
    }
  });
});

// Клики по кнопкам
if (typeof document !== 'undefined') {
  document.addEventListener('click', e => {
    const btn = e.target.closest('button, a');
    if (btn) {
      sendUserEvent('click', {text: btn.innerText || btn.value || btn.id || 'button'});
    }
  });

  // Копирование текста
  document.addEventListener('copy', () => {
    sendUserEvent('copy');
  });

  // Выделение текста
  document.addEventListener('selectionchange', () => {
    const sel = window.getSelection();
    if (sel && sel.toString().length > 5) {
      sendUserEvent('select_text', {text: sel.toString().slice(0, 100)});
    }
  });

  // Время на странице (10, 30, 60 сек)
  [10, 30, 60].forEach(sec => {
    setTimeout(() => sendUserEvent('time_' + sec + 's'), sec * 1000);
  });

  // Взаимодействие с формой (input, change, submit)
  document.addEventListener('input', e => {
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) {
      sendUserEvent('form_input', {name: e.target.name || e.target.id || ''});
    }
  });
  document.addEventListener('change', e => {
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT')) {
      sendUserEvent('form_change', {name: e.target.name || e.target.id || ''});
    }
  });
  document.addEventListener('submit', e => {
    sendUserEvent('form_submit');
  });
}

// Уход со страницы — используем visibilitychange вместо beforeunload
window.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') {
    sendUserEvent('leave');
  }
});

// 72-часовой отсчёт
(function() {
  const DURATION = 72 * 60 * 60 * 1000;
  const END_KEY = 'promoCountdownEnd';
  let endTime = localStorage.getItem(END_KEY);
  if (!endTime || isNaN(Number(endTime)) || Number(endTime) < Date.now()) {
    endTime = Date.now() + DURATION;
    localStorage.setItem(END_KEY, endTime);
  } else {
    endTime = Number(endTime);
  }
  function pad(n) { return n < 10 ? '0' + n : n; }
  function updateCountdown() {
    const now = Date.now();
    let diff = endTime - now;
    if (diff < 0) diff = 0;
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    const seconds = Math.floor((diff % (1000 * 60)) / 1000);
    const h = document.getElementById('countdown-hours');
    const m = document.getElementById('countdown-minutes');
    const s = document.getElementById('countdown-seconds');
    if (h) h.textContent = pad(hours);
    if (m) m.textContent = pad(minutes);
    if (s) s.textContent = pad(seconds);
    if (diff > 0) {
      setTimeout(updateCountdown, 1000);
    }
  }
  updateCountdown();
})();

// Анимация счётчиков
if (typeof document !== 'undefined') {
  document.addEventListener("DOMContentLoaded", function() {
    const counters = document.querySelectorAll('.counter[data-target]');
    const speed = 200;
    counters.forEach(counter => {
      function animate() {
        const target = +counter.getAttribute('data-target');
        const current = +counter.innerText.replace(/\s/g, '');
        const increment = Math.max(1, Math.ceil(target / speed));
        if (current < target) {
          counter.innerText = (current + increment).toLocaleString('ru-RU');
          setTimeout(animate, 10);
        } else {
          counter.innerText = target.toLocaleString('ru-RU');
        }
      }
      animate();
    });
  });
}

// FAQ-аккордеон
if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', function() {
    const faqItems = document.querySelectorAll('.faq-item');
    faqItems.forEach(item => {
      const btn = item.querySelector('.faq-question');
      const answer = item.querySelector('.faq-answer');
      const icon = item.querySelector('.faq-icon');
      answer.style.maxHeight = '0';
      answer.style.paddingTop = '0';
      answer.style.paddingBottom = '0';
      btn.addEventListener('click', () => {
        const isOpen = answer.style.maxHeight !== '0px';
        faqItems.forEach(el => {
          if (el !== item) {
            el.querySelector('.faq-answer').style.maxHeight = '0';
            el.querySelector('.faq-answer').style.paddingTop = '0';
            el.querySelector('.faq-answer').style.paddingBottom = '0';
            el.querySelector('.faq-icon').textContent = '+';
            el.querySelector('.faq-icon').style.transform = 'rotate(0deg)';
            el.classList.remove('active');
          }
        });
        if (!isOpen) {
          const answerContent = answer.querySelector('div');
          answer.style.maxHeight = answerContent.scrollHeight + 'px';
          answer.style.paddingTop = '1rem';
          answer.style.paddingBottom = '1rem';
          icon.textContent = '−';
          icon.style.transform = 'rotate(180deg)';
          item.classList.add('active');
        } else {
          answer.style.maxHeight = '0';
          answer.style.paddingTop = '0';
          answer.style.paddingBottom = '0';
          icon.textContent = '+';
          icon.style.transform = 'rotate(0deg)';
          item.classList.remove('active');
        }
      });
    });
    window.addEventListener('resize', () => {
      document.querySelectorAll('.faq-item.active').forEach(item => {
        const answer = item.querySelector('.faq-answer');
        const answerContent = answer.querySelector('div');
        answer.style.maxHeight = answerContent.scrollHeight + 'px';
      });
    });
  });
} 