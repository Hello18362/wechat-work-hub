/* ==========================================================================
 * mock-api.js —— 沙盘演示版的「假后端」
 *
 * 作用：拦截页面发出的所有 /api/* 请求，返回预先编好的示例数据。
 * 因此这个演示站是**纯静态**的：不需要 Python、不需要服务、不需要微信，
 * 直接扔到任何静态托管（Vercel / Netlify / GitHub Pages）就能点。
 *
 * 里面所有群名、人名、聊天内容都是编的，不含任何真实数据。
 *
 * 覆盖的接口（与真实后端一一对应）：
 *   GET    /api/status
 *   GET    /api/groups
 *   GET    /api/groups/config
 *   POST   /api/groups/config
 *   POST   /api/groups/pin
 *   GET    /api/contacts?category=friend|official
 *   GET    /api/runs
 *   DELETE /api/runs
 *   POST   /api/run
 *   GET    /api/task?id=xxx
 *   GET    /api/report?md=xxx
 *   DELETE /api/report?md=xxx
 * ========================================================================== */

(function () {
  'use strict';

  // 单文件版（build_singlefile.py 打包）会把示例报告一起塞进来，
  // 此时没有 reports/ 目录可读，改走这里的字符串。多文件版为 undefined。
  var EMBEDDED = window.__DEMO_REPORTS__ || null;

  var realFetch = window.fetch
    ? window.fetch.bind(window)
    : function () { return Promise.reject(new Error('当前环境不支持 fetch')); };

  /* 从 "reports/demo-report-1.html" 之类取文件名 */
  function reportName(url) {
    var s = String(url || '').split('?')[0].split('#')[0];
    return s.slice(s.lastIndexOf('/') + 1);
  }

  function embeddedReport(url) {
    if (!EMBEDDED) return '';
    return EMBEDDED[reportName(url)] || '';
  }

  /* ------------------------------------------------------------ 示例数据 */

  // 群列表：pinned 标记置顶，configured 表示已配「关注的人」
  var GROUPS = [
    { name: '示例 · 项目协作群',   configured: true,  leader_count: 2, pinned: true  },
    { name: '示例 · 班级通知群',   configured: true,  leader_count: 2, pinned: true  },
    { name: '示例 · 学生干部群',   configured: true,  leader_count: 1, pinned: false },
    { name: '示例 · 部门周会群',   configured: true,  leader_count: 1, pinned: false },
    { name: '示例 · 实验室讨论群', configured: false, leader_count: 0, pinned: false },
    { name: '示例 · 兼职信息群',   configured: false, leader_count: 0, pinned: false },
    { name: '示例 · 宿舍群',       configured: false, leader_count: 0, pinned: false },
    { name: '示例 · 兴趣交流群',   configured: false, leader_count: 0, pinned: false }
  ];

  // 「关注的人」配置：对应真实后端的 groups.yaml
  var GROUP_CONFIG = {
    target_groups: [
      { name: '示例 · 项目协作群', enabled: true,
        leaders: [{ name: '张经理', id: '' }, { name: '李主管', id: '' }] },
      { name: '示例 · 班级通知群', enabled: true,
        leaders: [{ name: '辅导员', id: '' }, { name: '班长', id: '' }] },
      { name: '示例 · 学生干部群', enabled: true,
        leaders: [{ name: '王老师', id: '' }] },
      { name: '示例 · 部门周会群', enabled: true,
        leaders: [{ name: '陈总监', id: '' }] }
    ],
    global_leaders: []
  };

  // 报告列表：html 指向 reports/ 目录里预先生成的示例报告
  var nowSec = Math.floor(Date.now() / 1000);
  var RUNS = [
    { md: 'demo-report-1.md', html: 'demo-report-1.html', group: '示例 · 项目协作群',
      date: '2026-11-13', total: 86, leader: 12, size: 62400, mtime: nowSec - 3600 },
    { md: 'demo-report-2.md', html: 'demo-report-2.html', group: '示例 · 班级通知群',
      date: '2026-11-12', total: 41, leader: 7,  size: 38900, mtime: nowSec - 86400 },
    { md: 'demo-report-3.md', html: 'demo-report-3.html', group: '示例 · 学生干部群',
      date: '2026-11-11', total: 133, leader: 21, size: 88700, mtime: nowSec - 172800 }
  ];

  // 报告 Markdown 正文（用于「复制 Markdown」和详情弹窗）
  var REPORT_MD = {
    'demo-report-1.md':
      '## 今日要点\n\n' +
      '- 版本 v0.9 已提测，张经理要求周四前完成回归。\n' +
      '- 数据接口联调延后到明天上午，李主管负责对接。\n\n' +
      '## 任务安排\n\n' +
      '- ☐ 完成回归测试 · 负责人：张经理 · 截止：周四\n' +
      '- ☐ 输出接口联调记录 · 负责人：李主管 · 截止：明天\n' +
      '- ☑ 评审会议纪要已归档\n',
    'demo-report-2.md':
      '## 通知汇总\n\n' +
      '- 本周五下午 3 点在教学楼 302 开班会，请全体同学参加。\n' +
      '- 奖学金材料提交截止到下周三，交到辅导员办公室。\n\n' +
      '## 任务安排\n\n' +
      '- ☐ 收齐奖学金申请表 · 负责人：班长 · 截止：下周三\n',
    'demo-report-3.md':
      '## 讨论结论\n\n' +
      '- 迎新晚会节目单初稿已确定，共 12 个节目。\n' +
      '- 物资采购由王老师统一走流程，本周内下单。\n\n' +
      '## 任务安排\n\n' +
      '- ☐ 提交节目单终稿 · 负责人：王老师 · 截止：周五\n' +
      '- ☐ 完成物资清单核对 · 负责人：生活委员 · 截止：周四\n'
  };

  /* 好友：包含有备注、只有昵称、无有效昵称（noisy）几种情况，用来展示筛选逻辑 */
  function mkContact(display, nick, remark, alias, noisy) {
    return {
      name: display,
      display: display,
      id: 'wxid_' + Math.random().toString(36).slice(2, 12),
      nick: nick || display,
      remark: remark || '',
      alias: alias || '',
      noisy: !!noisy
    };
  }

  var FRIENDS = [
    mkContact('张经理', '张伟', '张经理', 'zhangwei'),
    mkContact('李主管', '李娜', '李主管', 'lina'),
    mkContact('王老师', '王芳', '王老师', ''),
    mkContact('陈总监', '陈明', '陈总监', 'chenming'),
    mkContact('刘工', '刘洋', '刘工', ''),
    mkContact('小周', '周杰', '', 'zhoujie'),
    mkContact('阿May', 'May', '', ''),
    mkContact('老赵', '赵强', '老赵', ''),
    mkContact('孙同学', '孙悦', '', ''),
    mkContact('吴老师', '吴敏', '吴老师', ''),
    mkContact('郑同学', '郑浩', '', ''),
    mkContact('冯工', '冯磊', '冯工', ''),
    mkContact('陈同学', '陈曦', '', ''),
    mkContact('褚老师', '褚红', '褚老师', ''),
    mkContact('卫同学', '卫东', '', ''),
    mkContact('蒋工', '蒋楠', '蒋工', ''),
    mkContact('沈同学', '沈璐', '', ''),
    mkContact('韩老师', '韩冰', '韩老师', ''),
    mkContact('杨同学', '杨帆', '', ''),
    mkContact('朱工', '朱琳', '朱工', ''),
    // 无有效昵称：真实数据里这类会被标记 noisy、默认隐藏
    mkContact('wxid_a1b2c3', '.', '', '', true),
    mkContact('wxid_d4e5f6', '_', '', '', true),
    mkContact('wxid_g7h8i9', '12345678', '', '', true)
  ];

  var OFFICIALS = [
    mkContact('某大学教务处', '某大学教务处', '', ''),
    mkContact('团委公众号', '团委公众号', '', ''),
    mkContact('学院学生会', '学院学生会', '', ''),
    mkContact('图书馆服务号', '图书馆服务号', '', ''),
    mkContact('就业指导中心', '就业指导中心', '', ''),
    mkContact('校园卡服务', '校园卡服务', '', '')
  ];

  /* -------------------------------------------------------------- 工具 */

  function json(obj, status) {
    return new Response(JSON.stringify(obj), {
      status: status || 200,
      headers: { 'Content-Type': 'application/json; charset=utf-8' }
    });
  }

  function delay(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  // 置顶状态在内存里维护，点图钉能看到即时变化
  var PINS = {};
  GROUPS.forEach(function (g) { if (g.pinned) PINS[g.name] = true; });

  function sortGroups() {
    return GROUPS.map(function (g) {
      return {
        name: g.name,
        configured: g.configured,
        leader_count: g.leader_count,
        pinned: !!PINS[g.name],
        source: 'demo'
      };
    }).sort(function (a, b) {
      if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
      return a.name.localeCompare(b.name, 'zh');
    });
  }

  /* 任务模拟：点「生成报告」后进度条走 4 秒，然后出一份新报告 */
  var taskSeq = 0;
  var TASK = null;

  function startTask(payload) {
    taskSeq += 1;
    TASK = {
      id: 'demo-' + taskSeq,
      startedAt: Date.now(),
      group: (payload && payload.group) || '示例 · 项目协作群',
      date: (payload && payload.date) || 'today',
      emitted: false
    };
    return TASK.id;
  }

  function taskSnapshot() {
    if (!TASK) return { ok: true, task: null };
    var elapsed = (Date.now() - TASK.startedAt) / 1000;
    var percent = Math.min(100, Math.round((elapsed / 4) * 100));
    var stage, detail;

    if (percent < 20)      { stage = '读取消息'; detail = TASK.group; }
    else if (percent < 45) { stage = '加工媒体'; detail = '语音 / 图片 / 链接'; }
    else if (percent < 80) { stage = 'AI 总结';  detail = '正在提炼要点'; }
    else if (percent < 100){ stage = '渲染报告'; detail = 'Markdown + HTML'; }
    else                   { stage = '完成';     detail = ''; }

    var task = {
      id: TASK.id,
      status: percent >= 100 ? 'done' : 'running',
      percent: percent,
      stage: stage,
      detail: detail
    };

    if (percent >= 45) {
      task.result = {
        group: TASK.group,
        date: TASK.date === 'today' ? '今天' : TASK.date,
        elapsed: 4,
        total: 0,
        stats: {
          total: 0,
          leader_count: 0,
          counts: { voice: 0, image: 0, article: 0 }
        }
      };
    }

    if (percent >= 100 && !TASK.emitted) {
      // 完成后追加一份新报告到列表顶部，让「生成」看起来真的产出了东西
      TASK.emitted = true;
      var stamp = new Date();
      var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
      var dstr = stamp.getFullYear() + '-' + pad(stamp.getMonth() + 1) + '-' + pad(stamp.getDate());
      RUNS.unshift({
        md: 'demo-report-1.md',
        html: 'demo-report-1.html',
        group: TASK.group,
        date: dstr,
        total: 86,
        leader: 12,
        size: 62400,
        mtime: Math.floor(stamp.getTime() / 1000)
      });
      task.result.total = 86;
      task.result.stats.total = 86;
      task.result.stats.leader_count = 12;
      task.result.stats.counts = { voice: 5, image: 14, article: 3 };
    }

    return { ok: true, task: task };
  }

  /* ------------------------------------------------------------ 路由 */

  window.fetch = function (input, init) {
    var url = typeof input === 'string' ? input : (input && input.url) || '';
    var method = ((init && init.method) || (input && input.method) || 'GET').toUpperCase();

    var parsed;
    try {
      // file:// 下 origin 是 "file://"（不是 "null"），
      // new URL('/api/x', 'file://') 会得到 pathname=/api/x，能被下面正确拦截。
      parsed = new URL(url, window.location.origin);
    } catch (e) {
      return realFetch(input, init);
    }

    var path = parsed.pathname;
    if (path.indexOf('/api/') !== 0) {
      return realFetch(input, init);
    }

    var body = {};
    if (init && init.body) {
      try { body = JSON.parse(init.body); } catch (e) { body = {}; }
    }

    /* ---- 状态 ---- */
    if (path === '/api/status') {
      return delay(60).then(function () {
        return json({
          ok: true,
          chatlog_online: true,
          api_base: '演示模式 · 示例数据',
          today: new Date().toISOString().slice(0, 10),
          templates: ['daily_digest', 'leader_brief', 'todo_list'],
          version: '0.1.0-demo',
          // features 必须包含 contacts，否则前端会提示「服务端是旧版本」
          features: ['contacts', 'pin', 'auto_refresh_async', 'contacts_query'],
          build: 'demo'
        });
      });
    }

    /* ---- 群列表 ---- */
    if (path === '/api/groups') {
      return delay(80).then(function () {
        return json({ ok: true, groups: sortGroups() });
      });
    }

    /* ---- 置顶 ---- */
    if (path === '/api/groups/pin' && method === 'POST') {
      var gname = body.group || '';
      if (body.pinned) {
        PINS[gname] = true;
      } else {
        delete PINS[gname];
      }
      return delay(80).then(function () {
        return json({ ok: true, group: gname, pinned: !!body.pinned });
      });
    }

    /* ---- 关注的人配置 ---- */
    if (path === '/api/groups/config') {
      if (method === 'POST') {
        var target = body.group || '';
        var leaders = body.leaders || [];
        var hit = null;
        GROUP_CONFIG.target_groups.forEach(function (g) {
          if (g.name === target) hit = g;
        });
        if (!hit) {
          hit = { name: target, enabled: true, leaders: [] };
          GROUP_CONFIG.target_groups.push(hit);
        }
        hit.leaders = leaders;
        GROUPS.forEach(function (g) {
          if (g.name === target) {
            g.configured = true;
            g.leader_count = leaders.length;
          }
        });
        return delay(120).then(function () {
          return json({ ok: true, group: target, leader_count: leaders.length });
        });
      }
      return delay(60).then(function () {
        return json({
          ok: true,
          target_groups: GROUP_CONFIG.target_groups,
          global_leaders: GROUP_CONFIG.global_leaders
        });
      });
    }

    /* ---- 联系人 / 公众号 ---- */
    if (path === '/api/contacts') {
      var cat = parsed.searchParams.get('category') || 'friend';
      var q = (parsed.searchParams.get('q') || '').trim().toLowerCase();
      var limit = parseInt(parsed.searchParams.get('limit') || '200', 10) || 200;
      var src = cat === 'official' ? OFFICIALS : FRIENDS;
      var matched = src.filter(function (c) {
        return !q || (c.display + ' ' + c.nick + ' ' + c.remark).toLowerCase().indexOf(q) >= 0;
      });
      var page = matched.slice(0, limit);
      return delay(90).then(function () {
        return json({
          ok: true,
          category: cat,
          q: q,
          limit: limit,
          total: src.length,
          matched: matched.length,
          truncated: matched.length > page.length,
          contacts: page
        });
      });
    }

    /* ---- 报告列表 ---- */
    if (path === '/api/runs') {
      if (method === 'DELETE') {
        RUNS = [];
        return delay(120).then(function () { return json({ ok: true, removed: 0 }); });
      }
      return delay(80).then(function () { return json({ ok: true, runs: RUNS }); });
    }

    /* ---- 生成报告 ---- */
    if (path === '/api/run' && method === 'POST') {
      var id = startTask(body);
      return delay(120).then(function () { return json({ ok: true, task_id: id }); });
    }

    /* ---- 任务进度 ---- */
    if (path === '/api/task') {
      return delay(40).then(function () { return json(taskSnapshot()); });
    }

    /* ---- 报告正文 / 删除 ---- */
    if (path === '/api/report') {
      var md = parsed.searchParams.get('md') || '';
      if (method === 'DELETE') {
        RUNS = RUNS.filter(function (r) { return r.md !== md || r.date !== md; });
        RUNS = RUNS.filter(function (r, i) { return i > 0 || true; });
        return delay(100).then(function () { return json({ ok: true }); });
      }
      return delay(80).then(function () {
        return json({ ok: true, markdown: REPORT_MD[md] || '（示例报告的 Markdown 正文）' });
      });
    }

    // 未覆盖的接口，明确返回 404，避免静默失败
    return Promise.resolve(json({ ok: false, error: '演示版未实现该接口：' + path }, 404));
  };

  /* -------------------------------------------------- 报告预览（页内展开）

   * 真实后端里，点「查看报告」是 window.open('/reports/xxx.html') 开新标签。
   * 但演示站常被嵌在预览面板 / iframe 里，window.open 会被浏览器拦截，
   * 表现就是「点了没反应」。所以这里改成在当前页面内盖一层 iframe：
   * 任何环境下都能打开，还留了一个「在新标签打开」的链接给需要的人。
   */

  function openReportOverlay(url) {
    var id = 'demoReportOverlay';
    var old = document.getElementById(id);
    if (old && old.parentNode) {
      old.parentNode.removeChild(old);
    }

    var wrap = document.createElement('div');
    wrap.id = id;

    var bar = document.createElement('div');
    bar.className = 'demo-ov-bar';

    var title = document.createElement('span');
    title.className = 'demo-ov-title';
    title.textContent = '示例报告 · 演示预览';

    var embedded = embeddedReport(url);

    var link = document.createElement('a');
    link.className = 'demo-ov-link';
    link.target = '_blank';
    link.rel = 'noopener';
    if (embedded) {
      // 单文件版：报告本身就是字符串，用 Blob 造一个可打开的地址
      try {
        link.href = URL.createObjectURL(new Blob([embedded], { type: 'text/html' }));
      } catch (e) {
        link.style.display = 'none';
      }
    } else {
      link.href = url;
    }
    link.textContent = '在新标签打开';

    var close = document.createElement('button');
    close.className = 'demo-ov-close';
    close.type = 'button';
    close.textContent = '关闭';
    close.addEventListener('click', function () {
      if (wrap.parentNode) wrap.parentNode.removeChild(wrap);
    });

    bar.appendChild(title);
    bar.appendChild(link);
    bar.appendChild(close);

    var frame = document.createElement('iframe');
    frame.className = 'demo-ov-frame';
    if (embedded) {
      frame.setAttribute('srcdoc', embedded);
    } else {
      frame.src = url;
    }

    wrap.appendChild(bar);
    wrap.appendChild(frame);
    document.body.appendChild(wrap);

    document.addEventListener('keydown', function esc(e) {
      if (e.key === 'Escape') {
        if (wrap.parentNode) wrap.parentNode.removeChild(wrap);
        document.removeEventListener('keydown', esc);
      }
    });
  }

  // 覆盖 window.open：报告走页内预览，其他情况保持原样
  var nativeOpen = window.open ? window.open.bind(window) : null;
  window.open = function (url) {
    if (typeof url === 'string' && url.indexOf('/reports/') >= 0) {
      openReportOverlay(url);
      return null;
    }
    return nativeOpen ? nativeOpen.apply(window, arguments) : null;
  };

  /* -------------------------------------------------- 演示模式提示条 */

  window.addEventListener('DOMContentLoaded', function () {
    // 单文件版由打包脚本预先写好提示条（在文档流最前面），这里就不再重复插入
    if (document.getElementById('demoBanner')) return;
    var bar = document.createElement('div');
    bar.id = 'demoBanner';
    bar.innerHTML =
      '<span class="demo-dot"></span>' +
      '<strong>演示模式</strong>' +
      '<span class="demo-text">页面为沙盘演示，所有群聊、联系人和报告内容均为示例数据，不含任何真实信息。可自由点击体验。</span>';
    document.body.appendChild(bar);
    document.body.style.paddingTop = '38px';
  });
})();
