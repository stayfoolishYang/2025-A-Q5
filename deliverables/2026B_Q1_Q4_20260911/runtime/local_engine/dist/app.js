"use strict";
const $=id=>document.getElementById(id), Flow=window.JammersFlow;
const phaseNames={countdown:"准备倒计时",ready:"等待机器狗接入",running:"测试进行中",ended:"测试已结束",interrupted:"运行中断"};
const reasonNames={user_exit:"机器狗主动结束测试",manual_abort_running:"已手工中止测试",manual_abort_before_enter:"已手工中止，机器狗未接入",program_timeout:"程序现实运行超时",window_timeout_running:"测试窗口已超时",window_timeout_before_enter:"测试窗口超时，机器狗未接入",virtual_timeout:"达到虚拟世界时间上限",internal_failure:"发生本地运行错误",process_interrupted:"上次运行意外中断"};
let state=null,history=[],screen="practice",busy=false,flow=null,customScene=null,historyStamp="",eventStamp="",completed="",initialized=false,moduleStamp="";
const el=(tag,className,text)=>{const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node;};
function notify(message,error=false){$("notification").textContent=message;$("notification").className=`notice${error?" error":""}`;$("notification").hidden=false;}
async function api(path,body){const response=await fetch(path,body===undefined?{cache:"no-store"}:{method:"POST",headers:{"Content-Type":"application/json","X-Jammers-Local":"1"},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw new Error(data.error||`本地请求失败 (${response.status})`);return data;}
function hms(seconds){const s=Math.max(0,Math.floor(seconds||0));return [Math.floor(s/3600),Math.floor(s/60)%60,s%60].map(n=>String(n).padStart(2,"0")).join(":");}
function minutes(seconds){const s=Math.max(0,Math.ceil(seconds||0));return `${String(Math.floor(s/60)).padStart(2,"0")}:${String(s%60).padStart(2,"0")}`;}
function date(value){return value?new Date(value).toLocaleString("zh-CN",{hour12:false}):"—";}
function size(bytes){return bytes?`${(bytes/1024).toFixed(1)} KiB`:"—";}
function setPage(name){
  screen=name;
  document.querySelectorAll(".page").forEach(node=>{node.hidden=node.id!==`${name.startsWith("formal")?"formal":name}-page`;});
  const selected=name==="run"?(state?.session?.mode==="formal"?`formal${state.session.problem}`:"practice"):name;
  document.querySelectorAll(".nav-item").forEach(node=>node.classList.toggle("active",node.dataset.page===selected));
  $("workspace-main").classList.toggle("test-run-workspace",name==="run");
  if(name==="settings")fillSettings();
  moduleStamp="";renderModules();renderRun();
}
document.querySelectorAll(".nav-item").forEach(node=>node.addEventListener("click",()=>setPage(node.dataset.page)));
$("resume").addEventListener("click",()=>setPage("run"));
function historyTable(mode,problem){
  const wrap=el("div","data-table-wrap module-log-table"),table=el("table","data-table"),head=el("thead"),tr=el("tr");
  const columns=["测试案例编码",...(mode==="practice"?["干扰源数量"]:[]),"开始时间","结束时间","文件大小","状态","操作"];
  columns.forEach(text=>tr.append(el("th","",text)));head.append(tr);table.append(head);
  const body=el("tbody"),rows=history.filter(run=>run.mode===mode&&run.problem===problem);
  if(!rows.length){const row=el("tr","empty-row"),cell=el("td","","暂无日志文件");cell.colSpan=columns.length;row.append(cell);body.append(row);}
  for(const run of rows){
    const row=el("tr");row.append(el("td","log-code-cell",run.case_code));
    if(mode==="practice")row.append(el("td","numeric-cell",run.source_count===undefined?"—":`${run.source_count}（全向 ${run.omni_count??"—"} / 定向 ${run.directional_count??"—"}）`));
    row.append(el("td","",date(run.started_at_utc)),el("td","",date(run.ended_at_utc)),el("td","numeric-cell",size(run.log_package_bytes)),el("td","",run.phase==="ended"?"已保存（本地）":phaseNames[run.phase]||run.phase));
    const cell=el("td");if(run.phase==="ended"||run.phase==="interrupted"){
      const link=el("a","table-action-button",run.log_file_name?"导出日志":"导出已有记录");link.href=`/api/runs/${encodeURIComponent(run.run_id)}/${run.log_file_name?"package":"events"}`;link.download="";cell.append(link);
    }else cell.append(el("span","state-text","测试中"));row.append(cell);body.append(row);
  }
  table.append(body);wrap.append(table);return wrap;
}
function moduleCard(mode,problem){
  const formal=mode==="formal",card=el("section",`test-module${formal?" formal-module":""}`),row=el("div","module-action-row"),identity=el("div","module-identity");
  identity.append(el("h2","",`问题${problem}${formal?"正式":"演练"}测试`));
  const attempts=state?.attempts[String(problem)];
  identity.append(el("p","",formal?`已用 ${attempts?.used??0} 次，剩余 ${attempts?.remaining??3} 次（共3次）`:`${problem===3?"全向干扰源场景":"含定向干扰源的场景"} · 演练次数不限`));
  const enabled=Flow.canStart(state,mode,problem)&&!busy;
  const status=!state?.port_available?"接口不可用":state?.session&&state.session.phase!=="ended"?"已有测试进行中":formal&&attempts?.remaining===0?"机会已用完":state?.closing_listener?"正在关闭接口":"可以开始";
  const button=el("button","primary-button module-start-button",`开始问题${problem}${formal?"正式":"演练"}测试`);
  button.disabled=!enabled;button.dataset.mode=mode;button.dataset.problem=String(problem);
  button.addEventListener("click",()=>formal?openFlow(Flow.begin("formal",{problem,remaining:attempts.remaining})):startRun("practice",problem));
  row.append(identity,el("span","state-text",status),button);card.append(row);
  const heading=el("div","module-log-heading");heading.append(el("span","","≡"),el("h3","",`问题${problem}${formal?"正式":"演练"}测试历史行为日志`));
  const refresh=el("button","text-button","刷新");refresh.setAttribute("aria-label",`刷新问题${problem}${formal?"正式":"演练"}日志`);refresh.addEventListener("click",()=>guarded(async()=>{await loadHistory();renderModules();}));heading.append(refresh);card.append(heading,historyTable(mode,problem));return card;
}
function renderModules(){
  const stamp=JSON.stringify([screen,busy,state?.port_available,state?.port_open,state?.closing_listener,state?.session?.phase,state?.settings?.robot_port,state?.attempts,history]);
  if(stamp===moduleStamp)return;moduleStamp=stamp;
  if(screen==="practice")$("practice-modules").replaceChildren(moduleCard("practice",3),moduleCard("practice",4));
  if(screen.startsWith("formal")){const problem=screen==="formal4"?4:3;$("formal-title").textContent=`问题${problem}正式测试`;$("formal-module").replaceChildren(moduleCard("formal",problem));}
  for(const id of ["practice-preflight","formal-preflight"]){$(id).textContent=state?.port_available?`端口 ${state.settings.robot_port} ${state.port_open?"已开放":"已预留"}`:"接口端口不可用";$(id).className=`preflight-state${state?.port_available?"":" error"}`;}
}
function resultText(event){const r=event.response;if(!r)return reasonNames[event.reason]||event.reason;
  if(r.measure_result==="direction")return `direction · ${r.svd_deg.toFixed(2)}°`;
  return r.measure_result||r.clear_result||r.exit_reason||(event.path==="/enter"?`accepted · 剩余 ${r.remaining_real_duration_s} 秒`:"accepted");}
function renderEvents(run){
  const key=`${run.run_id}:${run.accepted_actions}:${run.phase}`;if(key===eventStamp)return;eventStamp=key;
  const rows=$("event-rows"),fragment=document.createDocumentFragment(),events=run.events.filter(event=>event.event==="action");
  for(const event of events){const row=el("tr"),p=event.request.position;for(const [i,value] of [event.sequence,event.path,event.request.request_id,p?`(${p.x.toFixed(2)}, ${p.y.toFixed(2)}) / ${event.request.channel}`:"—",resultText(event),event.response.virtual_time_s.toFixed(6)].entries())row.append(el("td",i===2?"request-id":"",String(value)));fragment.append(row);}
  rows.replaceChildren(fragment);$("event-empty").hidden=events.length>0;$("event-empty").textContent=run.phase==="ended"?"本局没有已接受的动作":"等待机器狗调用 /enter";
  if($("follow-log").checked)$("live-feed").scrollTop=$("live-feed").scrollHeight;
}
function renderRun(){
  const run=state?.session;$("resume").hidden=!run||screen==="run";if(!run)return;
  $("run-problem").textContent=`问题${run.problem}`;$("run-mode").textContent=run.mode==="formal"?"正式":"演练";$("run-mode").className=`run-title-mode-${run.mode}`;
  $("run-phase").textContent=phaseNames[run.phase];$("case-code").textContent=run.case_code;
  $("countdown-panel").hidden=run.phase!=="countdown";$("countdown-value").textContent=run.countdown;
  $("real-label").textContent=run.entered?"现实可用时间剩余":"测试窗口剩余";
  $("real-clock").textContent=run.phase==="countdown"?"25:00":minutes(run.remaining_real_s);
  $("virtual-clock").textContent=hms(run.virtual_time_s);$("port-status").textContent=state.port_open?"已开放":"未开放";$("endpoint").textContent=state.robot_endpoint.replace("0.0.0.0",location.hostname);
  $("program-clock").textContent=run.entered?`程序剩余 ${minutes(run.program_remaining_s)} / 窗口剩余 ${minutes(run.window_remaining_s)}`:"等待 /enter";
  $("position").textContent=`x ${run.position.x.toFixed(2)} / y ${run.position.y.toFixed(2)} / CH ${run.current_channel}`;$("cleared").textContent=`已清除 ${run.cleared_count} 个`;
  $("abort").hidden=run.phase==="ended";$("abort").disabled=busy;$("return-module").hidden=run.phase!=="ended";$("return-module").disabled=busy||state.closing_listener;
  $("package-result").hidden=run.phase!=="ended";$("end-reason").textContent=reasonNames[run.end_reason]||run.end_reason;$("package-name").textContent=run.log_file_name||"记录未完成打包";
  $("export-package").href=`/api/runs/${encodeURIComponent(run.run_id)}/package`;$("export-package").classList.toggle("disabled",!run.log_file_name);
  const counts=Flow.publicCounts(run);$("practice-counts").textContent=counts?`本次案例含干扰源 ${counts.total} 个，其中全向 ${counts.omni} 个、定向 ${counts.directional} 个。`:"";
  $("show-scene").hidden=!counts;$("event-hint").textContent=`显示最近 ${state.settings.event_limit} 条事件；完整动作保存在本地日志。`;renderEvents(run);
}
function fillSettings(){if(!state)return;const s=state.settings;$("robot-id").value=s.robot_id;$("robot-port").value=s.robot_port;$("event-limit").value=s.event_limit;$("practice-seed").value=s.practice_seed;}
function render(){
  if(!state)return;$("header-robot").textContent=state.settings.robot_id;$("batch-info").textContent=`当前轮次：${state.settings.batch_id} · 问题3剩余 ${state.attempts["3"].remaining} 次 · 问题4剩余 ${state.attempts["4"].remaining} 次`;
  const active=state.session&&state.session.phase!=="ended";
  for(const id of ["robot-id","robot-port","event-limit","practice-seed","save-settings","new-batch","use-scene","reset-scene"])$(id).disabled=!!active||busy||state.closing_listener;
  renderModules();renderRun();
}
function openFlow(value){flow=value;renderFlow();if(!$("confirmation").open)$("confirmation").showModal();}
function renderFlow(){const copy=Flow.text(flow);$("confirm-title").textContent=copy.title;$("confirm-message").textContent=copy.message;$("confirm-next").textContent=copy.confirm;$("confirm-cancel").textContent=copy.cancel;$("confirm-cancel").hidden=!copy.cancel;$("confirm-next").className=flow.kind==="abort"?"danger-button":"primary-button";}
function cancelFlow(){flow=Flow.cancel().flow;$("confirmation").close();}
$("confirm-cancel").addEventListener("click",cancelFlow);$("confirmation").addEventListener("cancel",event=>{event.preventDefault();cancelFlow();});
$("confirm-next").addEventListener("click",()=>{const result=Flow.next(flow);flow=result.flow;if(flow){renderFlow();return;}$("confirmation").close();const action=result.action;if(!action)return;if(action.kind==="formal")startRun("formal",action.problem);if(action.kind==="abort")guarded(()=>api("/api/abort",{confirmed:true}));if(action.kind==="batch")guarded(async()=>{await api("/api/new-batch",{confirmed:true});notify("已创建新的本地评测轮次，历史记录已保留。");});});
$("abort").addEventListener("click",()=>openFlow(Flow.begin("abort")));$("new-batch").addEventListener("click",()=>openFlow(Flow.begin("batch")));
async function guarded(fn){if(busy)return;busy=true;render();try{await fn();await refresh(true);}catch(error){notify(error.message,true);}finally{busy=false;render();}}
function startRun(mode,problem){return guarded(async()=>{const data={mode,problem};if(mode==="formal")data.confirmed=true;else if(customScene&&(customScene.problem_no??customScene.problem)===problem)data.scenario=customScene;const run=await api("/api/start",data);state.session=run;eventStamp="";$("notification").hidden=true;setPage("run");});}
$("return-module").addEventListener("click",()=>guarded(async()=>{const run=state.session;await api("/api/clear-finished",{});state.session=null;setPage(run.mode==="formal"?`formal${run.problem}`:"practice");}));
$("settings-form").addEventListener("submit",event=>{event.preventDefault();guarded(async()=>{await api("/api/configure",{robot_id:$("robot-id").value,robot_port:Number($("robot-port").value),event_limit:Number($("event-limit").value),practice_seed:$("practice-seed").value});$("settings-message").textContent="设置已保存";});});
$("generate").addEventListener("click",()=>guarded(async()=>{$("scene-editor").value=JSON.stringify(await api("/api/generate",{problem:Number($("scene-problem").value),seed:$("scene-seed").value}),null,2);}));
$("use-scene").addEventListener("click",()=>{try{const scene=JSON.parse($("scene-editor").value),problem=scene.problem_no??scene.problem;if((scene.format!=="jammers-offline-v1"&&scene.schema_version!=="scenario-v1")||![3,4].includes(problem)||!Array.isArray(scene.jammers))throw new Error("请使用有效的 scenario-v1 或 jammers-offline-v1 场景");customScene=scene;$("custom-note").textContent=`已应用到问题${problem}演练：${scene.jammers.length} 个源`;$("scene-mode").textContent="演练使用自定义场景";notify(`问题${problem}演练将使用已应用的场景；正式模式不受影响。`);setPage("practice");}catch(error){notify(error.message,true);}});
$("reset-scene").addEventListener("click",()=>{customScene=null;$("custom-note").textContent="";$("scene-mode").textContent="当前使用自动生成场景";});
$("import-scene").addEventListener("change",async event=>{const file=event.target.files[0];if(!file)return;try{if(file.size>65536)throw new Error("场景文件不能超过64 KiB");$("scene-editor").value=JSON.stringify(JSON.parse(await file.text()),null,2);}catch(error){notify(error.message,true);}finally{event.target.value="";}});
$("download-scene").addEventListener("click",()=>{try{const data=JSON.stringify(JSON.parse($("scene-editor").value),null,2),url=URL.createObjectURL(new Blob([data],{type:"application/json"})),link=el("a");link.href=url;link.download="offline-scenario.json";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){notify(error.message,true);}});
$("close-preview").addEventListener("click",()=>$("scene-preview").close());
$("show-scene").addEventListener("click",()=>{const run=state.session,counts=Flow.publicCounts(run);if(!counts||!run.scenario)return;$("preview-counts").textContent=`共 ${counts.total} 个源 · 全向 ${counts.omni} · 定向 ${counts.directional} · 绿色为已清除，橙色为未清除`;$("scene-preview").showModal();drawMap(run);});
function drawMap(run){const canvas=$("map"),ctx=canvas.getContext("2d"),w=canvas.width,h=canvas.height,range=Math.max(2050,...run.trace.map(p=>Math.max(Math.abs(p.x),Math.abs(p.y))*1.1)),scale=Math.min(w-70,h-50)/(2*range),X=x=>w/2+x*scale,Y=y=>h/2-y*scale;ctx.clearRect(0,0,w,h);ctx.strokeStyle="#dce4e7";ctx.font="11px Consolas";ctx.fillStyle="#78878b";const step=range<3000?500:10**Math.floor(Math.log10(range));for(let v=-Math.floor(range/step)*step;v<=range;v+=step){ctx.beginPath();ctx.moveTo(X(v),20);ctx.lineTo(X(v),h-20);ctx.moveTo(20,Y(v));ctx.lineTo(w-20,Y(v));ctx.stroke();ctx.fillText(String(v),X(v)+3,h-9);}ctx.setLineDash([4,4]);ctx.strokeStyle="#8cbab0";ctx.beginPath();ctx.arc(X(0),Y(0),1800*scale,0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);ctx.strokeStyle="#578ea5";ctx.beginPath();run.trace.forEach((p,i)=>i?ctx.lineTo(X(p.x),Y(p.y)):ctx.moveTo(X(p.x),Y(p.y)));ctx.stroke();for(const source of run.scenario.jammers){ctx.fillStyle=run.cleared_channels.includes(source.channel)?"#21806a":"#c88228";ctx.beginPath();ctx.arc(X(source.x),Y(source.y),4,0,Math.PI*2);ctx.fill();ctx.fillText(`CH${source.channel}`,X(source.x)+7,Y(source.y)-6);if(source.kind==="directional"){ctx.strokeStyle=ctx.fillStyle;const a=source.direction_deg*Math.PI/180;ctx.beginPath();ctx.moveTo(X(source.x),Y(source.y));ctx.lineTo(X(source.x)+18*Math.cos(a),Y(source.y)-18*Math.sin(a));ctx.stroke();}}ctx.fillStyle="#2d62aa";ctx.beginPath();ctx.arc(X(run.position.x),Y(run.position.y),5,0,Math.PI*2);ctx.fill();}
async function loadHistory(){history=(await api("/api/history")).runs;moduleStamp="";}
async function refresh(force=false){
  state=await api("/api/status");const stamp=`${state.settings.robot_id}:${state.settings.batch_id}:${state.session?.run_id}:${state.session?.phase}`;
  if(force||stamp!==historyStamp){await loadHistory();historyStamp=stamp;}
  if(!initialized){initialized=true;fillSettings();if(state.session)setPage("run");}
  render();if(state.port_error)notify(state.port_error,true);if(state.session?.io_error)notify(state.session.io_error,true);
  const run=state.session;if(run?.phase==="ended"&&completed!==run.run_id&&!flow){completed=run.run_id;const counts=Flow.publicCounts(run);openFlow(Flow.begin("complete",{title:`问题${run.problem}${run.mode==="formal"?"正式":"演练"}测试已结束`,message:`${reasonNames[run.end_reason]||run.end_reason}。${counts?`\n本次案例含干扰源 ${counts.total} 个，其中全向 ${counts.omni} 个、定向 ${counts.directional} 个。`:""}\n${run.log_file_name?"行为日志已保存到本机。":"行为日志未完成打包，请保留已有记录。"}`}));}
}
async function poll(){try{await refresh();}catch(error){notify(`无法连接本地程序：${error.message}`,true);}setTimeout(poll,500);}
poll();
