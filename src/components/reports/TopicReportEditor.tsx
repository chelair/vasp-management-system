import {useEffect,useRef,useState} from 'react';
import {Alert,App,Button,Card,Collapse,Drawer,Empty,Input,Select,Space,Spin,Tag,Typography} from 'antd';
import {editTopic,exportTopic,fetchTopic,previewTopic,regenerateTopicParagraph,resolveTopic,saveTopic} from '../../api/topicReports';
import type {TopicBlock,TopicEdit,TopicReport} from '../../api/topicReports';
import './ReportCompositionEditor.css';

const uid=()=>Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');
const stages:Record<string,string>={prepared:'已检查数据',planned:'已组织元素',draft:'可编辑草案',saved:'已保存'};
const showText=(doc:TopicReport,b:TopicBlock)=>doc.narratives[b.block_id]?.user_text??doc.narratives[b.block_id]?.ai_text??b.text??'';
const toEdit=(doc:TopicReport):TopicEdit=>({expected_revision:doc.revision,title:doc.title,sections:doc.sections,
  blocks:doc.blocks.map(b=>({block_id:b.block_id,title:b.title,section:b.section,...(b.origin==='ai_text'?{text:showText(doc,b)}:{})})),
  hidden_block_ids:doc.hidden_block_ids,deleted_block_ids:doc.deleted_block_ids});

export default function TopicReportEditor({topicId,connectionId,onClose,onSaved}: {topicId:string;connectionId?:string|null;onClose:()=>void;onSaved?:()=>void}) {
  const {message,modal}=App.useApp();
  const [doc,setDoc]=useState<TopicReport>();
  const [draft,setDraft]=useState<TopicEdit>();
  const [dirty,setDirty]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [html,setHtml]=useState('');
  const [selected,setSelected]=useState<string>();
  const [relations,setRelations]=useState<Record<string,number>>({});
  const [tasks,setTasks]=useState<Record<string,string>>({});
  const [observations,setObservations]=useState<Record<string,string>>({});
  const [adsReference,setAdsReference]=useState<string>();
  const [reference,setReference]=useState<string>();
  const alive=useRef(true);
  useEffect(()=>{
    alive.current=true;setBusy(true);
    fetchTopic(topicId).then(async value=>{if(!alive.current)return;setDoc(value);setDraft(toEdit(value));setDirty(false);const p=await previewTopic(topicId);if(alive.current)setHtml(p.html);})
      .catch(e=>{if(alive.current)setError(e.message);}).finally(()=>{if(alive.current)setBusy(false);});
    return()=>{alive.current=false;};
  },[topicId]);
  const run=async(fn:()=>Promise<void>)=>{setBusy(true);setError('');try{await fn();}catch(e){if(alive.current)setError((e as Error).message);}finally{if(alive.current)setBusy(false);}};
  const accept=async(value:TopicReport)=>{
    if(!alive.current)return;setDoc(value);setDraft(toEdit(value));setDirty(false);onSaved?.();
    const p=await previewTopic(topicId);if(alive.current)setHtml(p.html);
  };
  const change=(next:TopicEdit)=>{setDraft(next);setDirty(true);};
  const patch=(id:string,value:Partial<TopicEdit['blocks'][number]>)=>draft&&change({...draft,blocks:draft.blocks.map(b=>b.block_id===id?{...b,...value}:b)});
  const save=()=>draft&&run(async()=>{let value=await editTopic(topicId,draft);if(['draft','saved'].includes(value.stage))value=await saveTopic(topicId,value.revision);await accept(value);message.success('专题报告已保存');});
  const exportFile=(print=false)=>run(async()=>{
    const url=await exportTopic(topicId,print);
    if(print){const frame=document.createElement('iframe');frame.style.display='none';frame.src=url;document.body.appendChild(frame);setTimeout(()=>{frame.remove();URL.revokeObjectURL(url);},60000);}
    else{const a=document.createElement('a');a.href=url;a.download=(doc?.title||'专题报告')+'.html';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  });
  const close=()=>{if(!dirty)return onClose();modal.confirm({title:'有未保存修改，是否放弃？',okText:'放弃修改',cancelText:'继续编辑',onOk:onClose});};
  const blockById=(id:string)=>doc?.blocks.find(b=>b.block_id===id)||doc?.data.library.blocks.find(b=>b.block_id===id);
  const add=()=>{
    if(!draft||!selected)return;
    const existing=draft.blocks.find(b=>b.block_id===selected);const source=blockById(selected);
    if(existing)change({...draft,hidden_block_ids:draft.hidden_block_ids.filter(id=>id!==selected),deleted_block_ids:draft.deleted_block_ids.filter(id=>id!==selected)});
    else if(source)change({...draft,blocks:[...draft.blocks,{block_id:source.block_id,title:source.title,section:'sources'}]});
  };
  const chooseRelations=()=>doc&&run(async()=>{
    const targets=structuredClone(doc.data.targets);
    for(const choice of doc.data.choices){const index=relations[choice.label];if(index==null||!choice.relations)continue;const item=choice.relations[index];const ti=targets.findIndex(t=>t.label===choice.label);if(ti>=0)targets[ti]={label:choice.label,pristine:item.pristine,defect:item.defect,removed_oxygen_index:item.removed_oxygen_index};}
    for(const choice of doc.data.choices){const tid=tasks[choice.label];const item=choice.tasks?.find(t=>t.task_id===tid);const ti=targets.findIndex(t=>t.label===(choice.target_label||choice.label));if(item&&ti>=0&&choice.role)targets[ti]={...targets[ti],[choice.role]:item.selector};}
    for(const choice of doc.data.choices){const index=relations[choice.label];const item=index==null?undefined:choice.adsorption_relations?.[index];const ti=targets.findIndex(t=>t.label===choice.label);if(item&&ti>=0)targets[ti]={label:choice.label,complex:item.complex,surface:item.surface,adsorbate:item.adsorbate};}
    for(const input of doc.data.science?.inputs||[]){const observation=observations[input.role];if(!observation||!input.task)continue;const [index,role]=input.role.split('.');const target=targets[Number(index)];const selector=target?.[role] as Record<string,string>|undefined;if(selector?.task_id===input.task.task_id)target[role]={...selector,observation_id:observation};}
    await accept(await resolveTopic(topicId,{expected_revision:doc.revision,targets,...(reference?{reference_report_id:reference}:{}),...(adsReference?{adsorbate_reference_type:adsReference}:{})}));
    message.info('已按明确选择更新数据，旧版本保留；可继续在原对话请求组织报告文字。');
  });
  return <Drawer open title="专题科研报告" width="94vw" onClose={close} destroyOnClose>
    {error&&<Alert type="error" message={error} showIcon style={{marginBottom:12}}/>}
    {!doc||!draft?<Spin/>:<div className="rb-editor-grid">
      <div className="rb-editor-controls">
        <Space wrap><Tag>{stages[doc.stage]||doc.stage}</Tag><Typography.Text type="secondary">版本 {doc.revision}</Typography.Text>
          <Button type="primary" aria-label="保存专题科研报告" disabled={!dirty||busy} loading={busy} onClick={save}>保存报告与预览</Button>
          <Button disabled={dirty||busy} onClick={()=>void exportFile()}>下载 HTML</Button>
          <Button disabled={dirty||busy} onClick={()=>void exportFile(true)}>PDF 打印</Button>
        </Space>
        {['prepared','planned'].includes(doc.stage)&&<Alert type="warning" showIcon message="报告尚未生成完成" description="当前只完成数据检查，尚无 AI 科研正文。请查看下方具体缺口、确认任务与参考态，再在原对话继续生成；已有计算数据不代表已通过科学校验。"/>}
        {doc.stage==='prepared'&&<Button disabled={dirty||busy} onClick={()=>void run(async()=>{await accept(await resolveTopic(topicId,{expected_revision:doc.revision}));setTasks({});setRelations({});setObservations({});})}>重新检查已有数据</Button>}
        {dirty&&<Alert type="info" message="已修改；保存后预览和导出使用同一份内容。"/>}
        {doc.freshness?.stale&&<Alert type="warning" message="上游数据可能过期；本报告保留生成时的证据，未自动替换。"/>}
        <Input aria-label="专题报告标题" value={draft.title} onChange={e=>change({...draft,title:e.target.value})}/>
        <Collapse items={[
          {key:'question',label:'原始研究问题与数据缺口',children:<><Typography.Paragraph>{doc.original_question}</Typography.Paragraph>{doc.data.gaps.map((g,i)=><p key={i}><Tag>{g.status}</Tag>{g.detail}</p>)}</>},
          {key:'sections',label:'编辑章节标题',children:draft.sections.map((section,i)=><Input key={section.section_id} aria-label={`章节标题-${section.section_id}`} value={section.title} onChange={e=>change({...draft,sections:draft.sections.map((s,j)=>i===j?{...s,title:e.target.value}:s)})}/>)},
        ]}/>
        {(doc.data.choices.some(c=>(c.relations&&c.relations.length>1)||(c.role&&c.tasks&&c.tasks.length>0))||doc.data.reference_candidates.length>1||doc.request.property_id==='adsorption.simple')&&<Card size="small" title="确认任务、位点和参考态">
          {doc.data.choices.filter(c=>c.relations&&c.relations.length>1).map(choice=><Select key={choice.label} aria-label={`${choice.label}-氧位点`} style={{width:'100%',marginBottom:8}} placeholder={`${choice.label}：选择完整/缺陷任务和氧位点`} value={relations[choice.label]}
            options={choice.relations!.map((r,i)=>({value:i,label:`${r.pristine.task_id} → ${r.defect.task_id} · O原子 ${r.removed_oxygen_index} · ${r.site.fractional.join(', ')}`}))}
            onChange={value=>setRelations(old=>({...old,[choice.label]:value}))}/>)}
          {doc.data.choices.filter(c=>c.role&&c.tasks&&c.tasks.length>0).map(choice=><Select key={choice.label} aria-label={`${choice.label}-候选任务`} style={{width:'100%',marginBottom:8}} placeholder={`${choice.label}：选择候选任务`} value={tasks[choice.label]} onChange={value=>setTasks(old=>({...old,[choice.label]:value}))} options={choice.tasks!.map(t=>({value:t.task_id,label:`${t.model_name} · ${t.task_id}`}))}/>)}
          {doc.data.choices.filter(c=>c.adsorption_relations&&c.adsorption_relations.length>1).map(choice=><Select key={choice.label} aria-label={`${choice.label}-吸附位点`} style={{width:'100%',marginBottom:8}} placeholder={`${choice.label}：选择复合体系、表面及吸附物参考`} value={relations[choice.label]} options={choice.adsorption_relations!.map((r,i)=>({value:i,label:`${r.complex.task_id} − ${r.surface.task_id} − ${r.adsorbate.task_id} · 吸附原子 ${r.site.adsorbate_atom_indices.join(', ')}`}))} onChange={value=>setRelations(old=>({...old,[choice.label]:value}))}/>)}
          {(doc.data.science?.inputs||[]).filter(input=>(input.observations?.length||0)>1).map(input=><Select key={input.role} aria-label={`${input.role}-计算快照`} style={{width:'100%',marginBottom:8}} placeholder={`${input.task?.model_name||input.role}：选择计算目录快照`} value={observations[input.role]} onChange={value=>setObservations(old=>({...old,[input.role]:value}))} options={input.observations!.map(o=>({value:o.observation_id,label:`${o.directory.path||'目录身份未知'} · ${o.archive}`}))}/>)}
          {doc.request.property_id==='adsorption.simple'&&<Select aria-label="专题吸附物参考类型" style={{width:'100%',marginBottom:8}} value={adsReference||doc.request.adsorbate_reference_type||'periodic'} onChange={setAdsReference} options={[{value:'periodic',label:'严格模式：参考使用相同k网格'},{value:'isolated_molecule',label:'确认孤立/气相分子参考：Gamma单点网格'}]}/>}
          {doc.data.reference_candidates.length>1&&<Select aria-label="专题氧参考" style={{width:'100%',marginBottom:8}} placeholder="选择已有明确设置的氧参考" value={reference} onChange={setReference}
            options={doc.data.reference_candidates.map(r=>({value:r.report_id,label:`${r.reference.value_ev_per_O} eV/O · ${r.reference.source} · ${r.reference.conditions}`}))}/>}
          <Button disabled={dirty||busy} onClick={()=>void chooseRelations()}>应用明确选择</Button>
        </Card>}
        <Space.Compact style={{width:'100%'}}><Select aria-label="相关报告元素" style={{flex:1}} showSearch optionFilterProp="label" placeholder="增加相关的冻结报告元素" value={selected} onChange={setSelected}
          options={doc.data.candidates.map(c=>({value:c.block_id,label:c.title+' · '+c.type}))}/><Button onClick={add} disabled={!selected||busy||draft.blocks.length>=40}>增加元素</Button></Space.Compact>
        <Button disabled={busy||draft.blocks.length>=40} onClick={()=>change({...draft,blocks:[...draft.blocks,{block_id:'draft_txt_'+uid(),title:'补充讨论',section:'discussion',text:'请基于已列出的事实补充解释；未验证的内容应明确标为假设。'}]})}>增加文字</Button>
        {!draft.blocks.length&&<Empty description="暂无元素"/>}
        {draft.blocks.map((block,index)=>{
          const source=blockById(block.block_id);const isText=source?.origin==='ai_text'||block.block_id.startsWith('draft_txt_');
          const deleted=draft.deleted_block_ids.includes(block.block_id);const hidden=draft.hidden_block_ids.includes(block.block_id);
          return <Card key={block.block_id} size="small" data-topic-block={block.block_id} style={{opacity:deleted ? 0.5 : 1}} title={<Space><Tag>{source?.origin==='r2'?'计算证据':isText?'解释文字':'冻结事实'}</Tag>{deleted&&<Tag>已删除</Tag>}{hidden&&<Tag>已隐藏</Tag>}</Space>}>
            <Input aria-label="元素标题" value={block.title} onChange={e=>patch(block.block_id,{title:e.target.value})}/>
            <Select aria-label="元素章节" style={{width:'100%',marginTop:8}} value={block.section} options={draft.sections.map(s=>({value:s.section_id,label:s.title}))} onChange={value=>patch(block.block_id,{section:value})}/>
            {isText?<>
              <Input.TextArea aria-label="专题段落文字" value={block.text||''} autoSize={{minRows:3,maxRows:12}} maxLength={4000} onChange={e=>patch(block.block_id,{text:e.target.value})}/>
              <Select aria-label="引用可信事实" allowClear value={undefined} style={{width:'100%',margin:'8px 0'}} placeholder="插入可信数值引用；数值随冻结事实展开" options={doc.data.facts.map(f=>({value:f.fact_id,label:`${f.fact_id} · ${f.label} · ${f.value} ${f.units}`}))}
                onChange={key=>{if(key)patch(block.block_id,{text:(block.text||'')+` [[${key}]]`});}}/>
              <Button size="small" disabled={dirty||busy||!connectionId||!source} onClick={()=>void run(async()=>accept(await regenerateTopicParagraph(topicId,block.block_id,doc.revision,connectionId!)))}>重新生成本段</Button>
            </>:source?.origin!=='r2'&&<Typography.Paragraph ellipsis={{rows:5,expandable:true,symbol:'展开冻结内容'}} style={{whiteSpace:'pre-wrap'}}>{source?.text}</Typography.Paragraph>}
            <Space wrap style={{marginTop:8}}>
              <Button size="small" aria-label="上移专题元素" disabled={index===0} onClick={()=>{const blocks=[...draft.blocks];[blocks[index-1],blocks[index]]=[blocks[index],blocks[index-1]];change({...draft,blocks});}}>上移</Button>
              <Button size="small" aria-label="下移专题元素" disabled={index===draft.blocks.length-1} onClick={()=>{const blocks=[...draft.blocks];[blocks[index+1],blocks[index]]=[blocks[index],blocks[index+1]];change({...draft,blocks});}}>下移</Button>
              <Button size="small" onClick={()=>change({...draft,hidden_block_ids:hidden?draft.hidden_block_ids.filter(id=>id!==block.block_id):[...draft.hidden_block_ids,block.block_id]})}>{hidden?'显示':'隐藏'}</Button>
              <Button size="small" aria-label={deleted?'恢复专题元素':'删除专题元素'} onClick={()=>change({...draft,deleted_block_ids:deleted?draft.deleted_block_ids.filter(id=>id!==block.block_id):[...draft.deleted_block_ids,block.block_id]})}>{deleted?'恢复':'删除'}</Button>
            </Space>
          </Card>;
        })}
      </div>
      <div className="rb-editor-preview"><iframe title="专题科研报告预览" sandbox="allow-scripts allow-modals" srcDoc={html} style={{width:'100%',height:'calc(100vh - 150px)',border:'1px solid #ddd'}}/></div>
    </div>}
  </Drawer>;
}
