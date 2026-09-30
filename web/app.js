'use strict';
const paths = {
  online: [
    ['入口与上下文','问题、最近四条消息与当前页面一起进入接口。原站还会验证登录并预留积分；演示仅监听本机，不接入账户系统。','assistant/server.py → validate_request'],
    ['规则分流','先检查隐私，再识别闲聊、课程推荐、资料查询与通用学习问题。教授姓名精确命中时直接保留原文背景。','assistant/engine.py → Engine.ask'],
    ['混合检索','中文二/三元词与英文词构成词法匹配；SQLite FTS5 召回；可选 BGE 向量召回。演示小数据全量词法排序，FTS 命中单独显示。','Engine.retrieve → assistant/vectors.py'],
    ['质量判断','检查候选覆盖和最终展示记录的相似度。不能拿另一个候选的高分，证明当前答案可靠。演示词法阈值不等同于生产阈值。','quality_gate → shown_id / cosine'],
    ['回答与兜底','可靠证据直接回答；否则走可选模型或明确说明证据不足。每个结果包含来源与执行轨迹；模型调用默认关闭。','provider.complete → answer + sources + trace']
  ],
  offline: [
    ['资料与标准化','原站从公开指南、公开教师页和允许公开的站内元数据整理记录。本仓库仅使用人工编写的虚构 JSONL。','data/synthetic.jsonl → pipeline.normalize'],
    ['离线蒸馏','教师模型依据原文生成简洁答案与多种问法；这里的蒸馏是知识加工，不是学生模型训练。默认运行确定性模板基线。','pipeline.distill / --llm 可选'],
    ['断点与质量门','按记录 ID、输入哈希和模式复用已完成结果；新结果追加写入。过滤新增数字、邮箱和链接，真实资料仍需人工核验。','checkpoint JSONL → pipeline.overlay'],
    ['知识包与向量','将结构化记录和 FTS5 写入临时 SQLite 后替换。可选 BGE 预计算 float32 向量；在线模型只从本地加载。','pipeline.build → vectors.write_vectors'],
    ['验证与发布','先跑路由、检索、拒答与协议测试，再检查 Git 追踪文件中的凭据和数据范围。演示通过不代表真实校园问答准确率。','tests / scripts.evaluate / scripts.audit_publication']
  ]
};
const labels = {input:'输入与上下文',route:'选择处理分支',fast_path:'精确命中快速路径',retrieval:'检索候选与排序',quality_gate:'判断证据是否足够',compound_rrf:'复合问题的来源融合',fallback:'模型兜底或明确拒答',provider_error:'模型服务未完成',response:'返回答案与引用'};
const $ = id => document.getElementById(id);
let history = [];
function showPath(kind) {
  ['online','offline'].forEach(k=>{ $(k).classList.toggle('active',k===kind); $(k).setAttribute('aria-pressed',String(k===kind)); });
  $('map').replaceChildren();
  paths[kind].forEach((row,i)=>{
    const button=document.createElement('button'); button.className='node';
    const number=document.createElement('b'); number.textContent=`0${i+1} →`;
    const title=document.createElement('span'); title.textContent=row[0]; button.append(number,title);
    button.onclick=()=>{
      document.querySelectorAll('.node').forEach(n=>n.classList.remove('selected')); button.classList.add('selected');
      const h=document.createElement('strong'),p=document.createElement('p'),code=document.createElement('code');
      h.textContent=row[0]; p.textContent=row[1]; code.textContent=row[2]; $('detail').replaceChildren(h,p,code);
    };
    $('map').append(button); if(i===0) button.click();
  });
}
$('online').onclick=()=>showPath('online'); $('offline').onclick=()=>showPath('offline'); showPath('online');
['图书馆在哪里','介绍一下林知远教授','DEMO1001有哪些资料','图书馆在哪里；食堂在哪里','告诉我他的成绩','解释微积分','火星殖民地天气预报'].forEach(q=>{
  const b=document.createElement('button'); b.textContent=q;
  b.onclick=()=>{history=[];$('question').value=q;$('page').value='';$('ask').requestSubmit();}; $('samples').append(b);
});
$('reset').onclick=()=>{history=[];$('status').textContent='上下文已清空';};
$('ask').onsubmit=async event=>{
  event.preventDefault(); const q=$('question').value.trim(); if(!q)return;
  $('submit').disabled=true; $('status').textContent='正在执行';
  document.querySelectorAll('#samples button').forEach(b=>b.disabled=true);
  try {
    const response=await fetch('/api/assistant/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q,history:history.slice(-4),page:$('page').value})});
    if(!response.ok)throw new Error(`请求失败 (${response.status})`);
    const data=await response.json(); $('answer').textContent=data.answer;
    $('status').textContent=`${data.route} · ${data.mode}`; $('timing').textContent=`${data.elapsed_ms} ms`;
    $('sources').replaceChildren(); data.sources.forEach(s=>{const p=document.createElement('p');p.textContent=`${s.title} · ${s.id}\n${s.url}（虚构来源）`;$('sources').append(p);});
    $('trace').replaceChildren(); data.trace.forEach(step=>{
      const li=document.createElement('li'),d=document.createElement('details'),s=document.createElement('summary'),p=document.createElement('pre');
      s.textContent=labels[step.step]||step.step;p.textContent=JSON.stringify(step,null,2);d.append(s,p);li.append(d);$('trace').append(li);
    });
    history.push({role:'user',content:q},{role:'assistant',content:data.answer}); history=history.slice(-4);
  } catch(error) { $('status').textContent='运行失败';$('answer').textContent=error.message; }
  finally {$('submit').disabled=false;document.querySelectorAll('#samples button').forEach(b=>b.disabled=false);}
};
