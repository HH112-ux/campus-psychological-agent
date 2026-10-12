/* 心屿开发文档 · 原型与文档交互 */
(function () {
  'use strict';

  /* ---------- Mermaid 初始化 ---------- */
  if (window.mermaid) {
    mermaid.initialize({ startOnLoad: true, theme: 'neutral', securityLevel: 'loose' });
  }

  /* ---------- 功能名称映射（链接指示器用） ---------- */
  var featureNames = {
    'feature-home': 'F1 首页与情绪打卡',
    'feature-chat': 'F2 对话陪伴',
    'feature-emotion': 'F3 情绪识别与疏导',
    'feature-crisis': 'F4 危机干预',
    'feature-log': 'F5 情绪日志',
    'feature-mine': 'F6 账户与数据'
  };

  /* ---------- Tab 切换 ---------- */
  window.switchTab = function (tabId) {
    document.querySelectorAll('.tab-bar .tab-btn').forEach(function (b) { b.classList.remove('active'); });
    document.querySelectorAll('.tab-content-wrapper > .tab-pane').forEach(function (p) { p.classList.remove('active'); });
    var btn = document.querySelector('.tab-bar [data-tab="' + tabId + '"]');
    var pane = document.getElementById(tabId);
    if (btn) btn.classList.add('active');
    if (pane) pane.classList.add('active');
  };

  /* ---------- 原型页面切换 ---------- */
  window.navigate = function (pageId) {
    document.querySelectorAll('.phone-screen .page').forEach(function (p) { p.classList.remove('active'); });
    var target = document.getElementById(pageId);
    if (target) target.classList.add('active');
    if (pageId === 'page-home') {
      document.querySelectorAll('#page-home .tab-item').forEach(function (t, i) {
        t.classList.toggle('active', t.getAttribute('onclick').indexOf('page-home') > -1);
      });
    } else {
      var sel = '#page-home .tab-item';
      var pages = ['page-home', 'page-chat', 'page-log', 'page-mine'];
      document.querySelectorAll('.page').forEach(function (page) {
        if (!page.id) return;
        var idx = pages.indexOf(page.id);
        if (idx < 0) return;
        var items = page.querySelectorAll('.page-tabbar .tab-item');
        items.forEach(function (t) {
          t.classList.toggle('active', t.getAttribute('onclick').indexOf("navigate('" + page.id + "')") > -1);
        });
      });
    }
  };

  /* ---------- 情绪打卡选中 ---------- */
  window.pickMood = function (btn) {
    document.querySelectorAll('.mood-row .mood-btn').forEach(function (b) { b.classList.remove('selected'); });
    btn.classList.add('selected');
  };

  /* ---------- 危机卡片浮层（含文本模式克隆副本） ---------- */
  window.toggleCrisis = function (show) {
    document.querySelectorAll('.crisis-overlay').forEach(function (o) {
      o.classList.toggle('show', show);
    });
  };

  /* ---------- 原型 → 文档联动 ---------- */
  function linkToFeature(featureId) {
    switchTab('tab-features');
    window.setTimeout(function () {
      var target = document.getElementById(featureId);
      var wrapper = document.getElementById('tabContentWrapper');
      if (!target || !wrapper) return;
      wrapper.scrollTo({ top: target.offsetTop - wrapper.offsetTop - 20, behavior: 'smooth' });
      document.querySelectorAll('.feature-section').forEach(function (s) { s.classList.remove('highlight'); });
      target.classList.add('highlight');
      window.setTimeout(function () { target.classList.remove('highlight'); }, 2500);
      var indicator = document.getElementById('linkIndicator');
      if (indicator) {
        indicator.textContent = '→ ' + (featureNames[featureId] || featureId);
        indicator.classList.add('show');
        window.setTimeout(function () { indicator.classList.remove('show'); }, 2000);
      }
    }, 100);
  }
  window.linkToFeature = linkToFeature;

  var protoRoot = document.getElementById('prototypeRoot');
  if (protoRoot) {
    protoRoot.addEventListener('click', function (event) {
      if (event.target.closest('.demo-crisis')) return; /* 危机演示气泡只触发卡片，不跳文档 */
      var el = event.target.closest('[data-link]');
      if (el) linkToFeature(el.dataset.link);
    });
  }

  /* ---------- 左右分栏拖拽 + 等比缩放 ---------- */
  (function () {
    var handle = document.getElementById('resizeHandle');
    var left = document.querySelector('.left-panel');
    var container = document.querySelector('.main-layout');
    if (!handle || !left || !container) return;
    var isDragging = false;

    function scalePrototype() {
      var frame = left.querySelector('.phone-frame');
      if (!frame) return;
      var padding = 20;
      var panelW = left.clientWidth - padding * 2;
      var panelH = left.clientHeight - padding * 2 - 20;
      var origW = 375, origH = 720;
      var scale = Math.min(panelW / origW, panelH / origH, 1.15);
      scale = Math.max(scale, 0.3);
      frame.style.transform = 'scale(' + scale + ')';
      frame.style.left = (padding + (panelW - origW * scale) / 2) + 'px';
      frame.style.top = (padding + 18 + (panelH - origH * scale) / 2) + 'px';
    }

    handle.addEventListener('mousedown', function () {
      isDragging = true;
      handle.classList.add('active');
      document.body.style.userSelect = 'none';
    });
    document.addEventListener('mousemove', function (event) {
      if (!isDragging) return;
      var rect = container.getBoundingClientRect();
      var pct = ((event.clientX - rect.left) / rect.width) * 100;
      left.style.flex = '0 0 ' + Math.max(25, Math.min(70, pct)) + '%';
      scalePrototype();
    });
    document.addEventListener('mouseup', function () {
      isDragging = false;
      handle.classList.remove('active');
      document.body.style.userSelect = '';
    });
    window.addEventListener('resize', scalePrototype);
    window.addEventListener('load', scalePrototype);
    window.setTimeout(scalePrototype, 100);
  })();

  /* ---------- 文本模式 ---------- */
  window.switchMode = function (mode) {
    var modeBtns = document.querySelectorAll('.mode-toggle .mode-btn');
    var textDoc = document.getElementById('textModeDoc');

    function activate(idx) {
      modeBtns.forEach(function (b) { b.classList.remove('active'); });
      if (modeBtns[idx]) modeBtns[idx].classList.add('active');
    }

    if (mode === 'text') {
      var html = '<h1>心屿 · 校园心理咨询智能陪伴 Agent — 开发文档</h1>' +
        '<p class="doc-meta">V1.0 · 2026-10-12 · 微信小程序 · 读者：研发团队（后端 / 小程序前端 / 算法与提示词）</p>';
      var panes = document.querySelectorAll('.tab-content-wrapper > .tab-pane');
      panes.forEach(function (pane, i) {
        if (i > 0) html += '<hr class="section-divider">';
        html += pane.innerHTML;
      });
      textDoc.innerHTML = html;
      injectFeaturePrototypes(textDoc);
      document.body.classList.add('text-mode');
      activate(1);
      rerenderMermaid(textDoc);
      window.scrollTo(0, 0);
    } else {
      document.body.classList.remove('text-mode');
      window.scrollTo(0, 0);
      activate(0);
      rerenderMermaid(document.querySelector('.main-layout'));
    }
  };

  /* 文本模式下把原型插入对应功能小节 */
  function injectFeaturePrototypes(container) {
    var proto = document.querySelector('.phone-frame');
    if (!proto) return;
    var pages = proto.querySelectorAll('.page');
    var used = {};

    container.querySelectorAll('.feature-section').forEach(function (section) {
      var featureId = section.id;
      if (!featureId || used[featureId]) return;
      var matchedPage = null;
      pages.forEach(function (page) {
        if (matchedPage) return;
        if (page.getAttribute('data-link') === featureId) { matchedPage = page; return; }
        page.querySelectorAll('[data-link]').forEach(function (el) {
          if (el.dataset.link === featureId) matchedPage = page;
        });
      });
      if (!matchedPage) return;
      used[featureId] = true;

      var clone = matchedPage.cloneNode(true);
      clone.style.position = 'absolute';
      clone.style.top = '0'; clone.style.left = '0'; clone.style.right = '0'; clone.style.bottom = '0';
      clone.style.opacity = '1'; clone.style.transform = 'none'; clone.style.display = 'flex';
      clone.style.flexDirection = 'column';

      var frame = document.createElement('div');
      frame.style.cssText = 'width:375px;height:640px;border-radius:32px;overflow:hidden;position:relative;background:#fff;box-shadow:0 2px 12px rgba(0,0,0,0.08);margin:0 auto;';
      frame.appendChild(clone);

      var wrapper = document.createElement('div');
      wrapper.style.cssText = 'border:1px solid #e4ece9;border-radius:12px;padding:20px;margin:0 0 16px;background:#fafcfb;';
      wrapper.innerHTML = '<div style="font-size:13px;color:#667085;margin-bottom:12px;font-weight:500;">交互原型（可点击）</div>';
      wrapper.appendChild(frame);
      section.insertBefore(wrapper, section.children[1] || null);
    });
  }

  /* Mermaid 在模式切换后重绘：已渲染为 SVG 的元素（含克隆副本）直接静态保留 */
  function rerenderMermaid(scope) {
    if (!window.mermaid || !scope) return;
    var pending = [];
    scope.querySelectorAll('pre.mermaid').forEach(function (el) {
      if (el.querySelector('svg')) return;
      if (el.hasAttribute('data-processed')) el.removeAttribute('data-processed');
      pending.push(el);
    });
    if (!pending.length) return;
    try { mermaid.run({ nodes: pending }); }
    catch (e) { /* 初次渲染由 startOnLoad 兜底，此处失败不影响阅读 */ }
  }
})();
