// 在 Node 里模拟浏览器环境，把 mock-api.js 的逻辑真跑一遍
const fs = require('fs');
const path = require('path');

const file = path.join(__dirname, '..', 'demo-site', 'mock-api.js');
const code = fs.readFileSync(file, 'utf8');

// --- 最小 DOM / window 桩 ---
const listeners = {};

function mkEl(tag) {
  return {
    tagName: tag,
    style: {},
    children: [],
    id: '',
    parentNode: null,
    _text: '',
    set textContent(v) { this._text = v; },
    get textContent() { return this._text; },
    set innerHTML(v) { this._html = v; },
    get innerHTML() { return this._html || ''; },
    appendChild(c) { this.children.push(c); c.parentNode = this; return c; },
    removeChild(c) {
      const i = this.children.indexOf(c);
      if (i >= 0) this.children.splice(i, 1);
      return c;
    },
    addEventListener() {},
    removeEventListener() {},
  };
}

global.window = {
  location: { origin: 'https://demo.example.com' },
  fetch: (input, init) => {
    // 演示站不该走真实网络；走到这里说明路由漏了
    return Promise.resolve(new Response(JSON.stringify({ __real__: String(input) }), { status: 599 }));
  },
  addEventListener: (ev, fn) => { listeners[ev] = fn; },
};
global.document = {
  body: mkEl('body'),
  createElement: (t) => mkEl(t),
  getElementById: () => null,
  addEventListener: () => {},
  removeEventListener: () => {},
};
global.window.document = global.document;

// 执行 mock-api.js（它会覆盖 window.fetch）
eval(code);

const fetchMock = window.fetch;

async function call(p, init) {
  const r = await fetchMock(p, init);
  const body = await r.json().catch(() => ({}));
  return { status: r.status, body };
}

function assert(cond, label, extra) {
  if (cond) {
    console.log('  PASS  ' + label);
  } else {
    console.log('  FAIL  ' + label + (extra ? '  -> ' + JSON.stringify(extra).slice(0, 200) : ''));
    process.exitCode = 1;
  }
}

(async () => {
  console.log('=== 1) /api/status ===');
  {
    const { status, body } = await call('/api/status');
    assert(status === 200 && body.ok === true, 'ok=true');
    assert(Array.isArray(body.features) && body.features.includes('contacts'),
      'features 含 contacts（否则前端会报"服务端是旧版本"）', body.features);
    assert(Array.isArray(body.templates) && body.templates.length === 3, 'templates 3 个', body.templates);
  }

  console.log('\n=== 2) /api/groups ===');
  let firstGroup;
  {
    const { status, body } = await call('/api/groups');
    assert(status === 200 && body.groups.length === 8, '8 个群', body.groups && body.groups.length);
    assert(body.groups.every(g => 'pinned' in g && 'configured' in g),
      '每条都有 pinned/configured');
    assert(body.groups[0].pinned === true, '置顶群排第一', body.groups[0]);
    firstGroup = body.groups[0].name;
  }

  console.log('\n=== 3) 置顶切换 ===');
  {
    const target = '示例 · 宿舍群';
    const before = (await call('/api/groups')).body.groups.find(g => g.name === target);
    assert(before.pinned === false, '置顶前为 false');
    const pin = await call('/api/groups/pin', {
      method: 'POST',
      body: JSON.stringify({ group: target, pinned: true }),
      headers: { 'Content-Type': 'application/json' },
    });
    assert(pin.status === 200 && pin.body.ok === true && pin.body.pinned === true, 'POST 返回 ok', pin.body);
    const after = (await call('/api/groups')).body.groups;
    // 真实后端排序是 (not pinned, name)：置顶区在前，区内按名称排。
    // 所以要断言「置顶条目全部排在非置顶之前」，而不是「目标必须第一个」。
    const firstUnpinned = after.findIndex(g => !g.pinned);
    const pinnedCount = after.filter(g => g.pinned).length;
    assert(after.every((g, i) => (i < pinnedCount) === g.pinned),
      '置顶条目全部排在非置顶之前', after.map(g => (g.pinned ? '📌' : '') + g.name));
    const hit = after.find(g => g.name === target);
    assert(hit && hit.pinned === true, '目标群已置顶', hit);
    assert(after.indexOf(hit) < firstUnpinned, '目标群落在置顶区内', { idx: after.indexOf(hit), firstUnpinned });
    // 还原
    await call('/api/groups/pin', {
      method: 'POST', body: JSON.stringify({ group: target, pinned: false }),
      headers: { 'Content-Type': 'application/json' },
    });
    const back = (await call('/api/groups')).body.groups;
    assert(back[0].name === firstGroup, '取消置顶后顺序恢复', back[0].name);
  }

  console.log('\n=== 4) 关注的人配置 ===');
  {
    const g = await call('/api/groups/config');
    assert(g.status === 200 && Array.isArray(g.body.target_groups), 'GET 返回 target_groups',
      g.body && Object.keys(g.body));
    const p = await call('/api/groups/config', {
      method: 'POST',
      body: JSON.stringify({ group: '示例 · 实验室讨论群', leaders: [{ name: '赵老师', id: '' }, { name: '钱同学', id: '' }] }),
      headers: { 'Content-Type': 'application/json' },
    });
    assert(p.status === 200 && p.body.leader_count === 2, 'POST 保存 2 人', p.body);
    const g2 = await call('/api/groups/config');
    const hit = g2.body.target_groups.find(x => x.name === '示例 · 实验室讨论群');
    assert(hit && hit.leaders.length === 2, '回读包含新增的群与 2 位成员', hit);
    const gs = await call('/api/groups');
    const gl = gs.body.groups.find(x => x.name === '示例 · 实验室讨论群');
    assert(gl.configured === true && gl.leader_count === 2, '群列表同步显示已配置 2 人', gl);
  }

  console.log('\n=== 5) 联系人 ===');
  {
    const f = await call('/api/contacts?category=friend');
    assert(f.status === 200 && f.body.contacts.length > 0, '好友有数据', f.body && f.body.contacts.length);
    assert(typeof f.body.total === 'number' && typeof f.body.truncated === 'boolean', '有 total/truncated');
    assert(f.body.contacts.every(c => 'display' in c && 'noisy' in c), '每条有 display/noisy');
    const noisy = f.body.contacts.filter(c => c.noisy).length;
    assert(noisy > 0, '包含若干 noisy 条目（用于演示隐藏逻辑）', noisy);
    const q = await call('/api/contacts?category=friend&q=' + encodeURIComponent('张'));
    assert(q.body.matched < f.body.matched || q.body.matched === 1, '关键词搜索生效', q.body.matched);
    const o = await call('/api/contacts?category=official');
    assert(o.body.contacts.length > 0, '公众号有数据', o.body.contacts.length);
  }

  console.log('\n=== 6) 报告列表 / 正文 ===');
  {
    const r = await call('/api/runs');
    assert(r.status === 200 && r.body.runs.length === 3, '3 份报告', r.body.runs && r.body.runs.length);
    const one = r.body.runs[0];
    assert(one.html && one.md && one.group && typeof one.mtime === 'number',
      '报告字段齐全', Object.keys(one));
    const md = await call('/api/report?md=' + encodeURIComponent(one.md));
    assert(md.status === 200 && typeof md.body.markdown === 'string' && md.body.markdown.length > 20,
      'Markdown 正文可取', (md.body.markdown || '').slice(0, 30));
  }

  console.log('\n=== 7) 生成报告（模拟 4 秒）===');
  {
    const run = await call('/api/run', {
      method: 'POST',
      body: JSON.stringify({ group: '示例 · 项目协作群', date: 'today', template: 'leader_brief', format: 'both' }),
      headers: { 'Content-Type': 'application/json' },
    });
    assert(run.status === 200 && !!run.body.task_id, '返回 task_id', run.body);
    const id = run.body.task_id;

    const t1 = await call('/api/task?id=' + id);
    assert(t1.body.task && t1.body.task.status === 'running', '刚启动是 running', t1.body.task);
    assert(typeof t1.body.task.percent === 'number' && typeof t1.body.task.stage === 'string',
      '有 percent/stage', t1.body.task);

    await new Promise(r => setTimeout(r, 4400)); // 等模拟跑完
    const t2 = await call('/api/task?id=' + id);
    assert(t2.body.task.status === 'done', '4 秒后 done', t2.body.task);
    assert(t2.body.task.percent === 100, 'percent=100', t2.body.task.percent);

    const runs2 = await call('/api/runs');
    assert(runs2.body.runs.length === 4, '列表新增 1 份报告', runs2.body.runs.length);
    assert(runs2.body.runs[0].group === '示例 · 项目协作群', '新报告在最前且群名正确',
      runs2.body.runs[0]);
  }

  console.log('\n=== 8) 清理 ===');
  {
    const d = await call('/api/runs', { method: 'DELETE' });
    assert(d.status === 200 && d.body.ok === true, 'DELETE /api/runs 成功', d.body);
    const r = await call('/api/runs');
    assert(r.body.runs.length === 0, '清空后为 0 份', r.body.runs.length);
  }

  console.log('\n=== 9) 报告页内预览（window.open 被劫持）===');
  {
    let threw = null;
    try {
      window.open('/reports/demo-report-1.html');
    } catch (e) {
      threw = e;
    }
    assert(!threw, 'window.open 不抛异常', threw && String(threw));
    const ov = document.body.children.find(c => c.id === 'demoReportOverlay');
    assert(!!ov, '页面内生成了预览层（不再依赖弹窗）');
    assert(ov && ov.children.length === 2, '预览层含操作栏 + iframe', ov && ov.children.length);
    const frame = ov && ov.children[1];
    assert(frame && frame.tagName === 'iframe'
      && String(frame.src).indexOf('/reports/demo-report-1.html') >= 0,
      'iframe 指向对应报告', frame && frame.src);
  }

  console.log('\n' + (process.exitCode ? '存在失败项' : '全部通过'));
})();
