/* 由 build.js --brief 生成 —— 不是成稿，是骨架。
   把每个槽位重写成 { jp, zh } 成对文案后覆盖 copy/issue.js，再跑 node tools/copycheck.js。
   注释里的「预算」= 每行可容纳字数：写长了会把固定框挤爆（copycheck 版面层会拦）。
   ★ 本文件里出现的选择器才是「可写槽位」；ntext=0 的结构标签（Step / 数字序号）
     已由版式直接烘进 HTML，**不要**给它们写文案。 */
window.__ISSUE = {

  /* ═══════════ page01 ═══════════ */
  page01: {
    /* ntext=2 · 预算 26 字/行 · credits */
    "#credits > .t": { jp: ['', ''], zh: ['', ''] },
    /* ntext=1 · 预算 1 字/行 · note-v */
    "#note-v > .t": { jp: '', zh: '' },
    /* [结构标签·不用写] "#step-script > .t" —— 版式直接烘入：「Step」 */
    /* [结构标签·不用写] "#s1-no > .t" —— 版式直接烘入：「1」 */
    /* ntext=2 · 预算 19 字/行 · s1-h */
    "#s1-h > .t": { jp: ['', ''], zh: ['', ''] },
    /* ntext=1 · 预算 26 字/行 · s1-p */
    "#s1-p > .t": { jp: '', zh: '' },
    /* [结构标签·不用写] "#s2-no > .t" —— 版式直接烘入：「2」 */
    /* ntext=2 · 预算 19 字/行 · s2-h */
    "#s2-h > .t": { jp: ['', ''], zh: ['', ''] },
    /* ntext=1 · 预算 26 字/行 · s2-p */
    "#s2-p > .t": { jp: '', zh: '' },
    /* [结构标签·不用写] "#s3-no > .t" —— 版式直接烘入：「3」 */
    /* ntext=2 · 预算 19 字/行 · s3-h */
    "#s3-h > .t": { jp: ['', ''], zh: ['', ''] },
    /* ntext=1 · 预算 26 字/行 · s3-p */
    "#s3-p > .t": { jp: '', zh: '' },
    /* [结构标签·不用写] "#s4-no > .t" —— 版式直接烘入：「4」 */
    /* ntext=2 · 预算 19 字/行 · s4-h */
    "#s4-h > .t": { jp: ['', ''], zh: ['', ''] },
    /* ntext=1 · 预算 26 字/行 · s4-p */
    "#s4-p > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 3 字/行 · pageno */
    "#pageno > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 17 字/行 · wm */
    "#wm > .t": { jp: '', zh: '' },
  },

  /* ═══════════ page05 ═══════════ */
  page05: {
    /* ntext=1 · 预算 21 字/行 · mast-a */
    "#mast-a > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 28 字/行 · mast-b */
    "#mast-b > .t": { jp: '', zh: '' },
    /* ntext=2 · 预算 12 字/行 · 最新 */
    "#mast-c > .t": { jp: ['', ''], zh: ['', ''] },
    /* ntext=1 · 预算 NaN 字/行 · torn-title */
    "#torn-title > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 7 字/行 · n1 */
    "#n1 > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 7 字/行 · n2 */
    "#n2 > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 7 字/行 · n3 */
    "#n3 > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 7 字/行 · n4 */
    "#n4 > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 7 字/行 · n5 */
    "#n5 > .t": { jp: '', zh: '' },
    /* [结构标签·不用写] "#news01-kicker > .t" —— 版式直接烘入：「( NEWS 01 )」 */
    /* ntext=2 · 预算 10 字/行 · news01-h */
    "#news01-h > .t": { jp: ['', ''], zh: ['', ''] },
    /* ntext=1 · 预算 24 字/行 · news01-p */
    "#news01-p > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 14 字/行 · lab-a1 */
    "#lab-a1 > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 16 字/行 · lab-a2 */
    "#lab-a2 > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 15 字/行 · lab-a3 */
    "#lab-a3 > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 15 字/行 · lab-a4 */
    "#lab-a4 > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 30 字/行 · credits-a */
    "#credits-a > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 12 字/行 · lab-b1 */
    "#lab-b1 > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 12 字/行 · lab-b2 */
    "#lab-b2 > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 11 字/行 · lab-b3 */
    "#lab-b3 > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 12 字/行 · lab-b4 */
    "#lab-b4 > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 29 字/行 · credits-b */
    "#credits-b > .t": { jp: '', zh: '' },
    /* [结构标签·不用写] "#news02-kicker > .t" —— 版式直接烘入：「( NEWS 02 )」 */
    /* ntext=2 · 预算 14 字/行 · news02-h */
    "#news02-h > .t": { jp: ['', ''], zh: ['', ''] },
    /* ntext=1 · 预算 35 字/行 · news02-p */
    "#news02-p > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 88 字/行 · fam */
    "#fam > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 3 字/行 · pageno */
    "#pageno > .t": { jp: '', zh: '' },
    /* ntext=1 · 预算 21 字/行 · wm */
    "#wm > .t": { jp: '', zh: '' },
  },
};
