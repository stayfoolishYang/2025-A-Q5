/* Pure transitions are shared with the executable UI-flow tests. */
(function(root){
  "use strict";
  const API={
    begin(kind,context={}){return {kind,step:1,...context};},
    next(flow){if(!flow||flow.kind==="complete")return {flow:null,action:null};if(flow.step===1)return {flow:{...flow,step:2},action:null};return {flow:null,action:{kind:flow.kind,problem:flow.problem}};},
    cancel(){return {flow:null,action:null};},
    text(flow){
      if(flow.kind==="formal")return flow.step===1?{title:"开始正式测试",message:`即将开始问题${flow.problem}正式测试。当前剩余 ${flow.remaining} 次机会，是否继续？`,confirm:"继续",cancel:"取消"}:{title:"再次确认开始",message:`启动成功后将占用问题${flow.problem}的一次离线正式测试机会。中止测试也不会退回次数，确定开始吗？`,confirm:"确认开始",cancel:"取消"};
      if(flow.kind==="abort")return flow.step===1?{title:"中止测试",message:"确定要中止本次测试吗？",confirm:"中止测试",cancel:"继续测试"}:{title:"再次确认中止",message:"中止后本次测试立即结束。正式测试已使用的机会不会退回，确定继续吗？",confirm:"确认中止",cancel:"继续测试"};
      if(flow.kind==="batch")return flow.step===1?{title:"新建本地评测轮次",message:"新一轮的问题3和问题4各有3次离线正式测试机会。已有历史记录将保留。",confirm:"继续",cancel:"取消"}:{title:"确认新建轮次",message:"此操作只影响本地评测。确认创建新一轮吗？",confirm:"确认新建",cancel:"取消"};
      return {title:flow.title,message:flow.message,confirm:"确认",cancel:""};
    },
    canStart(state,mode,problem){return !!state&&!state.closing_listener&&state.port_available&&(!state.session||state.session.phase==="ended")&&(mode!=="formal"||state.attempts[String(problem)].remaining>0);},
    publicCounts(run){return run?.mode==="practice"&&run?.counts_available?{total:run.source_count,omni:run.omni_count,directional:run.directional_count}:null;}
  };
  if(typeof module!=="undefined"&&module.exports)module.exports=API;else root.JammersFlow=API;
})(typeof window!=="undefined"?window:this);
